"""PostgreSQL component tests for authoritative state and tenant isolation."""

import os
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from autonoesis_adapters import PostgreSQLPlatformStore, SqlKillSwitchStore
from autonoesis_adapters.persistence_schema import audit_events, goals, outbox, releases, runs
from autonoesis_application import AuditEvent, ConcurrencyConflict, RecordNotFound
from autonoesis_capability import parse_manifest
from autonoesis_domain import (
    Action,
    ApprovalRequest,
    BudgetAmount,
    CandidateStatus,
    CandidateVersion,
    DataClassification,
    DeploymentStatus,
    Evidence,
    EvidenceCaptureMethod,
    EvidenceIntegrity,
    GoalContract,
    JsonObject,
    Outcome,
    OutcomeStatus,
    Plan,
    Release,
    RiskLevel,
    RiskTier,
    Run,
    RunExecutionSnapshot,
    RunStatus,
    SubjectRef,
    SuccessCriterion,
    Task,
)
from autonoesis_runtime import KillSwitchDimension
from sqlalchemy import func, insert, select, text
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.ext.asyncio import create_async_engine

pytestmark = pytest.mark.skipif(
    not os.getenv("AUTONOESIS_TEST_DATABASE_URL"),
    reason="requires an explicitly configured PostgreSQL component database",
)


def manifest_payload() -> dict[str, object]:
    return {
        "api_version": "autonoesis/v1alpha1",
        "pack_id": "authority-test-pack",
        "version": "1.0.0",
        "python_entry_point": "authority_test_pack.plugin:create",
        "goal_types": [
            {
                "goal_type": "authority.verify",
                "input_schema": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["request"],
                    "properties": {"request": {"type": "string"}},
                },
                "agent": "authority-agent",
                "evaluation_suite": "authority-suite",
                "default_policy": "authority-policy",
                "default_budget": 100,
            }
        ],
        "skills": [],
        "tools": ["records"],
        "policies": ["authority-policy"],
        "evaluation_suites": ["authority-suite"],
    }


async def provision_tenant(tenant_id: UUID) -> None:
    engine = create_async_engine(os.environ["AUTONOESIS_TEST_ADMIN_DATABASE_URL"])
    try:
        async with engine.begin() as connection:
            await connection.execute(
                text(
                    """INSERT INTO tenants (id, name, created_at)
                    VALUES (:tenant_id, :name, CURRENT_TIMESTAMP)
                    ON CONFLICT (id) DO NOTHING"""
                ),
                {"tenant_id": str(tenant_id), "name": f"test-{tenant_id}"},
            )
    finally:
        await engine.dispose()


def make_goal(tenant_id: UUID) -> GoalContract:
    return GoalContract(
        tenant_id=tenant_id,
        goal_type="authority.verify",
        statement="Persist authoritative state",
        desired_outcome="all facts survive process restart",
        subject_refs=(SubjectRef("records", "record", "42"),),
        success_criteria=(SuccessCriterion("persisted", "state is authoritative", "readback"),),
        constraints=("tenant isolated",),
        owner_id=uuid4(),
        risk_tier=RiskTier.MEDIUM,
        budget_limit=BudgetAmount(100),
        deadline=datetime.now(UTC) + timedelta(days=1),
        input_payload=JsonObject.from_value({"request": "persist"}),
    )


def audit_for(goal: GoalContract) -> AuditEvent:
    return AuditEvent(
        tenant_id=goal.tenant_id,
        actor_id=goal.owner_id,
        principal_id=goal.owner_id,
        event_type="goal.created",
        object_type="goal",
        object_id=str(goal.goal_id),
        correlation_id=uuid4(),
        details={"version": goal.version},
    )


