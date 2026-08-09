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
    AssetStage,
    LoopPolicy,
    RunStatus,
    SubjectRef,
    SuccessCriterion,
)
from autonoesis_worker.activities import (
    CancelRunInput,
    EvaluateRunInput,
    ExecuteRunInput,
    PrepareRunInput,
    RejectRunInput,
    cancel_run,
    evaluate_run,
    execute_run,
    prepare_run,
    reject_run,
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
            risk_tier="low",
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
            PrepareRunInput(tenant_id=tenant_id, goal_id=goal_id, run_id=run_id), store
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
            PrepareRunInput(tenant_id=tenant_id, goal_id=goal_id, run_id=run_id), store
        )
        result = await prepare_run(
            PrepareRunInput(tenant_id=tenant_id, goal_id=goal_id, run_id=run_id), store
        )
        assert result == "planned"


class TestCancelRun:
    @pytest.mark.asyncio
    async def test_transitions_run_to_cancelled(self) -> None:
        store, identity, tenant_id = _setup_store()
        goal_id = await _make_goal(store, identity)
        run_id = await _start_run(store, identity, goal_id)
        await prepare_run(
            PrepareRunInput(tenant_id=tenant_id, goal_id=goal_id, run_id=run_id), store
        )

        result = await cancel_run(
            CancelRunInput(tenant_id=tenant_id, goal_id=goal_id, run_id=run_id, reason="test"),
            store,
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
            PrepareRunInput(tenant_id=tenant_id, goal_id=goal_id, run_id=run_id), store
        )

        result = await reject_run(
            RejectRunInput(tenant_id=tenant_id, goal_id=goal_id, run_id=run_id, reason="test"),
            store,
        )
        assert result == "rejected"

        updated = await store.get_run(identity.tenant_id, UUID(run_id))
        assert updated.status is RunStatus.FAILED


class TestExecuteRun:
    @pytest.mark.asyncio
    async def test_transitions_run_to_succeeded(self) -> None:
        store, identity, tenant_id = _setup_store()
        goal_id = await _make_goal(store, identity)
        run_id = await _start_run(store, identity, goal_id)
        await prepare_run(
            PrepareRunInput(tenant_id=tenant_id, goal_id=goal_id, run_id=run_id), store
        )

        result = await execute_run(
            ExecuteRunInput(tenant_id=tenant_id, goal_id=goal_id, run_id=run_id), store
        )
        assert result == "succeeded"

        updated = await store.get_run(identity.tenant_id, UUID(run_id))
        assert updated.status is RunStatus.SUCCEEDED

    @pytest.mark.asyncio
    async def test_idempotent_when_already_succeeded(self) -> None:
        store, identity, tenant_id = _setup_store()
        goal_id = await _make_goal(store, identity)
        run_id = await _start_run(store, identity, goal_id)
        await prepare_run(
            PrepareRunInput(tenant_id=tenant_id, goal_id=goal_id, run_id=run_id), store
        )
        await execute_run(
            ExecuteRunInput(tenant_id=tenant_id, goal_id=goal_id, run_id=run_id), store
        )

        result = await execute_run(
            ExecuteRunInput(tenant_id=tenant_id, goal_id=goal_id, run_id=run_id), store
        )
        assert result == "succeeded"


class TestEvaluateRun:
    @pytest.mark.asyncio
    async def test_returns_run_status(self) -> None:
        store, identity, tenant_id = _setup_store()
        goal_id = await _make_goal(store, identity)
        run_id = await _start_run(store, identity, goal_id)
        await prepare_run(
            PrepareRunInput(tenant_id=tenant_id, goal_id=goal_id, run_id=run_id), store
        )
        await execute_run(
            ExecuteRunInput(tenant_id=tenant_id, goal_id=goal_id, run_id=run_id), store
        )

        result = await evaluate_run(
            EvaluateRunInput(tenant_id=tenant_id, goal_id=goal_id, run_id=run_id), store
        )
        assert result == "succeeded"
