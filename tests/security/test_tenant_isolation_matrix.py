"""Two-tenant attacks against the real P1-01 infrastructure boundaries."""

from __future__ import annotations

import os
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from uuid import UUID, uuid4

import boto3
import httpx
import pytest
from autonoesis_adapters import (
    Boto3ObjectStore,
    MinioEvidenceStore,
    PostgreSQLPlatformStore,
    SqlKillSwitchStore,
    SqlPlatformKillSwitchStore,
)
from autonoesis_api.main import build_app
from autonoesis_application import AuditEvent, RecordNotFound
from autonoesis_capability import parse_manifest
from autonoesis_domain import (
    AgentVersion,
    AssetStage,
    BudgetAmount,
    CandidateStatus,
    CandidateVersion,
    DataClassification,
    DeploymentStatus,
    GoalContract,
    ImprovementProposal,
    ImprovementTarget,
    JsonObject,
    LoopPolicy,
    MemoryRecord,
    Release,
    RiskTier,
    SubjectRef,
    SuccessCriterion,
    Trial,
)
from autonoesis_runtime import (
    IsolationRiskPool,
    KillSwitchQuery,
    TenantNamespaces,
    TenantTelemetryRecord,
)
from autonoesis_worker.contracts import (
    CancelRunInput,
    EvaluateRunInput,
    ExecuteRunInput,
    GoalRunInput,
    PrepareRunInput,
    RejectRunInput,
    TakeOverRunInput,
)
from autonoesis_worker.dispatcher import TemporalRunWorkflowControl, workflow_id_for_run
from autonoesis_worker.workflows import GoalRunWorkflow
from sqlalchemy import func, select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from temporalio import activity
from temporalio.client import Client
from temporalio.worker import Worker
from temporalio.worker.workflow_sandbox import SandboxedWorkflowRunner

REQUIRED_ENV = (
    "AUTONOESIS_TEST_DATABASE_URL",
    "AUTONOESIS_TEST_ADMIN_DATABASE_URL",
    "AUTONOESIS_TEST_BREAKGLASS_DATABASE_URL",
    "AUTONOESIS_TEST_MINIO_URL",
    "AUTONOESIS_TEST_TEMPORAL_TARGET",
)
pytestmark = pytest.mark.skipif(
    not all(os.getenv(name) for name in REQUIRED_ENV),
    reason="requires PostgreSQL app/admin/break-glass roles, MinIO, and Temporal",
)


@activity.defn(name="prepare_run")
async def isolation_prepare(input: PrepareRunInput) -> str:
    return f"planned:{input.tenant_id}"


@activity.defn(name="execute_run")
async def isolation_execute(input: ExecuteRunInput) -> str:
    return f"executed:{input.tenant_id}"


@activity.defn(name="evaluate_run")
async def isolation_evaluate(input: EvaluateRunInput) -> str:
    return "succeeded"


@activity.defn(name="cancel_run")
async def isolation_cancel(input: CancelRunInput) -> str:
    return "cancelled"


@activity.defn(name="reject_run")
async def isolation_reject(input: RejectRunInput) -> str:
    return "rejected"


@activity.defn(name="take_over_run")
async def isolation_takeover(input: TakeOverRunInput) -> str:
    return "taken_over"


ACTIVITIES = (
    isolation_prepare,
    isolation_execute,
    isolation_evaluate,
    isolation_cancel,
    isolation_reject,
    isolation_takeover,
)


async def provision_tenants(*tenant_ids: UUID) -> None:
    engine = create_async_engine(os.environ["AUTONOESIS_TEST_ADMIN_DATABASE_URL"])
    try:
        async with engine.begin() as connection:
            for tenant_id in tenant_ids:
                await connection.execute(
                    text(
                        "INSERT INTO tenants (id, name, created_at) "
                        "VALUES (:id, :name, CURRENT_TIMESTAMP) ON CONFLICT (id) DO NOTHING"
                    ),
                    {"id": str(tenant_id), "name": f"p101-{tenant_id}"},
                )
    finally:
        await engine.dispose()


def goal_for(tenant_id: UUID) -> GoalContract:
    return GoalContract(
        tenant_id=tenant_id,
        goal_type="isolation.verify",
        statement="verify tenant isolation",
        desired_outcome="other tenants remain invisible",
        subject_refs=(SubjectRef("security", "tenant", str(tenant_id)),),
        success_criteria=(SuccessCriterion("isolated", "tenant is isolated", "matrix"),),
        constraints=("no cross-tenant access",),
        owner_id=uuid4(),
        risk_tier=RiskTier.LOW,
        budget_limit=BudgetAmount(100),
        deadline=datetime.now(UTC) + timedelta(hours=1),
        input_payload=JsonObject.from_value({"logical_name": "same-name"}),
    )


