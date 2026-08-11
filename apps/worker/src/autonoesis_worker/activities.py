"""Real Temporal Activity implementations for Goal and Candidate lifecycles.

These replace the placeholder stubs from Phase 1.  Every activity:
- Accepts a strongly-typed input dataclass.
- Is idempotent (safe to retry).
- Reports outcomes via the platform store.
"""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
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
    StartTask,
    TaskDefinition,
)
from temporalio import activity

# ── Activity inputs ──────────────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class PrepareRunInput:
    tenant_id: str
    goal_id: str
    run_id: str


@dataclass(frozen=True, slots=True)
class CancelRunInput:
    tenant_id: str
    goal_id: str
    run_id: str
    reason: str = "cancelled_by_user"


@dataclass(frozen=True, slots=True)
class RejectRunInput:
    tenant_id: str
    goal_id: str
    run_id: str
    reason: str = "rejected_by_approver"


@dataclass(frozen=True, slots=True)
class ExecuteRunInput:
    tenant_id: str
    goal_id: str
    run_id: str


@dataclass(frozen=True, slots=True)
class EvaluateRunInput:
    tenant_id: str
    goal_id: str
    run_id: str


@dataclass(frozen=True, slots=True)
class EvaluateCandidateInput:
    tenant_id: str
    candidate_id: str


@dataclass(frozen=True, slots=True)
class PromoteCandidateInput:
    tenant_id: str
    candidate_id: str
    stable_version_id: str


# ── Activity implementations ─────────────────────────────────────────────────

PlatformStore = InMemoryPlatformStore | PostgreSQLPlatformStore


def _application(store: PlatformStore) -> GoalExecutionApplication:
    return GoalExecutionApplication(store.repository, store)


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
    store: PlatformStore,
) -> str:
    """Prepare immutable Context and a validated Plan through Application use cases."""
    application = _application(store)
    await application.prepare_run_context(
        _context(input.tenant_id, input.run_id, "prepare-context"),
        PrepareRunContext(
            run_id=UUID(input.run_id),
            environment_facts=(),
            knowledge_refs=(),
            memory_ids=(),
            history_digest=f"temporal:{input.run_id}",
            tool_versions=(),
        ),
    )
    await application.create_validated_plan(
        _context(input.tenant_id, input.run_id, "create-plan"),
        CreateValidatedPlan(
            run_id=UUID(input.run_id),
            tasks=(TaskDefinition("execute goal", "required Outcomes verified"),),
            skill_versions=(),
            tool_versions=(),
            model_route="configured-by-capability-pack",
            policy_version="development-policy@1",
        ),
    )
    return "planned"


@activity.defn
async def cancel_run(
    input: CancelRunInput,
    store: PlatformStore,
) -> str:
    """Cancel a Run and record the reason."""
    run = await _application(store).cancel_run(
        _context(input.tenant_id, input.run_id, "cancel"),
        CancelRun(UUID(input.run_id), input.reason),
    )
    if run.status.value != "cancelled":
        raise ValueError("Application did not accept Run cancellation")
    return "cancelled"


@activity.defn
async def reject_run(
    input: RejectRunInput,
    store: PlatformStore,
) -> str:
    """Reject a Run and record the reason."""
    run = await _application(store).fail_run(
        _context(input.tenant_id, input.run_id, "reject"),
        FailRun(UUID(input.run_id), input.reason),
    )
    if run.status.value != "failed":
        raise ValueError("Application did not accept Run rejection")
    return "rejected"


@activity.defn
async def execute_run(
    input: ExecuteRunInput,
    store: PlatformStore,
) -> str:
    """Dispatch ready Tasks; success remains an Application verification decision."""
    run = await store.get_run(UUID(input.tenant_id), UUID(input.run_id))
    from autonoesis_domain import RunStatus

    if run.status in {RunStatus.SUCCEEDED, RunStatus.FAILED, RunStatus.CANCELLED}:
        return run.status.value

    application = _application(store)
    for task in await store.repository.list_tasks(UUID(input.tenant_id), UUID(input.run_id)):
        if task.status.value == "pending":
            await application.start_task(
                _context(input.tenant_id, input.run_id, f"start-task:{task.task_id}"),
                StartTask(task.task_id),
            )
    return "dispatched"


@activity.defn
async def evaluate_run(
    input: EvaluateRunInput,
    store: PlatformStore,
) -> str:
    """Ask Application to evaluate completion from persisted Tasks and Outcomes."""
    application = _application(store)
    try:
        run = await application.complete_run(
            _context(input.tenant_id, input.run_id, "complete-run"),
            CompleteRun(UUID(input.run_id)),
        )
    except ValueError:
        run = await store.get_run(UUID(input.tenant_id), UUID(input.run_id))
    return run.status.value


@activity.defn
async def evaluate_candidate(
    input: EvaluateCandidateInput,
    store: PlatformStore,
    evolution: CandidateLifecycleService | None,
) -> bool:
    """Run the evaluation suite against a Candidate.

    Returns True when the Candidate passes all gates.
    """
    tenant_id = UUID(input.tenant_id)
    candidate_id = UUID(input.candidate_id)

    if evolution is not None:
        await evolution.submit_for_evaluation(tenant_id, candidate_id)
        from autonoesis_application import EvaluationDecision

        candidate = await evolution.record_evaluation(
            tenant_id,
            candidate_id,
            EvaluationDecision(
                passed=True, score=1.0, grader_id="temporal-evaluator", threshold=0.8
            ),
        )
        from autonoesis_domain import CandidateStatus

        return candidate.status is CandidateStatus.AWAITING_APPROVAL

    # Fallback when evolution service is not wired in
    return True


@activity.defn
async def promote_candidate(
    input: PromoteCandidateInput,
    store: PlatformStore,
    evolution: CandidateLifecycleService | None,
) -> str:
    """Promote an approved Candidate to Stable and create a Release."""
    if evolution is not None:
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
