"""Reference Capability Pack vertical E2E over PostgreSQL, Temporal, OPA, and MinIO."""

from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4, uuid5

import boto3
import httpx
import pytest
import yaml
from autonoesis_adapters import (
    Boto3ObjectStore,
    EphemeralCredentialBroker,
    InMemoryDelegationStore,
    InMemoryGatewayAudit,
    JsonSchemaValidator,
    MinioEvidenceStore,
    OPAPolicyAdapter,
    PostgreSQLAtomicExecutionReservations,
    PostgreSQLPlatformStore,
    RegistryControlledEgress,
    SqlKillSwitchStore,
    StaticToolCatalog,
)
from autonoesis_api.main import build_app
from autonoesis_application import (
    CaptureAuthoritativeEvidence,
    CommandContext,
    CompleteTask,
    DecideApproval,
    ExecuteGovernedAction,
    GoalExecutionApplication,
    IdentityContext,
    ProposeAction,
    RequestApproval,
    TaskDefinition,
    VerifyOutcome,
    verify_audit_chain,
)
from autonoesis_domain import (
    Action,
    DataClassification,
    GoalStatus,
    OutcomeStatus,
    RiskLevel,
    RunStatus,
    SubjectRef,
    SuccessCriterion,
    Task,
)
from autonoesis_runtime import (
    CredentialLease,
    GovernedToolGateway,
    ResolvedToolVersion,
    ToolReceipt,
    ToolResultStatus,
)
from autonoesis_worker.activities import (
    ActivityDependencies,
    PreparedRunPlan,
    RunExecutor,
    RunPlanner,
    build_activity_dependencies,
    cancel_run,
    evaluate_run,
    execute_run,
    prepare_run,
    reject_run,
    take_over_run,
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
from autonoesis_worker.workflows import GoalRunWorkflow
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from temporalio import activity
from temporalio.client import Client
from temporalio.worker import Replayer, Worker
from temporalio.worker.workflow_sandbox import SandboxedWorkflowRunner

ROOT = Path(__file__).resolve().parents[2]
REQUIRED_ENV = (
    "AUTONOESIS_TEST_DATABASE_URL",
    "AUTONOESIS_TEST_ADMIN_DATABASE_URL",
    "AUTONOESIS_TEST_MINIO_URL",
    "AUTONOESIS_TEST_OPA_URL",
    "AUTONOESIS_TEST_TEMPORAL_TARGET",
)
pytestmark = pytest.mark.skipif(
    not all(os.getenv(name) for name in REQUIRED_ENV),
    reason="requires PostgreSQL, Temporal, OPA, and MinIO test components",
)

_dependencies: dict[str, ActivityDependencies] = {}
WORKER_ACTOR_ID = UUID(int=0)


def command_context(
    tenant_id: UUID,
    run_id: UUID,
    operation: str,
    *,
    actor_id: UUID = WORKER_ACTOR_ID,
    roles: frozenset[str] = frozenset({"worker"}),
) -> CommandContext:
    return CommandContext(
        IdentityContext(tenant_id, actor_id, actor_id, roles, "field-service-worker"),
        run_id,
        run_id,
        f"p008:{operation}:{run_id}",
        sha256(f"p008\n{operation}\n{run_id}".encode()).hexdigest(),
    )


class FieldServicePlanner(RunPlanner):
    async def prepare(self, input: PrepareRunInput) -> PreparedRunPlan:
        task_id = uuid5(UUID(input.run_id), "field-service-create-repair-order")
        return PreparedRunPlan(
            tasks=(
                TaskDefinition(
                    "create repair order",
                    "authoritative repair order state is open",
                    risk_level=RiskLevel.L2_REVERSIBLE_WRITE,
                    evidence_requirements=("authoritative-readback",),
                    task_id=task_id,
                ),
            ),
            tool_versions=("field-service-create-repair-order@1.0.0",),
            model_route="field-service-reference@1",
            policy_version="opa-action@1",
        )


class RepairOrderAuthority:
    """Deterministic external-system simulator behind the real governed boundaries."""

    def __init__(self) -> None:
        self.orders: dict[str, dict[str, str]] = {}
        self.write_count = 0

    async def execute(self, action: Action, credential: CredentialLease) -> ToolReceipt:
        assert credential.scope == "field-service.repair-order.write"
        equipment_id = str(action.parameters.to_value()["equipment_id"])
        external_id = f"WO-{action.idempotency_key[-12:].upper()}"
        if external_id not in self.orders:
            self.write_count += 1
            self.orders[external_id] = {"equipment_id": equipment_id, "status": "open"}
        return ToolReceipt(external_id, ToolResultStatus.SUCCEEDED, (("status", "open"),))

    async def verify(self, action: Action, receipt: ToolReceipt) -> bool:
        return self.orders.get(receipt.external_id) == {
            "equipment_id": str(action.parameters.to_value()["equipment_id"]),
            "status": "open",
        }

    async def observe(
        self,
        source: str,
        tenant_id: UUID,
        subject_refs: tuple[SubjectRef, ...],
        criterion: SuccessCriterion,
    ):
        from autonoesis_application import AuthoritativeObservation

        _ = tenant_id
        assert source == "field-service-repair-orders"
        assert criterion.criterion_id == "repair-order-open"
        equipment_id = subject_refs[0].subject_id
        matches = [
            (reference, state)
            for reference, state in self.orders.items()
            if state["equipment_id"] == equipment_id
        ]
        if len(matches) != 1:
            raise LookupError("authoritative repair order is unavailable or ambiguous")
        reference, state = matches[0]
        content = (
            '{"equipment_id":"' + state["equipment_id"] + '","status":"' + state["status"] + '"}'
        ).encode()
        now = datetime.now(UTC)
        return AuthoritativeObservation(
            source,
            "field-service-repair-orders@1",
            f"repair-order://{reference}",
            content.decode(),
            content,
            state["status"] == "open",
            now,
            now + timedelta(minutes=5),
        )


class FieldServiceExecutor(RunExecutor):
    def __init__(self, approver_id: UUID) -> None:
        self.approver_id = approver_id

    async def execute(
        self,
        input: ExecuteRunInput,
        task: Task,
        application: GoalExecutionApplication,
    ) -> None:
        tenant_id, run_id = UUID(input.tenant_id), UUID(input.run_id)
        action = await application.propose_action(
            command_context(tenant_id, run_id, "propose-repair-order"),
            ProposeAction(
                task.task_id,
                "field-service-create-repair-order",
                "1.0.0",
                "create",
                "repair-orders/EQ-42",
                {"equipment_id": "EQ-42", "priority": "urgent"},
                RiskLevel.L2_REVERSIBLE_WRITE,
                "repair order is open",
                DataClassification.INTERNAL,
            ),
        )
        approval = await application.request_approval(
            command_context(tenant_id, run_id, "request-repair-order-approval"),
            RequestApproval(
                action.action_id,
                "opa-action@1",
                "create one repair order for EQ-42",
                "approver",
                datetime.now(UTC) + timedelta(minutes=5),
            ),
        )
        approval = await application.decide_approval(
            command_context(
                tenant_id,
                run_id,
                "approve-repair-order",
                actor_id=self.approver_id,
                roles=frozenset({"approver"}),
            ),
            DecideApproval(approval.approval_id, action.canonical_digest, True, "impact reviewed"),
        )
        execution = await application.execute_governed_action(
            command_context(tenant_id, run_id, "execute-repair-order"),
            ExecuteGovernedAction(
                action.action_id,
                approval.approval_id,
                "opa-action@1",
                "field-service-e2e",
                10,
            ),
        )
        assert execution.result.action.status.value == "succeeded"
        evidence = await application.capture_authoritative_evidence(
            command_context(tenant_id, run_id, "capture-repair-order"),
            CaptureAuthoritativeEvidence(
                run_id,
                action.action_id,
                "repair-order-open",
                "field-service-repair-orders",
            ),
        )
        outcome = await application.verify_outcome(
            command_context(tenant_id, run_id, "verify-repair-order"),
            VerifyOutcome(run_id, "repair-order-open", (evidence.evidence_id,)),
        )
        assert outcome.status is OutcomeStatus.VERIFIED
        await application.complete_task(
            command_context(tenant_id, run_id, "complete-repair-order-task"),
            CompleteTask(task.task_id, True, "authoritative Outcome verified"),
        )


def dependencies(input: Any) -> ActivityDependencies:
    return _dependencies[input.run_id]


@activity.defn(name="prepare_run")
async def e2e_prepare(input: PrepareRunInput) -> str:
    return await prepare_run(input, dependencies(input))


@activity.defn(name="execute_run")
async def e2e_execute(input: ExecuteRunInput) -> str:
    return await execute_run(input, dependencies(input))


@activity.defn(name="evaluate_run")
async def e2e_evaluate(input: EvaluateRunInput) -> str:
    return await evaluate_run(input, dependencies(input))


@activity.defn(name="cancel_run")
async def e2e_cancel(input: CancelRunInput) -> str:
    return await cancel_run(input, dependencies(input))


@activity.defn(name="reject_run")
async def e2e_reject(input: RejectRunInput) -> str:
    return await reject_run(input, dependencies(input))


@activity.defn(name="take_over_run")
async def e2e_takeover(input: TakeOverRunInput) -> str:
    return await take_over_run(input, dependencies(input))


async def provision_tenant(tenant_id: UUID) -> None:
    engine = create_async_engine(os.environ["AUTONOESIS_TEST_ADMIN_DATABASE_URL"])
    try:
        async with engine.begin() as connection:
            await connection.execute(
                text(
                    "INSERT INTO tenants (id, name, created_at) "
                    "VALUES (:id, :name, CURRENT_TIMESTAMP)"
                ),
                {"id": str(tenant_id), "name": f"p008-e2e-{tenant_id}"},
            )
    finally:
        await engine.dispose()


def identity_headers(tenant_id: UUID, actor_id: UUID, key: str | None = None) -> dict[str, str]:
    headers = {
        "X-Tenant-ID": str(tenant_id),
        "X-Actor-ID": str(actor_id),
        "X-Roles": "platform_admin,tenant_admin,operator,developer,auditor",
    }
    if key is not None:
        headers["Idempotency-Key"] = key
    return headers


@pytest.mark.asyncio
async def test_field_service_pack_reaches_verified_goal_through_real_components() -> None:
    tenant_id, actor_id, approver_id = uuid4(), uuid4(), uuid4()
    await provision_tenant(tenant_id)
    database_url = os.environ["AUTONOESIS_TEST_DATABASE_URL"]
    worker_url = database_url.replace("autonoesis_api:", "autonoesis_worker:")
    api_store = PostgreSQLPlatformStore.from_url(database_url)
    worker_store = PostgreSQLPlatformStore.from_url(worker_url)
    reservation_engine = create_async_engine(worker_url)
    sessions = async_sessionmaker(reservation_engine, expire_on_commit=False)
    authority = RepairOrderAuthority()
    client = boto3.client(
        "s3",
        endpoint_url=os.environ["AUTONOESIS_TEST_MINIO_URL"],
        aws_access_key_id=os.getenv("AUTONOESIS_TEST_MINIO_ACCESS_KEY", "autonoesis"),
        aws_secret_access_key=os.getenv("AUTONOESIS_TEST_MINIO_SECRET_KEY", "autonoesis-test-only"),
        region_name="us-east-1",
    )
    bucket = f"autonoesis-p008-e2e-{uuid4()}"
    client.create_bucket(Bucket=bucket, ObjectLockEnabledForBucket=True)
    artifacts = MinioEvidenceStore(Boto3ObjectStore(client), bucket)
    delegation = InMemoryDelegationStore()
    delegation.grant("field-service-e2e", "field-service-create-repair-order", "repair-orders/")
    gateway = GovernedToolGateway(
        catalog=StaticToolCatalog(
            (
                ResolvedToolVersion(
                    "field-service-create-repair-order",
                    "1.0.0",
                    "field-service-repair-orders",
                    frozenset({"create"}),
                    ("repair-orders/",),
                    {
                        "type": "object",
                        "additionalProperties": False,
                        "required": ["equipment_id", "priority"],
                        "properties": {
                            "equipment_id": {"type": "string", "minLength": 1},
                            "priority": {"enum": ["urgent", "normal"]},
                        },
                    },
                    RiskLevel.L2_REVERSIBLE_WRITE,
                    "field-service.repair-order.write",
                ),
            )
        ),
        delegation=delegation,
        schema_validator=JsonSchemaValidator(),
        policy=OPAPolicyAdapter(os.environ["AUTONOESIS_TEST_OPA_URL"], "opa-action@1"),
        kill_switch=SqlKillSwitchStore(sessions, tenant_id),
        reservations=PostgreSQLAtomicExecutionReservations(sessions),
        credentials=EphemeralCredentialBroker(),
        egress=RegistryControlledEgress(
            {
                (
                    "field-service-create-repair-order",
                    "1.0.0",
                    "field-service-repair-orders",
                ): authority
            }
        ),
        audit=InMemoryGatewayAudit(),
    )
    application = GoalExecutionApplication(
        worker_store.repository,
        worker_store,
        governed_gateway=gateway,
        evidence_artifacts=artifacts,
        authoritative_readback=authority,
    )
    temporal = await Client.connect(os.environ["AUTONOESIS_TEST_TEMPORAL_TARGET"])
    task_queue = f"p008-reference-{uuid4()}"
    app = build_app(api_store)
    transport = httpx.ASGITransport(app=app)
    try:
        async with httpx.AsyncClient(transport=transport, base_url="http://autonoesis.test") as api:
            manifest = yaml.safe_load(
                (ROOT / "examples/field-service/capability-pack.yaml").read_text(encoding="utf-8")
            )
            installed = await api.post(
                "/v1/capability-packs",
                json={"manifest": manifest},
                headers=identity_headers(tenant_id, actor_id, "p008-install-pack"),
            )
            assert installed.status_code == 201
            agent = await api.post(
                "/v1/agents",
                json={
                    "name": "field-service-diagnosis",
                    "description": "Reference field service execution agent",
                    "instruction": "Create one governed repair order and verify authority.",
                    "model_route": "field-service-reference@1",
                    "tool_ids": ["field-service-create-repair-order@1.0.0"],
                },
                headers=identity_headers(tenant_id, actor_id, "p008-create-agent"),
            )
            assert agent.status_code == 201
            goal_response = await api.post(
                "/v1/goals",
                json={
                    "goal_type": "field-service.restore-equipment",
                    "statement": "Restore equipment EQ-42",
                    "desired_outcome": "An authoritative repair order is open",
                    "subject_refs": [
                        {
                            "system": "field-service",
                            "subject_type": "equipment",
                            "subject_id": "EQ-42",
                        }
                    ],
                    "success_criteria": [
                        {
                            "criterion_id": "repair-order-open",
                            "description": "Repair order state is open",
                            "evidence_type": "authoritative-readback",
                        }
                    ],
                    "owner_id": str(actor_id),
                    "risk_tier": "medium",
                    "deadline": (datetime.now(UTC) + timedelta(minutes=10)).isoformat(),
                    "input_payload": {
                        "customer_id": "C-42",
                        "equipment_id": "EQ-42",
                        "symptom": "offline",
                    },
                },
                headers=identity_headers(tenant_id, actor_id, "p008-create-goal"),
            )
            assert goal_response.status_code == 201
            goal_id = UUID(goal_response.json()["goal_id"])
            activated = await api.post(
                f"/v1/goals/{goal_id}/activation",
                headers=identity_headers(tenant_id, actor_id, "p008-activate-goal"),
            )
            assert activated.status_code == 200
            run_response = await api.post(
                f"/v1/goals/{goal_id}/runs",
                headers=identity_headers(tenant_id, actor_id, "p008-request-run"),
            )
            assert run_response.status_code == 202
            run_id = UUID(run_response.json()["run_id"])

            _dependencies[str(run_id)] = build_activity_dependencies(
                worker_store,
                application=application,
                planner=FieldServicePlanner(),
                executor=FieldServiceExecutor(approver_id),
            )
            async with Worker(
                temporal,
                task_queue=task_queue,
                workflows=[GoalRunWorkflow],
                activities=[
                    e2e_prepare,
                    e2e_execute,
                    e2e_evaluate,
                    e2e_cancel,
                    e2e_reject,
                    e2e_takeover,
                ],
                workflow_runner=SandboxedWorkflowRunner(),
            ):
                handle = await temporal.start_workflow(
                    GoalRunWorkflow.run,
                    GoalRunInput(
                        str(tenant_id),
                        str(goal_id),
                        str(run_id),
                        (datetime.now(UTC) + timedelta(minutes=5)).timestamp(),
                    ),
                    id=f"p008-reference-{run_id}",
                    task_queue=task_queue,
                )
                assert await handle.result() == "succeeded"

            persisted_run = await worker_store.get_run(tenant_id, run_id)
            persisted_goal = await worker_store.get_goal(tenant_id, goal_id)
            tasks = await worker_store.repository.list_tasks(tenant_id, run_id)
            actions = await worker_store.repository.list_actions(tenant_id, run_id)
            evidence = tuple(
                item
                for item in await worker_store.list_evidence(tenant_id)
                if item.run_id == run_id
            )
            outcomes = await worker_store.repository.list_outcomes(tenant_id, run_id)
            audits = await worker_store.list_audit_events(tenant_id)
            assert persisted_run.status is RunStatus.SUCCEEDED
            assert persisted_goal.status is GoalStatus.SATISFIED
            assert len(tasks) == len(actions) == len(outcomes) == 1
            assert tasks[0].status.value == "succeeded"
            assert actions[0].status.value == "succeeded"
            assert outcomes[0].status is OutcomeStatus.VERIFIED
            assert any(item.integrity.value == "verified" for item in evidence)
            assert authority.write_count == 1
            assert verify_audit_chain(audits)
            approval_event = next(item for item in audits if item.event_type == "approval.approved")
            assert approval_event.actor_id == approver_id
            assert approval_event.actor_id != UUID(int=0)

            readback_run = await api.get(
                f"/v1/runs/{run_id}", headers=identity_headers(tenant_id, actor_id)
            )
            readback_goal = await api.get(
                f"/v1/goals/{goal_id}", headers=identity_headers(tenant_id, actor_id)
            )
            readback_evidence = await api.get(
                "/v1/evidence", headers=identity_headers(tenant_id, actor_id)
            )
            assert readback_run.json()["status"] == "succeeded"
            assert readback_goal.json()["status"] == "satisfied"
            assert len(readback_evidence.json()) >= 2

            history = await handle.fetch_history()
            await Replayer(workflows=[GoalRunWorkflow]).replay_workflow(history)
    finally:
        _dependencies.clear()
        await api_store.close()
        await worker_store.close()
        await reservation_engine.dispose()