def audit_for(goal: GoalContract) -> AuditEvent:
    return AuditEvent(
        goal.tenant_id,
        goal.owner_id,
        goal.owner_id,
        "goal.created",
        "goal",
        str(goal.goal_id),
        uuid4(),
        {"source": "p1-01-attack-matrix"},
    )


async def add_release(store: PostgreSQLPlatformStore, tenant_id: UUID) -> Release:
    proposal = ImprovementProposal(
        tenant_id,
        ImprovementTarget.AGENT_INSTRUCTION,
        uuid4(),
        ("evidence://isolation",),
        "tenant baseline",
        "tenant candidate",
        "same-suite",
        "restore tenant baseline",
        "isolated-generator",
    )
    await store.add_proposal(proposal)
    candidate = CandidateVersion(
        tenant_id, proposal.proposal_id, uuid4(), "artifact://same-name", "isolated-generator"
    )
    await store.add_candidate(candidate)
    for status in (
        CandidateStatus.EVALUATING,
        CandidateStatus.AWAITING_APPROVAL,
        CandidateStatus.APPROVED,
    ):
        candidate = candidate.transition_to(status)
        await store.save_candidate(candidate)
    deployment = candidate.begin_deployment(actor_id=uuid4(), reason="isolation shadow")
    await store.add_deployment(deployment)
    for status in (DeploymentStatus.CANARY, DeploymentStatus.STABLE):
        deployment = deployment.transition_to(status, actor_id=uuid4(), reason="isolation gate")
        await store.save_deployment(deployment)
    release = Release.from_stable_deployment(
        deployment,
        stable_version_id=uuid4(),
        previous_stable_version_id=candidate.baseline_version_id,
        approved_by=uuid4(),
    )
    await store.add_release(release)
    return release


def identity_headers(tenant_id: UUID, actor_id: UUID) -> dict[str, str]:
    return {
        "X-Tenant-ID": str(tenant_id),
        "X-Actor-ID": str(actor_id),
        "X-Roles": "tenant_admin,operator,auditor",
    }


def capability_manifest() -> dict[str, object]:
    return {
        "api_version": "autonoesis/v1alpha1",
        "pack_id": "same-name",
        "version": "1.0.0",
        "python_entry_point": "same_name.plugin:create",
        "goal_types": [
            {
                "goal_type": "isolation.verify",
                "input_schema": {"type": "object"},
                "agent": "same-name",
                "evaluation_suite": "same-suite",
                "default_policy": "same-name",
                "default_budget": 100,
            }
        ],
        "skills": ["same-name"],
        "tools": ["same-name"],
        "policies": ["same-name"],
        "evaluation_suites": ["same-suite"],
    }