@pytest.mark.asyncio
async def test_two_store_instances_share_capability_approval_and_release() -> None:
    tenant_id = uuid4()
    await provision_tenant(tenant_id)
    first = PostgreSQLPlatformStore.from_url(os.environ["AUTONOESIS_TEST_DATABASE_URL"])
    second = PostgreSQLPlatformStore.from_url(os.environ["AUTONOESIS_TEST_DATABASE_URL"])
    try:
        manifest = parse_manifest(manifest_payload())
        await first.add_capability_pack(tenant_id, manifest)
        assert (await second.get_goal_type(tenant_id, "authority.verify")).agent == (
            "authority-agent"
        )
        first_switches = SqlKillSwitchStore(first.repository.sessions).for_tenant(tenant_id)
        second_switches = SqlKillSwitchStore(second.repository.sessions).for_tenant(tenant_id)
        await first_switches.activate(
            KillSwitchDimension.TOOL, "records", "component test", str(uuid4())
        )
        assert len(await second_switches.list_active()) == 1

        goal = make_goal(tenant_id)
        await first.add_goal(goal, audit_for(goal))
        run = Run(tenant_id, goal.goal_id, uuid4())
        await first.add_run(run, audit_for(goal))
        task = Task(tenant_id, run.run_id, "read", "state returned")
        plan = Plan(tenant_id, goal.goal_id, run.run_id, (task,))
        await first.repository.add_plan(plan)
        action = Action(
            tenant_id=tenant_id,
            run_id=run.run_id,
            task_id=task.task_id,
            tool_name="records",
            tool_version="1.0.0",
            operation="read",
            resource_scope="records/42",
            parameters=JsonObject.from_value({"include": ["status"]}),
            risk_level=RiskLevel.L1_READ,
            idempotency_key=f"read-{uuid4()}",
            expected_effect="record state returned",
        )
        await first.repository.add_action(action)
        approval = ApprovalRequest(
            tenant_id=tenant_id,
            run_id=run.run_id,
            action_id=action.action_id,
            action_digest=action.canonical_digest,
            tool_version=action.tool_version,
            operation=action.operation,
            resource_scope=action.resource_scope,
            argument_digest=action.parameter_digest,
            policy_version="authority-policy@1",
            impact_summary="read authoritative state",
            required_role="approver",
            expires_at=datetime.now(UTC) + timedelta(minutes=5),
        )
        with pytest.raises(ValueError, match="authoritative persisted Action"):
            await first.repository.add_approval(replace(approval, operation="tampered"))
        await first.repository.add_approval(approval)
        assert (await second.get_approval(tenant_id, approval.approval_id)).action_digest == (
            action.canonical_digest
        )

        proposal_id = uuid4()
        from autonoesis_domain import ImprovementProposal, ImprovementTarget

        proposal = ImprovementProposal(
            tenant_id,
            ImprovementTarget.AGENT_INSTRUCTION,
            uuid4(),
            ("evidence://1",),
            "baseline gap",
            "candidate change",
            "authority-suite",
            "restore baseline",
            "independent-generator",
            proposal_id,
        )
        await first.add_proposal(proposal)
        candidate = CandidateVersion(
            tenant_id, proposal_id, uuid4(), "artifact://candidate", "independent-generator"
        )
        await first.add_candidate(candidate)
        for status in (
            CandidateStatus.EVALUATING,
            CandidateStatus.AWAITING_APPROVAL,
            CandidateStatus.APPROVED,
        ):
            candidate = candidate.transition_to(status)
            await first.save_candidate(candidate)
        deployment = candidate.begin_deployment(actor_id=uuid4(), reason="shadow approved")
        await first.add_deployment(deployment)
        deployment = deployment.transition_to(
            DeploymentStatus.CANARY, actor_id=uuid4(), reason="shadow passed"
        )
        await first.save_deployment(deployment)
        deployment = deployment.transition_to(
            DeploymentStatus.STABLE, actor_id=uuid4(), reason="canary passed"
        )
        await first.save_deployment(deployment)
        release = Release.from_stable_deployment(
            deployment,
            stable_version_id=uuid4(),
            previous_stable_version_id=candidate.baseline_version_id,
            approved_by=uuid4(),
        )
        await first.add_release(release)
        assert {item.release_id for item in await second.list_releases(tenant_id)} == {
            release.release_id
        }
        admin = create_async_engine(os.environ["AUTONOESIS_TEST_ADMIN_DATABASE_URL"])
        try:
            with pytest.raises(IntegrityError):
                async with admin.begin() as connection:
                    await connection.execute(
                        insert(releases).values(
                            id=str(uuid4()),
                            tenant_id=str(tenant_id),
                            candidate_id=str(release.candidate_id),
                            deployment_id=str(release.deployment_id),
                            stable_slot=str(candidate.baseline_version_id),
                            stable_version_id=str(uuid4()),
                            previous_stable_version_id=str(release.stable_version_id),
                            approved_by=str(uuid4()),
                            active=True,
                            definition={},
                            optimistic_version=1,
                            created_at=datetime.now(UTC),
                        )
                    )
        finally:
            await admin.dispose()
    finally:
        await first.close()
        await second.close()


