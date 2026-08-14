"""Tests for Temporal Activity implementations."""

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from autonoesis_adapters import InMemoryPlatformStore
from autonoesis_application import (
    CreateGoal,
    CreateGoalHandler,
    IdentityContext,
    StartGoalRun,
    StartGoalRunHandler,
)
from autonoesis_capability import parse_manifest
from autonoesis_domain import (
    AgentVersion,
    ApprovalRequest,
    AssetStage,
    LoopPolicy,
    RiskTier,
    RunStatus,
    SubjectRef,
    SuccessCriterion,
)
from autonoesis_worker.activities import (
    build_activity_dependencies,
    cancel_run,
    evaluate_candidate,
    evaluate_run,
    execute_run,
    load_approval,
    prepare_run,
    reject_run,
    take_over_run,
)
from autonoesis_worker.contracts import (
    ApprovalLookupInput,
    CancelRunInput,
    EvaluateCandidateInput,
    EvaluateRunInput,
    ExecuteRunInput,
    PrepareRunInput,
    RejectRunInput,
    TakeOverRunInput,
)
from temporalio.exceptions import ApplicationError


@pytest.mark.asyncio
async def test_candidate_evaluation_fails_closed_without_real_harness() -> None:
    store, _, tenant_id = _setup_store()
    with pytest.raises(ApplicationError, match="refusing synthetic pass"):
        await evaluate_candidate(
            EvaluateCandidateInput(tenant_id, str(uuid4())),
            build_activity_dependencies(store),
        )


def _test_manifest() -> dict[str, object]:
    return {
        "api_version": "autonoesis/v1alpha1",
        "pack_id": "test-pack",
        "version": "1.0.0",
        "python_entry_point": "test_pack.plugin:create",
        "goal_types": [
            {
                "goal_type": "generic.test",
                "input_schema": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {},
                },
                "agent": "test-agent",
                "evaluation_suite": "test-suite",
                "default_policy": "test-policy",
                "default_budget": 100,
            }
        ],
        "skills": [],
        "tools": [],
        "policies": ["test-policy"],
        "evaluation_suites": ["test-suite"],
    }


def _setup_store() -> tuple[InMemoryPlatformStore, IdentityContext, str]:
    store = InMemoryPlatformStore()
    store.register_pack(parse_manifest(_test_manifest()))
    tenant_id = uuid4()
    agent = AgentVersion(
        tenant_id,
        uuid4(),
        1,
        "test agent",
        "balanced",
        (),
        (),
        LoopPolicy(5, 1000, 100, 60),
        AssetStage.STABLE,
    )
    store.register_agent("test-agent", agent)
    identity = IdentityContext(tenant_id, tenant_id, tenant_id, frozenset({"operator"}))
    return store, identity, str(tenant_id)


async def _make_goal(store: InMemoryPlatformStore, identity: IdentityContext) -> str:
    handler = CreateGoalHandler(store, store)
    goal = await handler(
        identity,
        CreateGoal(
            goal_type="generic.test",
            statement="test goal",
            desired_outcome="test passes",
            subject_refs=(SubjectRef(system="test", subject_type="test", subject_id="1"),),
            success_criteria=(
                SuccessCriterion(criterion_id="c1", description="pass", evidence_type="test"),
            ),
            constraints=(),
            owner_id=identity.actor_id,
            risk_tier=RiskTier.LOW,
            budget_limit=1000,
            deadline=datetime.now(UTC) + timedelta(days=1),
            input_payload={},
            correlation_id=uuid4(),
        ),
    )
    return str(goal.goal_id)


async def _start_run(store: InMemoryPlatformStore, identity: IdentityContext, goal_id: str) -> str:
    handler = StartGoalRunHandler(store, store)
    run = await handler(identity, StartGoalRun(goal_id=UUID(goal_id), correlation_id=uuid4()))
    return str(run.run_id)


class TestPrepareRun:
    @pytest.mark.asyncio
    async def test_transitions_run_to_running(self) -> None:
        store, identity, tenant_id = _setup_store()
        goal_id = await _make_goal(store, identity)
        run_id = await _start_run(store, identity, goal_id)

        result = await prepare_run(
            PrepareRunInput(tenant_id=tenant_id, goal_id=goal_id, run_id=run_id),
            build_activity_dependencies(store),
        )
        assert result == "planned"

        updated = await store.get_run(identity.tenant_id, UUID(run_id))
        assert updated.status is RunStatus.RUNNING

    @pytest.mark.asyncio
    async def test_idempotent_when_already_running(self) -> None:
        store, identity, tenant_id = _setup_store()
        goal_id = await _make_goal(store, identity)
        run_id = await _start_run(store, identity, goal_id)

        await prepare_run(
            PrepareRunInput(tenant_id=tenant_id, goal_id=goal_id, run_id=run_id),
            build_activity_dependencies(store),
        )
        result = await prepare_run(
            PrepareRunInput(tenant_id=tenant_id, goal_id=goal_id, run_id=run_id),
            build_activity_dependencies(store),
        )
        assert result == "planned"


class TestCancelRun:
    @pytest.mark.asyncio
    async def test_transitions_run_to_cancelled(self) -> None:
        store, identity, tenant_id = _setup_store()
        goal_id = await _make_goal(store, identity)
        run_id = await _start_run(store, identity, goal_id)
        await prepare_run(
            PrepareRunInput(tenant_id=tenant_id, goal_id=goal_id, run_id=run_id),
            build_activity_dependencies(store),
        )

        result = await cancel_run(
            CancelRunInput(tenant_id=tenant_id, goal_id=goal_id, run_id=run_id, reason="test"),
            build_activity_dependencies(store),
        )
        assert result == "cancelled"

        updated = await store.get_run(identity.tenant_id, UUID(run_id))
        assert updated.status is RunStatus.CANCELLED


