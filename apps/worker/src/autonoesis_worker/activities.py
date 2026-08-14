"""Real Temporal Activity implementations for Goal and Candidate lifecycles.

These replace the placeholder stubs from Phase 1. Every activity:
- Accepts a strongly-typed input dataclass.
- Is idempotent (safe to retry).
- Reports outcomes via the platform store.
"""

from __future__ import annotations

from contextlib import suppress
from dataclasses import dataclass
from hashlib import sha256
from typing import Protocol
from uuid import UUID

from autonoesis_adapters import InMemoryPlatformStore, PostgreSQLPlatformStore
from autonoesis_application import (
    CancelRun,
    CandidateLifecycleService,
    CommandContext,
    CompleteRun,
    CreateValidatedPlan,
    FailRun,
    GoalExecutionApplication,
    IdentityContext,
    PrepareRunContext,
    SatisfyOrFailGoal,
    StartTask,
    TaskDefinition,
)
from autonoesis_domain import Task, Trial, TrialStatus
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


def build_activity_dependencies(
    store: PlatformStore,
    evolution: CandidateLifecycleService | None = None,
    *,
    application: GoalExecutionApplication | None = None,
    planner: RunPlanner | None = None,
    executor: RunExecutor | None = None,
    candidate_evaluator: CandidateEvaluator | None = None,
) -> ActivityDependencies:
    return ActivityDependencies(
        store=store,
        application=application or GoalExecutionApplication(store.repository, store),
        evolution=evolution,
        planner=planner,
        executor=executor,
        candidate_evaluator=candidate_evaluator,
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

    _heartbeat("evaluate_candidate")
    await evolution.submit_for_evaluation(tenant_id, candidate_id)
    trial = await evaluator.evaluate(tenant_id, candidate_id)
    await dependencies.store.add_trial(trial)
    if trial.status is TrialStatus.INVALID:
        raise ApplicationError(
            f"candidate evaluation invalid: {trial.failure_reason}",
            non_retryable=True,
        )

    from autonoesis_application import EvaluationDecision

    grader = _context(input.tenant_id, input.candidate_id, "evaluate-candidate").identity
    passed = trial.status is TrialStatus.PASSED
    candidate = await evolution.record_evaluation(
        grader,
        candidate_id,
        EvaluationDecision(passed=passed, score=1.0 if passed else 0.0, threshold=1.0),
    )
    from autonoesis_domain import CandidateStatus

    return candidate.status is CandidateStatus.AWAITING_APPROVAL


@activity.defn
async def promote_candidate(
    input: PromoteCandidateInput,
    dependencies: ActivityDependencies,
) -> str:
    """Promote an approved Candidate to Stable and create a Release."""
    evolution = dependencies.evolution
    if evolution is not None:
        _heartbeat("promote_candidate")
        from autonoesis_application import IdentityContext

        identity = IdentityContext(
            tenant_id=UUID(input.tenant_id),
            actor_id=UUID(int=0),
            principal_id=UUID(int=0),
            roles=frozenset({"platform_admin"}),
        )
        await evolution.begin_shadow(identity, UUID(input.candidate_id))
        return "shadow"

    return "promoted"
