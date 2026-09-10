"""Real Temporal Activity implementations for Goal and Candidate lifecycles.

These replace the placeholder stubs from Phase 1. Every activity:
- Accepts a strongly-typed input dataclass.
- Is idempotent (safe to retry).
- Reports outcomes via the platform store.
"""

from __future__ import annotations

from contextlib import suppress
from dataclasses import dataclass, replace
from hashlib import sha256
from typing import Protocol
from uuid import UUID

from autonoesis_adapters import (
    CanaryRunRouter,
    InMemoryPlatformStore,
    PostgreSQLPlatformStore,
    SqlShadowWriteGuard,
)
from autonoesis_application import (
    CancelRun,
    CandidateLifecycleService,
    CommandContext,
    CompleteRun,
    CreateValidatedPlan,
    ExecuteShadowPair,
    FailRun,
    GoalExecutionApplication,
    IdentityContext,
    PrepareRunContext,
    PromotionPolicy,
    SatisfyOrFailGoal,
    ShadowSubjectRuntime,
    StartTask,
    TaskDefinition,
)
from autonoesis_domain import Task, TrafficAllocation, Trial
from autonoesis_evaluation import RepeatedTrialPolicy
from temporalio import activity
from temporalio.exceptions import ApplicationError

from autonoesis_worker.contracts import (
    ApprovalLookupInput,
    ApprovalState,
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

# ── Activity implementations ─────────────────────────────────────────────────

PlatformStore = InMemoryPlatformStore | PostgreSQLPlatformStore


@dataclass(frozen=True, slots=True)
class PreparedRunPlan:
    """Capability-owned immutable inputs for the generic planning Activity."""

    tasks: tuple[TaskDefinition, ...]
    skill_versions: tuple[str, ...] = ()
    tool_versions: tuple[str, ...] = ()
    model_route: str = "configured-by-capability-pack"
    policy_version: str = "development-policy@1"


class RunPlanner(Protocol):
    async def prepare(self, input: PrepareRunInput) -> PreparedRunPlan: ...


class RunExecutor(Protocol):
    async def execute(
        self,
        input: ExecuteRunInput,
        task: Task,
        application: GoalExecutionApplication,
    ) -> None: ...


class CandidateEvaluator(Protocol):
    async def evaluate(self, tenant_id: UUID, candidate_id: UUID) -> Trial: ...


@dataclass(frozen=True, slots=True)
class ActivityDependencies:
    """Process-level dependencies injected into every Activity invocation."""

    store: PlatformStore
    application: GoalExecutionApplication
    evolution: CandidateLifecycleService | None = None
    planner: RunPlanner | None = None
    executor: RunExecutor | None = None
    candidate_evaluator: CandidateEvaluator | None = None
    evaluation_policy: RepeatedTrialPolicy | None = None
    shadow_runtime: ShadowSubjectRuntime | None = None


def build_activity_dependencies(
    store: PlatformStore,
    evolution: CandidateLifecycleService | None = None,
    *,
    application: GoalExecutionApplication | None = None,
    planner: RunPlanner | None = None,
    executor: RunExecutor | None = None,
    candidate_evaluator: CandidateEvaluator | None = None,
    evaluation_policy: RepeatedTrialPolicy | None = None,
    shadow_runtime: ShadowSubjectRuntime | None = None,
) -> ActivityDependencies:
    return ActivityDependencies(
        store=store,
        application=application
        or GoalExecutionApplication(
            store.repository,
            store,
            shadow_write_guard=SqlShadowWriteGuard(store),
            run_deployment_router=CanaryRunRouter(store),
        ),
        evolution=evolution,
        planner=planner,
        executor=executor,
        candidate_evaluator=candidate_evaluator,
        evaluation_policy=evaluation_policy,
        shadow_runtime=shadow_runtime,
    )


def _heartbeat(stage: str) -> None:
    # Direct unit tests do not run inside a Temporal Activity context.
    with suppress(RuntimeError):
        activity.heartbeat(stage)


def _context(tenant_id: str, run_id: str, operation: str) -> CommandContext:
    actor = UUID(int=0)
    correlation = UUID(run_id)
    return CommandContext(
        IdentityContext(
            tenant_id=UUID(tenant_id),
            actor_id=actor,
            principal_id=actor,
            roles=frozenset({"worker"}),
            agent_id="temporal-worker",
        ),
        correlation,
        correlation,
        f"temporal:{operation}:{run_id}",
        sha256(f"{operation}\n{run_id}".encode()).hexdigest(),
    )


def _worker_principal(duty: str, tenant_id: str) -> UUID:
    """Deterministic per-duty principal so separated duties never share identity."""
    from uuid import uuid5

    return uuid5(UUID(int=0), f"{duty}:{tenant_id}")


@activity.defn
async def prepare_run(
    input: PrepareRunInput,
    dependencies: ActivityDependencies,
) -> str:
    """Prepare immutable Context and a validated Plan through Application use cases."""
    _heartbeat("prepare_context")
    application = dependencies.application
    prepared = (
        await dependencies.planner.prepare(input)
        if dependencies.planner is not None
        else PreparedRunPlan(tasks=(TaskDefinition("execute goal", "required Outcomes verified"),))
    )
    await application.prepare_run_context(
        _context(input.tenant_id, input.run_id, "prepare-context"),
        PrepareRunContext(
            run_id=UUID(input.run_id),
            environment_facts=(),
            knowledge_refs=(),
            memory_ids=(),
            history_digest=f"temporal:{input.run_id}",
            tool_versions=prepared.tool_versions,
        ),
    )
    await application.create_validated_plan(
        _context(input.tenant_id, input.run_id, "create-plan"),
        CreateValidatedPlan(
            run_id=UUID(input.run_id),
            tasks=prepared.tasks,
            skill_versions=prepared.skill_versions,
            tool_versions=prepared.tool_versions,
            model_route=prepared.model_route,
            policy_version=prepared.policy_version,
        ),
    )
    _heartbeat("plan_persisted")
    return "planned"


@activity.defn
async def cancel_run(
    input: CancelRunInput,
    dependencies: ActivityDependencies,
) -> str:
    """Cancel a Run and record the reason."""
    _heartbeat("cancel_requested")
    run = await dependencies.application.cancel_run(
        _context(input.tenant_id, input.run_id, "cancel"),
        CancelRun(UUID(input.run_id), input.reason),
    )
    if run.status.value != "cancelled":
        raise ValueError("Application did not accept Run cancellation")
    return "cancelled"


@activity.defn
async def reject_run(
    input: RejectRunInput,
    dependencies: ActivityDependencies,
) -> str:
    """Reject a Run and record the reason."""
    _heartbeat("rejection_requested")
    run = await dependencies.application.fail_run(
        _context(input.tenant_id, input.run_id, "reject"),
        FailRun(UUID(input.run_id), input.reason),
    )
    if run.status.value != "failed":
        raise ValueError("Application did not accept Run rejection")
    return "rejected"


@activity.defn
async def take_over_run(
    input: TakeOverRunInput,
    dependencies: ActivityDependencies,
) -> str:
    """Confirm an already-authorized Application takeover before automation stops."""

    _heartbeat("confirm_takeover")
    run = await dependencies.store.get_run(UUID(input.tenant_id), UUID(input.run_id))
    if run.status.value != "blocked":
        raise PermissionError(
            "manual takeover must be authorized and persisted before signaling Workflow"
        )
    return "taken_over"


@activity.defn
async def load_approval(
    input: ApprovalLookupInput,
    dependencies: ActivityDependencies,
) -> ApprovalState:
    """Reload the authoritative Approval; a Signal is only a wake-up reference."""

    _heartbeat("load_approval")
    approval = await dependencies.store.repository.get_approval(
        UUID(input.tenant_id), UUID(input.approval_id)
    )
    if approval.run_id != UUID(input.run_id):
        raise PermissionError("Approval Signal does not belong to the Workflow Run")
    return ApprovalState(str(approval.approval_id), approval.status.value)


@activity.defn
async def execute_run(
    input: ExecuteRunInput,
    dependencies: ActivityDependencies,
) -> str:
    """Dispatch ready Tasks; success remains an Application verification decision."""
    _heartbeat("load_run")
    store = dependencies.store
    run = await store.get_run(UUID(input.tenant_id), UUID(input.run_id))
    from autonoesis_domain import RunStatus

    if run.status in {RunStatus.SUCCEEDED, RunStatus.FAILED, RunStatus.CANCELLED}:
        return run.status.value

    application = dependencies.application
    for task in await store.repository.list_tasks(UUID(input.tenant_id), UUID(input.run_id)):
        if task.status.value == "pending":
            task = await application.start_task(
                _context(input.tenant_id, input.run_id, f"start-task:{task.task_id}"),
                StartTask(task.task_id),
            )
            _heartbeat(f"task_started:{task.task_id}")
        if task.status.value == "running" and dependencies.executor is not None:
            await dependencies.executor.execute(input, task, application)
            _heartbeat(f"task_executed:{task.task_id}")
    return "dispatched"


@activity.defn
async def evaluate_run(
    input: EvaluateRunInput,
    dependencies: ActivityDependencies,
) -> str:
    """Ask Application to evaluate completion from persisted Tasks and Outcomes."""
    _heartbeat("evaluate_run")
    application = dependencies.application
    try:
        run = await application.complete_run(
            _context(input.tenant_id, input.run_id, "complete-run"),
            CompleteRun(UUID(input.run_id)),
        )
    except ValueError:
        run = await dependencies.store.get_run(UUID(input.tenant_id), UUID(input.run_id))
    if run.status.value == "succeeded":
        await application.satisfy_or_fail_goal(
            _context(input.tenant_id, input.run_id, "satisfy-goal"),
            SatisfyOrFailGoal(UUID(input.goal_id), True, "verified Run satisfied Goal"),
        )
    return run.status.value


@activity.defn
async def evaluate_candidate(
    input: EvaluateCandidateInput,
    dependencies: ActivityDependencies,
) -> bool:
    """Run the evaluation suite against a Candidate.

    Returns True when the Candidate passes all gates.
    """
    tenant_id = UUID(input.tenant_id)
    candidate_id = UUID(input.candidate_id)

    evolution = dependencies.evolution
    evaluator = dependencies.candidate_evaluator
    if evolution is None or evaluator is None:
        raise ApplicationError(
            "candidate evaluation is not configured; refusing synthetic pass",
            non_retryable=True,
        )

    from autonoesis_domain import CandidateStatus

    policy = dependencies.evaluation_policy or RepeatedTrialPolicy(pass_threshold=0.8)
    # Invalid Trials are infrastructure evidence: consume the attempt budget but
    # never count toward the sample or the green rate.
    max_attempts = policy.min_valid_trials * 2
    _heartbeat("evaluate_candidate")
    await evolution.submit_for_evaluation(tenant_id, candidate_id)
    # The grader principal must stay distinct from the release executor's so the
    # domain's separation-of-duties gate can never observe them colliding.
    grader = replace(
        _context(input.tenant_id, input.candidate_id, "evaluate-candidate").identity,
        principal_id=_worker_principal("grader", input.tenant_id),
        roles=frozenset({"grader"}),
    )
    last_incompleteness = "no trial executed"
    for _attempt in range(max_attempts):
        _heartbeat("evaluate_candidate")
        trial = await evaluator.evaluate(tenant_id, candidate_id)
        trial = replace(trial, candidate_id=candidate_id)
        await dependencies.store.add_trial(trial)
        try:
            candidate, _record = await evolution.complete_evaluation(grader, candidate_id, policy)
        except ValueError as exc:
            last_incompleteness = str(exc)
            continue
        return candidate.status is CandidateStatus.AWAITING_APPROVAL
    raise ApplicationError(
        "candidate evaluation evidence is incomplete after "
        f"{max_attempts} attempts: {last_incompleteness}",
        non_retryable=True,
    )


@activity.defn
async def promote_candidate(
    input: PromoteCandidateInput,
    dependencies: ActivityDependencies,
) -> str:
    """Start an approved Candidate in Shadow; later gates own Stable release."""
    evolution = dependencies.evolution
    if evolution is not None:
        _heartbeat("promote_candidate")
        from autonoesis_application import IdentityContext

        identity = IdentityContext(
            tenant_id=UUID(input.tenant_id),
            actor_id=UUID(int=0),
            principal_id=_worker_principal("release-executor", input.tenant_id),
            roles=frozenset({"platform_admin"}),
            agent_id="temporal-release-executor",
        )
        await evolution.begin_shadow(identity, UUID(input.candidate_id))
        return "shadow"

    raise ApplicationError(
        "candidate release service is not configured; refusing synthetic promotion",
        non_retryable=True,
    )


@activity.defn
async def execute_shadow_pair(
    input: ShadowPairInput,
    dependencies: ActivityDependencies,
) -> str:
    """Execute and persist one mirrored Stable/Candidate request pair."""

    evolution = dependencies.evolution
    runtime = dependencies.shadow_runtime
    if evolution is None or runtime is None:
        raise ApplicationError(
            "shadow execution runtime is not configured; refusing synthetic comparison",
            non_retryable=True,
        )
    _heartbeat("execute_shadow_pair")
    worker = UUID(int=0)
    identity = IdentityContext(
        tenant_id=UUID(input.tenant_id),
        actor_id=worker,
        principal_id=worker,
        roles=frozenset({"shadow_executor"}),
        agent_id="temporal-shadow-worker",
    )
    comparison = await evolution.execute_shadow_pair(
        identity,
        ExecuteShadowPair(
            deployment_id=UUID(input.deployment_id),
            request_ref=input.request_ref,
            input_payload=input.input_payload,
        ),
        runtime,
    )
    _heartbeat(f"shadow_comparison_persisted:{comparison.comparison_id}")
    return str(comparison.comparison_id)


_RELEASE_COMMAND_ACTIONS = frozenset({"enter_canary", "release_stable", "rollback_release"})


@activity.defn
async def execute_release_command(
    input: ReleaseCommandInput,
    dependencies: ActivityDependencies,
) -> str:
    """Apply one release transition under the independent executor identity."""

    evolution = dependencies.evolution
    if evolution is None:
        raise ApplicationError(
            "release execution service is not configured; refusing synthetic release",
            non_retryable=True,
        )
    if input.action not in _RELEASE_COMMAND_ACTIONS:
        raise ApplicationError(
            f"unknown release command action: {input.action}",
            non_retryable=True,
        )
    _heartbeat(f"release_command:{input.action}")
    executor = _worker_principal("release-executor", input.tenant_id)
    identity = IdentityContext(
        tenant_id=UUID(input.tenant_id),
        actor_id=UUID(int=0),
        principal_id=executor,
        roles=frozenset({"release_executor"}),
        agent_id="temporal-release-executor",
    )
    if input.action == "enter_canary":
        deployment = await evolution.promote_to_canary(
            identity,
            UUID(input.deployment_id),
            TrafficAllocation(input.salt, input.candidate_percent),
        )
        _heartbeat(f"canary_entered:{deployment.deployment_id}")
        return f"canary:{deployment.deployment_id}"
    if input.action == "release_stable":
        release = await evolution.release_stable(
            identity,
            UUID(input.deployment_id),
            UUID(input.stable_version_id),
            PromotionPolicy(
                input.min_samples,
                input.observation_seconds,
                tuple(input.required_metrics),
            ),
        )
        _heartbeat(f"stable_released:{release.release_id}")
        return f"stable:{release.release_id}"
    release = await evolution.rollback(identity, UUID(input.release_id))
    _heartbeat(f"release_rolled_back:{release.release_id}")
    return f"rolled_back:{release.release_id}"