@pytest.mark.asyncio
async def test_optimistic_update_has_one_winner_and_cross_tenant_fk_is_rejected() -> None:
    tenant_id, other_tenant = uuid4(), uuid4()
    await provision_tenant(tenant_id)
    await provision_tenant(other_tenant)
    first = PostgreSQLPlatformStore.from_url(os.environ["AUTONOESIS_TEST_DATABASE_URL"])
    second = PostgreSQLPlatformStore.from_url(os.environ["AUTONOESIS_TEST_DATABASE_URL"])
    try:
        goal = make_goal(tenant_id)
        await first.add_goal(goal, audit_for(goal))
        other_goal = make_goal(other_tenant)
        await second.add_goal(other_goal, audit_for(other_goal))
        run = Run(tenant_id, goal.goal_id, uuid4())
        await first.add_run(run, audit_for(goal))
        left = await first.get_run(tenant_id, run.run_id)
        right = await second.get_run(tenant_id, run.run_id)
        snapshot = RunExecutionSnapshot(
            uuid4(), uuid4(), run.agent_version_id, (), (), "route@1", "policy@1"
        )
        left = left.bind_execution(snapshot).transition_to(RunStatus.RUNNING)
        right = right.bind_execution(snapshot).transition_to(RunStatus.RUNNING)
        await first.save_run(left, run.optimistic_version)
        with pytest.raises(ConcurrencyConflict):
            await second.save_run(right, run.optimistic_version)

        admin = create_async_engine(os.environ["AUTONOESIS_TEST_ADMIN_DATABASE_URL"])
        try:
            with pytest.raises(IntegrityError):
                async with admin.begin() as connection:
                    await connection.execute(
                        insert(runs).values(
                            id=str(uuid4()),
                            tenant_id=str(other_tenant),
                            goal_id=str(goal.goal_id),
                            agent_version_id=str(uuid4()),
                            status="pending",
                            temporal_workflow_id=f"cross-{uuid4()}",
                            definition={},
                            optimistic_version=1,
                            created_at=datetime.now(UTC),
                        )
                    )
        finally:
            await admin.dispose()

        app_engine = create_async_engine(os.environ["AUTONOESIS_TEST_DATABASE_URL"])
        try:
            async with app_engine.begin() as connection:
                await connection.execute(
                    select(func.set_config("app.tenant_id", str(tenant_id), True))
                )
                assert (
                    await connection.scalar(
                        select(goals.c.id).where(goals.c.id == str(other_goal.goal_id))
                    )
                ) is None
            with pytest.raises(DBAPIError):
                async with app_engine.begin() as connection:
                    await connection.execute(
                        text(
                            "INSERT INTO tenants (id, name, created_at) "
                            "VALUES (:id, 'forbidden', CURRENT_TIMESTAMP)"
                        ),
                        {"id": str(uuid4())},
                    )
        finally:
            await app_engine.dispose()
    finally:
        await first.close()
        await second.close()