class TestRejectRun:
    @pytest.mark.asyncio
    async def test_transitions_run_to_failed(self) -> None:
        store, identity, tenant_id = _setup_store()
        goal_id = await _make_goal(store, identity)
        run_id = await _start_run(store, identity, goal_id)
        await prepare_run(
            PrepareRunInput(tenant_id=tenant_id, goal_id=goal_id, run_id=run_id),
            build_activity_dependencies(store),
        )

        result = await reject_run(
            RejectRunInput(tenant_id=tenant_id, goal_id=goal_id, run_id=run_id, reason="test"),
            build_activity_dependencies(store),
        )
        assert result == "rejected"

        updated = await store.get_run(identity.tenant_id, UUID(run_id))
        assert updated.status is RunStatus.FAILED


class TestExecuteRun:
    @pytest.mark.asyncio
    async def test_dispatches_task_without_declaring_business_success(self) -> None:
        store, identity, tenant_id = _setup_store()
        goal_id = await _make_goal(store, identity)
        run_id = await _start_run(store, identity, goal_id)
        await prepare_run(
            PrepareRunInput(tenant_id=tenant_id, goal_id=goal_id, run_id=run_id),
            build_activity_dependencies(store),
        )

        result = await execute_run(
            ExecuteRunInput(tenant_id=tenant_id, goal_id=goal_id, run_id=run_id),
            build_activity_dependencies(store),
        )
        assert result == "dispatched"

        updated = await store.get_run(identity.tenant_id, UUID(run_id))
        assert updated.status is RunStatus.RUNNING

    @pytest.mark.asyncio
    async def test_dispatch_is_idempotent(self) -> None:
        store, identity, tenant_id = _setup_store()
        goal_id = await _make_goal(store, identity)
        run_id = await _start_run(store, identity, goal_id)
        await prepare_run(
            PrepareRunInput(tenant_id=tenant_id, goal_id=goal_id, run_id=run_id),
            build_activity_dependencies(store),
        )
        await execute_run(
            ExecuteRunInput(tenant_id=tenant_id, goal_id=goal_id, run_id=run_id),
            build_activity_dependencies(store),
        )

        result = await execute_run(
            ExecuteRunInput(tenant_id=tenant_id, goal_id=goal_id, run_id=run_id),
            build_activity_dependencies(store),
        )
        assert result == "dispatched"


class TestEvaluateRun:
    @pytest.mark.asyncio
    async def test_returns_run_status(self) -> None:
        store, identity, tenant_id = _setup_store()
        goal_id = await _make_goal(store, identity)
        run_id = await _start_run(store, identity, goal_id)
        await prepare_run(
            PrepareRunInput(tenant_id=tenant_id, goal_id=goal_id, run_id=run_id),
            build_activity_dependencies(store),
        )
        await execute_run(
            ExecuteRunInput(tenant_id=tenant_id, goal_id=goal_id, run_id=run_id),
            build_activity_dependencies(store),
        )

        result = await evaluate_run(
            EvaluateRunInput(tenant_id=tenant_id, goal_id=goal_id, run_id=run_id),
            build_activity_dependencies(store),
        )
        assert result == "running"


@pytest.mark.asyncio
async def test_approval_signal_reference_is_reloaded_and_run_bound() -> None:
    store, identity, tenant_id = _setup_store()
    goal_id = await _make_goal(store, identity)
    run_id = await _start_run(store, identity, goal_id)
    now = datetime.now(UTC)
    approval = ApprovalRequest(
        tenant_id=identity.tenant_id,
        run_id=UUID(run_id),
        action_id=uuid4(),
        action_digest="a" * 64,
        tool_version="1.0.0",
        operation="write",
        resource_scope="records/1",
        argument_digest="b" * 64,
        policy_version="policy@1",
        impact_summary="one write",
        required_role="approver",
        expires_at=now + timedelta(minutes=5),
        created_at=now,
    ).decide(uuid4(), True, "approved")
    await store.add_approval(approval)
    dependencies = build_activity_dependencies(store)

    state = await load_approval(
        ApprovalLookupInput(tenant_id, run_id, str(approval.approval_id)), dependencies
    )
    assert state.status == "approved"
    with pytest.raises(PermissionError, match="does not belong"):
        await load_approval(
            ApprovalLookupInput(tenant_id, str(uuid4()), str(approval.approval_id)),
            dependencies,
        )


@pytest.mark.asyncio
async def test_takeover_signal_only_confirms_persisted_application_state() -> None:
    store, identity, tenant_id = _setup_store()
    goal_id = await _make_goal(store, identity)
    run_id = await _start_run(store, identity, goal_id)
    dependencies = build_activity_dependencies(store)
    with pytest.raises(PermissionError, match="must be authorized"):
        await take_over_run(TakeOverRunInput(tenant_id, goal_id, run_id, "manual"), dependencies)
    await prepare_run(PrepareRunInput(tenant_id, goal_id, run_id), dependencies)
    running = await store.get_run(identity.tenant_id, UUID(run_id))
    await store.save_run(
        running.transition_to(RunStatus.BLOCKED, reason="authorized manual takeover"),
        running.optimistic_version,
    )
    assert (
        await take_over_run(TakeOverRunInput(tenant_id, goal_id, run_id, "manual"), dependencies)
        == "taken_over"
    )
