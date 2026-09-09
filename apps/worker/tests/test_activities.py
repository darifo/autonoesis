"""Tests for Temporal Activity implementations."""

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import pytest
from autonoesis_adapters import InMemoryPlatformStore
from autonoesis_application import (
    CreateGoal,
    CreateGoalHandler,
    IdentityContext,
    PromotionPolicy,
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
    ShadowMeasurements,
    SubjectRef,
    SuccessCriterion,
    TrafficAllocation,
)
from autonoesis_worker.activities import (
    build_activity_dependencies,
    cancel_run,
    evaluate_candidate,
    evaluate_run,
    execute_release_command,
    execute_run,
    execute_shadow_pair,
    load_approval,
    prepare_run,
    promote_candidate,
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
    PromoteCandidateInput,
    RejectRunInput,
    ReleaseCommandInput,
    ShadowPairInput,
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


@pytest.mark.asyncio
async def test_shadow_activity_fails_closed_without_runtime() -> None:
    store, _, tenant_id = _setup_store()
    with pytest.raises(ApplicationError, match="refusing synthetic comparison"):
        await execute_shadow_pair(
            ShadowPairInput(tenant_id, str(uuid4()), "request://shadow/1", {}),
            build_activity_dependencies(store),
        )


@pytest.mark.asyncio
async def test_candidate_promotion_fails_closed_without_release_service() -> None:
    store, _, tenant_id = _setup_store()
    candidate_id = str(uuid4())
    with pytest.raises(ApplicationError, match="refusing synthetic promotion"):
        await promote_candidate(
            PromoteCandidateInput(tenant_id, candidate_id, candidate_id),
            build_activity_dependencies(store),
        )


@pytest.mark.asyncio
async def test_release_command_fails_closed_without_release_service() -> None:
    store, _, tenant_id = _setup_store()
    with pytest.raises(ApplicationError, match="refusing synthetic release"):
        await execute_release_command(
            ReleaseCommandInput(tenant_id, "enter_canary", deployment_id=str(uuid4())),
            build_activity_dependencies(store),
        )


@pytest.mark.asyncio
async def test_release_command_rejects_unknown_actions() -> None:
    store, _, tenant_id = _setup_store()
    evolution = AsyncMock()
    with pytest.raises(ApplicationError, match="unknown release command action"):
        await execute_release_command(
            ReleaseCommandInput(tenant_id, "declare_stable_directly"),
            build_activity_dependencies(store, evolution=evolution),
        )
    evolution.assert_not_called()


@pytest.mark.asyncio
async def test_release_command_enters_canary_with_rule_and_executor_identity() -> None:
    store, _, tenant_id = _setup_store()
    evolution = AsyncMock()
    deployment_id = uuid4()
    evolution.promote_to_canary.return_value = SimpleNamespace(deployment_id=deployment_id)
    dependencies = build_activity_dependencies(store, evolution=evolution)

    result = await execute_release_command(
        ReleaseCommandInput(
            tenant_id,
            "enter_canary",
            deployment_id=str(deployment_id),
            candidate_percent=15,
            salt="audit-salt",
        ),
        dependencies,
    )

    assert result == f"canary:{deployment_id}"
    identity, commanded_id, allocation = evolution.promote_to_canary.await_args.args
    assert commanded_id == deployment_id
    assert allocation == TrafficAllocation("audit-salt", 15)
    assert identity.tenant_id == UUID(tenant_id)
    assert "release_executor" in identity.roles
    assert identity.agent_id == "temporal-release-executor"


@pytest.mark.asyncio
async def test_release_command_releases_stable_with_the_requested_gate() -> None:
    store, _, tenant_id = _setup_store()
    evolution = AsyncMock()
    deployment_id, stable_version_id, release_id = uuid4(), uuid4(), uuid4()
    evolution.release_stable.return_value = SimpleNamespace(release_id=release_id)
    dependencies = build_activity_dependencies(store, evolution=evolution)

    result = await execute_release_command(
        ReleaseCommandInput(
            tenant_id,
            "release_stable",
            deployment_id=str(deployment_id),
            stable_version_id=str(stable_version_id),
            min_samples=3,
            observation_seconds=120,
            required_metrics=("outcome_rate",),
        ),
        dependencies,
    )

    assert result == f"stable:{release_id}"
    identity, commanded_id, commanded_version, policy = evolution.release_stable.await_args.args
    assert commanded_id == deployment_id
    assert commanded_version == stable_version_id
    assert policy == PromotionPolicy(3, 120, ("outcome_rate",))
    assert "release_executor" in identity.roles


@pytest.mark.asyncio
async def test_release_command_rolls_back_through_the_executor() -> None:
    store, _, tenant_id = _setup_store()
    evolution = AsyncMock()
    release_id, rollback_id = uuid4(), uuid4()
    evolution.rollback.return_value = SimpleNamespace(release_id=rollback_id)
    dependencies = build_activity_dependencies(store, evolution=evolution)

    result = await execute_release_command(
        ReleaseCommandInput(tenant_id, "rollback_release", release_id=str(release_id)),
        dependencies,
    )

    assert result == f"rolled_back:{rollback_id}"
    identity, commanded_release = evolution.rollback.await_args.args
    assert commanded_release == release_id
    assert "release_executor" in identity.roles


@pytest.mark.asyncio
async def test_release_command_persists_canary_rule_through_real_service() -> None:
    from autonoesis_application import (
        CandidateLifecycleService,
        ProposeImprovement,
        RegisterCandidate,
    )
    from autonoesis_domain import DeploymentStatus, Trial, TrialCaseResult, TrialStatus

    store, identity, tenant_id = _setup_store()
    evolution = CandidateLifecycleService(store)
    dependencies = build_activity_dependencies(store, evolution=evolution)
    generator = IdentityContext(identity.tenant_id, uuid4(), uuid4(), frozenset({"generator"}))
    proposal = await evolution.propose_improvement(
        generator,
        ProposeImprovement(
            target="agent_instruction",
            target_version_id=uuid4(),
            evidence_refs=("evidence://run/1",),
            diagnosis="misses recovery",
            proposed_change="add recovery",
            validation_suite_id="test-suite",
            rollback_plan="restore",
        ),
    )
    candidate = await evolution.register_candidate(
        generator,
        RegisterCandidate(
            proposal_id=proposal.proposal_id,
            baseline_version_id=uuid4(),
            artifact_ref="artifact://agent/v2",
            artifact_digest="d" * 64,
            suite_id="test-suite",
            suite_version="1",
        ),
    )
    await evolution.submit_for_evaluation(identity.tenant_id, candidate.candidate_id)
    executed = TrialCaseResult(
        case_id="c1",
        input_payload={},
        output_payload={"answer": 1},
        subject_executed=True,
        executor_id="subject-runtime",
        evidence_refs=("evidence://execution/1",),
        environment_ref="environment://fixture/1",
    )
    from autonoesis_evaluation import RepeatedTrialPolicy

    for _ in range(16):
        await store.add_trial(
            Trial(
                tenant_id=identity.tenant_id,
                suite_id="test-suite",
                suite_version="1",
                subject_version_id=candidate.candidate_id,
                harness_version="2",
                status=TrialStatus.PASSED,
                case_results=(executed,),
                candidate_id=candidate.candidate_id,
            )
        )
    grader = IdentityContext(identity.tenant_id, uuid4(), uuid4(), frozenset({"grader"}))
    await evolution.complete_evaluation(
        grader, candidate.candidate_id, RepeatedTrialPolicy(pass_threshold=0.8)
    )
    await evolution.decide(
        IdentityContext(identity.tenant_id, uuid4(), uuid4(), frozenset({"approver"})),
        candidate.candidate_id,
        True,
        "independent approval",
    )
    await evolution.begin_shadow(
        IdentityContext(identity.tenant_id, uuid4(), uuid4(), frozenset({"release_executor"})),
        candidate.candidate_id,
    )
    deployment = next(iter(store.deployments.values()))

    result = await execute_release_command(
        ReleaseCommandInput(
            tenant_id,
            "enter_canary",
            deployment_id=str(deployment.deployment_id),
            candidate_percent=25,
            salt="executor-salt",
        ),
        dependencies,
    )

    assert result == f"canary:{deployment.deployment_id}"
    persisted = await store.get_deployment(identity.tenant_id, deployment.deployment_id)
    assert persisted.status is DeploymentStatus.CANARY
    assert persisted.traffic_allocation == TrafficAllocation("executor-salt", 25)


@pytest.mark.asyncio
async def test_shadow_activity_delegates_to_governed_application_use_case() -> None:
    store, _, tenant_id = _setup_store()
    comparison_id = uuid4()
    evolution = AsyncMock()
    evolution.execute_shadow_pair.return_value = SimpleNamespace(comparison_id=comparison_id)

    class Runtime:
        async def execute_shadow_subject(self, **command: object) -> ShadowMeasurements:
            raise AssertionError("application service owns runtime invocation")

    runtime = Runtime()
    dependencies = build_activity_dependencies(
        store,
        evolution=evolution,
        shadow_runtime=runtime,
    )
    deployment_id = uuid4()
    result = await execute_shadow_pair(
        ShadowPairInput(
            tenant_id,
            str(deployment_id),
            "request://shadow/2",
            {"prompt": "mirror"},
        ),
        dependencies,
    )

    assert result == str(comparison_id)
    command = evolution.execute_shadow_pair.await_args.args[1]
    assert command.deployment_id == deployment_id
    assert command.request_ref == "request://shadow/2"
    assert evolution.execute_shadow_pair.await_args.args[2] is runtime


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