@pytest.mark.asyncio
async def test_two_tenant_real_infrastructure_attack_matrix() -> None:
    first_tenant, second_tenant = uuid4(), uuid4()
    await provision_tenants(first_tenant, second_tenant)
    first = PostgreSQLPlatformStore.from_url(os.environ["AUTONOESIS_TEST_DATABASE_URL"])
    second = PostgreSQLPlatformStore.from_url(os.environ["AUTONOESIS_TEST_DATABASE_URL"])
    admin = create_async_engine(os.environ["AUTONOESIS_TEST_ADMIN_DATABASE_URL"])
    try:
        # Same logical names remain distinct across configuration, Memory, Evaluation,
        # Telemetry, namespace projections, and Release authority.
        for store, tenant_id, marker in (
            (first, first_tenant, "first"),
            (second, second_tenant, "second"),
        ):
            await store.add_capability_pack(tenant_id, parse_manifest(capability_manifest()))
            await store.add_agent(
                "same-name",
                AgentVersion(
                    tenant_id,
                    uuid4(),
                    1,
                    f"{marker} instruction",
                    "isolated-route",
                    ("same-name",),
                    ("same-name",),
                    LoopPolicy(2, 100, 10, 30),
                    AssetStage.STABLE,
                ),
            )
            await store.add_skill(tenant_id, "same-name", {"version": "1", "marker": marker})
            await store.add_tool(tenant_id, "same-name", {"version": "1", "marker": marker})
            await store.add_policy(tenant_id, "same-name", {"version": "1", "marker": marker})
            await store.add_budget(tenant_id, "same-name", {"version": "1", "marker": marker})
            await store.add_memory(
                MemoryRecord(
                    tenant_id,
                    "same-scope",
                    marker,
                    ("p1-01",),
                    1.0,
                    datetime.now(UTC) + timedelta(days=1),
                    uuid4(),
                )
            )
            await store.add_telemetry(
                TenantTelemetryRecord(tenant_id, "trace", "same-trace", {"marker": marker})
            )
            await store.add_trial(Trial(tenant_id, "same-suite", "1", uuid4(), "harness@1"))
            namespaces = TenantNamespaces(tenant_id)
            for resource_kind, physical in namespaces.resource_registry(
                "same-name", IsolationRiskPool.READ
            ).items():
                await store.register_tenant_namespace(
                    tenant_id, resource_kind, "same-name", physical
                )

        assert (await first.list_skills(first_tenant))[0]["definition"]["marker"] == "first"
        assert (await second.list_skills(second_tenant))[0]["definition"]["marker"] == "second"
        assert len(await first.list_capability_packs(first_tenant)) == 1
        assert len(await second.list_capability_packs(second_tenant)) == 1
        assert (await first.list_agents(first_tenant))[0][1].instruction == "first instruction"
        assert (await second.list_agents(second_tenant))[0][1].instruction == "second instruction"
        assert (await first.list_memory(first_tenant))[0].content == "first"
        assert (await second.list_memory(second_tenant))[0].content == "second"
        assert (await first.list_telemetry(first_tenant))[0].payload == {"marker": "first"}
        assert (await second.list_telemetry(second_tenant))[0].payload == {"marker": "second"}
        first_namespaces = {
            (item["resource_kind"], item["physical_namespace"])
            for item in await first.list_tenant_namespaces(first_tenant)
        }
        second_namespaces = {
            (item["resource_kind"], item["physical_namespace"])
            for item in await second.list_tenant_namespaces(second_tenant)
        }
        assert len(first_namespaces) == len(second_namespaces) == 9
        assert first_namespaces.isdisjoint(second_namespaces)

        first_release = await add_release(first, first_tenant)
        await add_release(second, second_tenant)
        with pytest.raises(RecordNotFound):
            await second.get_active_release(second_tenant, first_release.release_id)

        first_goal = goal_for(first_tenant)
        await first.add_goal(first_goal, audit_for(first_goal))
        api = build_app(first)
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=api), base_url="http://tenant.test"
        ) as client:
            unknown = await client.get(
                f"/v1/goals/{uuid4()}", headers=identity_headers(second_tenant, uuid4())
            )
            hostile = await client.get(
                f"/v1/goals/{first_goal.goal_id}",
                headers=identity_headers(second_tenant, uuid4()),
            )
        assert unknown.status_code == hostile.status_code == 404
        assert unknown.json()["error"]["code"] == hostile.json()["error"]["code"]
        assert any(
            event.event_type == "security.tenant_scope_lookup_denied"
            for event in await second.list_audit_events(second_tenant)
        )

        async with admin.connect() as connection:
            unsafe_tables = await connection.scalar(
                text(
                    "SELECT count(*) FROM pg_class c "
                    "JOIN pg_namespace n ON n.oid=c.relnamespace "
                    "JOIN pg_attribute a ON a.attrelid=c.oid "
                    "WHERE n.nspname='public' AND c.relkind='r' AND a.attname='tenant_id' "
                    "AND a.attnum > 0 AND NOT a.attisdropped "
                    "AND (NOT c.relrowsecurity OR NOT c.relforcerowsecurity)"
                )
            )
            assert unsafe_tables == 0
        app_engine = create_async_engine(os.environ["AUTONOESIS_TEST_DATABASE_URL"])
        try:
            async with app_engine.begin() as connection:
                role = (
                    await connection.execute(
                        text(
                            "SELECT rolsuper, rolbypassrls FROM pg_roles WHERE rolname=current_user"
                        )
                    )
                ).one()
                assert role == (False, False)
                await connection.execute(
                    select(func.set_config("app.tenant_id", str(second_tenant), True))
                )
                assert (
                    await connection.scalar(
                        text("SELECT count(*) FROM memory_records WHERE content='first'")
                    )
                    == 0
                )
            with pytest.raises(DBAPIError):
                async with app_engine.begin() as connection:
                    await connection.execute(
                        text(
                            "INSERT INTO platform_kill_switches "
                            "(id, target, reason, activated_by, created_at) "
                            "VALUES (:id, 'platform', 'forbidden', :actor, CURRENT_TIMESTAMP)"
                        ),
                        {"id": str(uuid4()), "actor": str(uuid4())},
                    )
        finally:
            await app_engine.dispose()

        # Real MinIO object keys reject a forged descriptor even when the attacker
        # knows the other tenant's URI, digest, and Evidence ID.
        client = boto3.client(
            "s3",
            endpoint_url=os.environ["AUTONOESIS_TEST_MINIO_URL"],
            aws_access_key_id=os.getenv("AUTONOESIS_TEST_MINIO_ACCESS_KEY", "autonoesis"),
            aws_secret_access_key=os.getenv(
                "AUTONOESIS_TEST_MINIO_SECRET_KEY", "autonoesis-test-only"
            ),
            region_name="us-east-1",
        )
        bucket = f"autonoesis-p101-{uuid4()}"
        client.create_bucket(Bucket=bucket, ObjectLockEnabledForBucket=True)
        artifacts = MinioEvidenceStore(Boto3ObjectStore(client), bucket)
        content, evidence_id = b"same evidence", uuid4()
        digest = sha256(content).hexdigest()
        first_object = await artifacts.store(
            artifacts.describe(
                first_tenant,
                evidence_id,
                digest,
                DataClassification.INTERNAL,
                len(content),
                datetime.now(UTC) + timedelta(days=1),
            ),
            content,
            "text/plain",
        )
        second_object = await artifacts.store(
            artifacts.describe(
                second_tenant,
                evidence_id,
                digest,
                DataClassification.INTERNAL,
                len(content),
                datetime.now(UTC) + timedelta(days=1),
            ),
            content,
            "text/plain",
        )
        assert first_object.artifact_uri != second_object.artifact_uri
        with pytest.raises(LookupError, match="tenant namespace"):
            await artifacts.retrieve_verified(
                replace(first_object, artifact_uri=second_object.artifact_uri)
            )

        # The same Run ID is safe because Workflow IDs, queues, and Worker Pools
        # are tenant-derived. A pool refuses commands from another tenant.
        temporal = await Client.connect(os.environ["AUTONOESIS_TEST_TEMPORAL_TARGET"])
        run_id = uuid4()
        first_queue = TenantNamespaces(first_tenant).workflow_task_queue(IsolationRiskPool.READ)
        second_queue = TenantNamespaces(second_tenant).workflow_task_queue(IsolationRiskPool.READ)
        first_control = TemporalRunWorkflowControl(
            temporal,
            first_queue,
            tenant_id=first_tenant,
            risk_pool=IsolationRiskPool.READ,
        )
        second_control = TemporalRunWorkflowControl(
            temporal,
            second_queue,
            tenant_id=second_tenant,
            risk_pool=IsolationRiskPool.READ,
        )
        first_command = GoalRunInput(
            str(first_tenant),
            str(uuid4()),
            str(run_id),
            (datetime.now(UTC) + timedelta(minutes=2)).timestamp(),
        )
        second_command = replace(first_command, tenant_id=str(second_tenant), goal_id=str(uuid4()))
        async with (
            Worker(
                temporal,
                task_queue=first_queue,
                workflows=[GoalRunWorkflow],
                activities=ACTIVITIES,
                workflow_runner=SandboxedWorkflowRunner(),
            ),
            Worker(
                temporal,
                task_queue=second_queue,
                workflows=[GoalRunWorkflow],
                activities=ACTIVITIES,
                workflow_runner=SandboxedWorkflowRunner(),
            ),
        ):
            first_id = await first_control.start(first_command)
            second_id = await second_control.start(second_command)
            assert first_id != second_id
            assert await temporal.get_workflow_handle(first_id).result() == "succeeded"
            assert await temporal.get_workflow_handle(second_id).result() == "succeeded"
            with pytest.raises(PermissionError, match="another tenant"):
                await first_control.start(second_command)
        assert first_id == workflow_id_for_run(str(first_tenant), str(run_id))

        # Platform control uses a separate non-superuser login and creates a
        # platform audit event; tenant stores can only observe the active stop.
        breakglass_engine = create_async_engine(
            os.environ["AUTONOESIS_TEST_BREAKGLASS_DATABASE_URL"]
        )
        try:
            async with breakglass_engine.connect() as connection:
                breakglass_role = (
                    await connection.execute(
                        text(
                            "SELECT rolsuper, rolbypassrls FROM pg_roles WHERE rolname=current_user"
                        )
                    )
                ).one()
                assert breakglass_role == (False, False)
            platform_switch = SqlPlatformKillSwitchStore(
                async_sessionmaker(breakglass_engine, expire_on_commit=False)
            )
            actor_id, principal_id, correlation_id = uuid4(), uuid4(), uuid4()
            activated = await platform_switch.activate(
                "ticket=SEC-P101; verified isolation incident",
                actor_id,
                principal_id,
                correlation_id,
            )
            assert activated.dimension.value == "platform"
            assert await SqlKillSwitchStore(first.repository.sessions, first_tenant).is_blocked(
                KillSwitchQuery(tenant_id=str(first_tenant))
            )
            assert (await platform_switch.list_audit())[-1]["event_type"] == (
                "platform.kill_switch.activated"
            )
            await platform_switch.deactivate(
                "ticket=SEC-P101; incident resolved", actor_id, principal_id, uuid4()
            )
        finally:
            await breakglass_engine.dispose()
    finally:
        await first.close()
        await second.close()
        await admin.dispose()