@pytest.mark.asyncio
async def test_verified_outcome_requires_persisted_evidence() -> None:
    tenant_id = uuid4()
    await provision_tenant(tenant_id)
    store = PostgreSQLPlatformStore.from_url(os.environ["AUTONOESIS_TEST_DATABASE_URL"])
    try:
        goal = make_goal(tenant_id)
        await store.add_goal(goal, audit_for(goal))
        run = Run(tenant_id, goal.goal_id, uuid4())
        await store.add_run(run, audit_for(goal))
        task = Task(tenant_id, run.run_id, "verify", "readback complete")
        await store.repository.add_plan(Plan(tenant_id, goal.goal_id, run.run_id, (task,)))
        action = Action(
            tenant_id,
            run.run_id,
            task.task_id,
            "records",
            "1.0.0",
            "read",
            "records/42",
            JsonObject.from_value({"verify": True}),
            RiskLevel.L1_READ,
            f"verify-{uuid4()}",
            "state read back",
        )
        await store.repository.add_action(action)
        now = datetime.now(UTC)
        item = Evidence(
            tenant_id,
            run.run_id,
            action.action_id,
            "records",
            "records-readback@1",
            EvidenceCaptureMethod.AUTHORITATIVE_READBACK,
            "records://42",
            "exists",
            "a" * 64,
            DataClassification.INTERNAL,
            now - timedelta(seconds=1),
            now + timedelta(minutes=5),
            EvidenceIntegrity.VERIFIED,
            captured_at=now,
        )
        outcome = Outcome(
            tenant_id,
            goal.goal_id,
            run.run_id,
            "persisted",
            "readback@1",
            OutcomeStatus.VERIFIED,
            (item,),
            verified_at=now,
        )
        with pytest.raises(ValueError, match="persisted"):
            await store.repository.add_outcome(outcome)
        await store.repository.add_evidence(item)
        with pytest.raises(ValueError, match="exactly match"):
            await store.repository.add_outcome(
                replace(outcome, evidence=(replace(item, observed_state="tampered"),))
            )
        await store.repository.add_outcome(outcome)
        assert (await store.repository.get_outcome(tenant_id, outcome.outcome_id)).evidence_ids == (
            item.evidence_id,
        )
    finally:
        await store.close()


@pytest.mark.asyncio
async def test_business_audit_and_outbox_roll_back_together() -> None:
    tenant_id = uuid4()
    await provision_tenant(tenant_id)
    admin_url = os.environ["AUTONOESIS_TEST_ADMIN_DATABASE_URL"]
    admin = create_async_engine(admin_url)
    store = PostgreSQLPlatformStore.from_url(os.environ["AUTONOESIS_TEST_DATABASE_URL"])
    goal = make_goal(tenant_id)
    try:
        async with admin.begin() as connection:
            await connection.execute(
                text(
                    """CREATE OR REPLACE FUNCTION reject_test_outbox() RETURNS trigger AS $$
                    BEGIN RAISE EXCEPTION 'forced outbox failure'; END; $$ LANGUAGE plpgsql"""
                )
            )
            await connection.execute(
                text(
                    "CREATE TRIGGER reject_test_outbox BEFORE INSERT ON outbox "
                    "FOR EACH ROW EXECUTE FUNCTION reject_test_outbox()"
                )
            )
        with pytest.raises(Exception, match="forced outbox failure"):
            await store.add_goal(goal, audit_for(goal))
        with pytest.raises(RecordNotFound):
            await store.get_goal(tenant_id, goal.goal_id)
        async with admin.connect() as connection:
            assert (
                await connection.scalar(
                    select(audit_events.c.id).where(audit_events.c.object_id == str(goal.goal_id))
                )
            ) is None
            assert (
                await connection.scalar(
                    select(outbox.c.id).where(
                        outbox.c.payload["object_id"].as_string() == str(goal.goal_id)
                    )
                )
            ) is None
    finally:
        async with admin.begin() as connection:
            await connection.execute(text("DROP TRIGGER IF EXISTS reject_test_outbox ON outbox"))
            await connection.execute(text("DROP FUNCTION IF EXISTS reject_test_outbox()"))
        await store.close()
        await admin.dispose()
