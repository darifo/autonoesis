"""Vertical tests for Application-owned governed execution."""

from datetime import UTC, datetime, timedelta
from hashlib import sha256
from uuid import UUID, uuid4

import pytest
from autonoesis_adapters import InMemoryPlatformStore
from autonoesis_application import (
    ActivateGoal,
    AuthorizeActionAtExecutionTime,
    CancelRun,
    CommandContext,
    CompleteRun,
    CompleteTask,
    ConcurrencyConflict,
    CreateGoal,
    CreateValidatedPlan,
    DecideApproval,
    GoalExecutionApplication,
    IdentityContext,
    PrepareRunContext,
    ProposeAction,
    ReconcileUnknownAction,
    RecordActionAttempt,
    RecordEvidence,
    RequestApproval,
    RequestRun,
    SatisfyOrFailGoal,
    StartTask,
    TakeOverRun,
    TaskDefinition,
    VerifyOutcome,
)
from autonoesis_capability import parse_manifest
from autonoesis_domain import (
    Action,
    ActionAttemptStatus,
    ActionStatus,
    AgentVersion,
    ApprovalStatus,
    AssetStage,
    CompensationCapability,
    DataClassification,
    Evidence,
    EvidenceCaptureMethod,
    EvidenceIntegrity,
    GoalStatus,
    LoopPolicy,
    OutcomeStatus,
    RiskLevel,
    RiskTier,
    RunStatus,
    SubjectRef,
    SuccessCriterion,
)


def _manifest() -> dict[str, object]:
    return {
        "api_version": "autonoesis/v1alpha1",
        "pack_id": "vertical-pack",
        "version": "1.0.0",
        "python_entry_point": "vertical_pack.plugin:create",
        "goal_types": [
            {
                "goal_type": "vertical.deliver",
                "input_schema": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["request"],
                    "properties": {"request": {"type": "string"}},
                },
                "agent": "vertical-agent",
                "evaluation_suite": "vertical-suite",
                "default_policy": "vertical-policy",
                "default_budget": 100,
            }
        ],
        "skills": [],
        "tools": ["records"],
        "policies": ["vertical-policy"],
        "evaluation_suites": ["vertical-suite"],
    }


def _setup(
    store: InMemoryPlatformStore | None = None,
) -> tuple[InMemoryPlatformStore, GoalExecutionApplication, IdentityContext]:
    actual = store or InMemoryPlatformStore()
    tenant_id, actor_id = uuid4(), uuid4()
    actual.register_pack(parse_manifest(_manifest()))
    actual.register_agent(
        "vertical-agent",
        AgentVersion(
            tenant_id,
            uuid4(),
            1,
            "deliver only verified outcomes",
            "balanced",
            (),
            ("records",),
            LoopPolicy(5, 1000, 100, 60),
            AssetStage.STABLE,
        ),
    )
    identity = IdentityContext(
        tenant_id,
        actor_id,
        actor_id,
        frozenset({"operator", "approver", "tenant_admin"}),
        "vertical-agent",
    )
    return actual, GoalExecutionApplication(actual.repository, actual), identity


def _context(identity: IdentityContext, key: str) -> CommandContext:
    correlation_id = uuid4()
    return CommandContext(
        identity,
        correlation_id,
        correlation_id,
        key,
        sha256(key.encode("utf-8")).hexdigest(),
    )


def _goal_command(correlation_id: UUID | None = None) -> CreateGoal:
    return CreateGoal(
        goal_type="vertical.deliver",
        statement="deliver requested state",
        desired_outcome="authoritative state verified",
        subject_refs=(SubjectRef("records", "record", "42"),),
        success_criteria=(
            SuccessCriterion("verified", "record state verified", "authoritative-readback"),
        ),
        constraints=(),
        owner_id=uuid4(),
        risk_tier=RiskTier.MEDIUM,
        budget_limit=100,
        deadline=datetime.now(UTC) + timedelta(hours=1),
        input_payload={"request": "deliver"},
        correlation_id=correlation_id or uuid4(),
    )


async def _prepare_action(
    application: GoalExecutionApplication,
    identity: IdentityContext,
    *,
    suffix: str,
    risk: RiskLevel = RiskLevel.L2_REVERSIBLE_WRITE,
) -> tuple[UUID, UUID, Action]:
    goal = await application.create_goal(_context(identity, f"goal-{suffix}"), _goal_command())
    await application.activate_goal(
        _context(identity, f"activate-{suffix}"), ActivateGoal(goal.goal_id)
    )
    run = await application.request_run(
        _context(identity, f"run-{suffix}"), RequestRun(goal.goal_id)
    )
    await application.prepare_run_context(
        _context(identity, f"context-{suffix}"),
        PrepareRunContext(run.run_id, (), (), (), f"history-{suffix}", ("records@1.0.0",)),
    )
    task_id = uuid4()
    await application.create_validated_plan(
        _context(identity, f"plan-{suffix}"),
        CreateValidatedPlan(
            run.run_id,
            (
                TaskDefinition(
                    "write state",
                    "authoritative state observed",
                    risk_level=risk,
                    compensation=CompensationCapability.AVAILABLE,
                    evidence_requirements=("authoritative-readback",),
                    task_id=task_id,
                ),
            ),
            (),
            ("records@1.0.0",),
            "balanced",
            "vertical-policy@1",
        ),
    )
    await application.start_task(_context(identity, f"start-task-{suffix}"), StartTask(task_id))
    action = await application.propose_action(
        _context(identity, f"action-{suffix}"),
        ProposeAction(
            task_id,
            "records",
            "1.0.0",
            "update",
            "records/42",
            {"status": "delivered"},
            risk,
            "record status becomes delivered",
        ),
    )
    return goal.goal_id, task_id, action


@pytest.mark.asyncio
async def test_reference_goal_reaches_verified_outcome_without_receipt_shortcut() -> None:
    store, application, identity = _setup()
    goal_id, task_id, action = await _prepare_action(application, identity, suffix="happy")
    approval = await application.request_approval(
        _context(identity, "approval-happy"),
        RequestApproval(
            action.action_id,
            "vertical-policy@1",
            "reversible record update",
            "approver",
            datetime.now(UTC) + timedelta(minutes=10),
        ),
    )
    decided = await application.decide_approval(
        _context(identity, "decision-happy"),
        DecideApproval(approval.approval_id, action.canonical_digest, True, "impact accepted"),
    )
    assert decided.status is ApprovalStatus.APPROVED
    envelope = await application.authorize_action_at_execution_time(
        _context(identity, "authorize-happy"),
        AuthorizeActionAtExecutionTime(
            action.action_id,
            "vertical-policy@1",
            True,
            "policy allowed",
            approval.approval_id,
            "vertical-agent@1",
            "delegation://operator",
            "budget://run",
            datetime.now(UTC) + timedelta(minutes=5),
            "00-test-trace",
        ),
    )
    completed_action = await application.record_action_attempt(
        _context(identity, "attempt-happy"),
        RecordActionAttempt(
            action.action_id,
            envelope.invocation_id,
            ActionAttemptStatus.SUCCEEDED,
            "receipt://records/42",
            "records-adapter@1",
        ),
    )
    assert completed_action.status is ActionStatus.SUCCEEDED
    await application.complete_task(
        _context(identity, "complete-task-happy"),
        CompleteTask(task_id, True, "Action and readback completed"),
    )
    now = datetime.now(UTC)
    evidence = Evidence(
        identity.tenant_id,
        completed_action.run_id,
        action.action_id,
        "records",
        "records-authority@1",
        EvidenceCaptureMethod.AUTHORITATIVE_READBACK,
        "records://42",
        "status=delivered",
        "a" * 64,
        DataClassification.INTERNAL,
        now - timedelta(seconds=1),
        now + timedelta(minutes=5),
        EvidenceIntegrity.VERIFIED,
        captured_at=now,
    )
    await application.record_evidence(
        _context(identity, "evidence-happy"), RecordEvidence(evidence)
    )
    outcome = await application.verify_outcome(
        _context(identity, "outcome-happy"),
        VerifyOutcome(
            completed_action.run_id,
            "verified",
            "readback-verifier@1",
            OutcomeStatus.VERIFIED,
            (evidence.evidence_id,),
            now,
        ),
    )
    assert outcome.evidence == (evidence,)
    run = await application.complete_run(
        _context(identity, "complete-run-happy"), CompleteRun(completed_action.run_id)
    )
    assert run.status is RunStatus.SUCCEEDED
    goal = await application.satisfy_or_fail_goal(
        _context(identity, "finish-goal-happy"),
        SatisfyOrFailGoal(goal_id, True, "all contractual Outcomes verified"),
    )
    assert goal.status is GoalStatus.SATISFIED
    assert len(store.action_attempts) == 1
    assert len(store.evidence) == 1
    assert len(store.outcomes) == 1


@pytest.mark.asyncio
async def test_rejected_approval_denies_action_and_conflicting_retry_is_rejected() -> None:
    _, application, identity = _setup()
    _, _, action = await _prepare_action(application, identity, suffix="reject")
    approval = await application.request_approval(
        _context(identity, "approval-reject"),
        RequestApproval(
            action.action_id,
            "vertical-policy@1",
            "write impact",
            "approver",
            datetime.now(UTC) + timedelta(minutes=5),
        ),
    )
    rejected = await application.decide_approval(
        _context(identity, "decision-reject"),
        DecideApproval(approval.approval_id, action.canonical_digest, False, "impact denied"),
    )
    assert rejected.status is ApprovalStatus.REJECTED
    with pytest.raises(ValueError, match="already been decided"):
        await application.decide_approval(
            _context(identity, "decision-conflict"),
            DecideApproval(approval.approval_id, action.canonical_digest, True, "changed mind"),
        )


@pytest.mark.asyncio
async def test_unknown_action_requires_explicit_reconciliation() -> None:
    _, application, identity = _setup()
    _, _, action = await _prepare_action(
        application, identity, suffix="unknown", risk=RiskLevel.L1_READ
    )
    envelope = await application.authorize_action_at_execution_time(
        _context(identity, "authorize-unknown"),
        AuthorizeActionAtExecutionTime(
            action.action_id,
            "vertical-policy@1",
            True,
            "read allowed",
            None,
            "vertical-agent@1",
            "delegation://operator",
            "budget://run",
            datetime.now(UTC) + timedelta(minutes=5),
            "00-unknown-trace",
        ),
    )
    unknown = await application.record_action_attempt(
        _context(identity, "attempt-unknown"),
        RecordActionAttempt(
            action.action_id,
            envelope.invocation_id,
            ActionAttemptStatus.UNKNOWN,
            "receipt://timeout",
            "records-adapter@1",
        ),
    )
    assert unknown.status is ActionStatus.UNKNOWN
    reconciled = await application.reconcile_unknown_action(
        _context(identity, "reconcile-unknown"),
        ReconcileUnknownAction(
            action.action_id,
            envelope.invocation_id,
            True,
            "readback://records/42",
            "records-reconciler@1",
        ),
    )
    assert reconciled.status is ActionStatus.SUCCEEDED


@pytest.mark.asyncio
async def test_deadline_and_idempotent_retry_are_first_class() -> None:
    _, application, identity = _setup()
    context = _context(identity, "same-create-key")
    first = await application.create_goal(context, _goal_command(context.correlation_id))
    retried = await application.create_goal(context, _goal_command(context.correlation_id))
    assert retried.goal_id == first.goal_id
    with pytest.raises(ConcurrencyConflict, match="different request"):
        await application.create_goal(
            CommandContext(
                identity,
                uuid4(),
                uuid4(),
                context.idempotency_key,
                "b" * 64,
            ),
            _goal_command(),
        )
    await application.activate_goal(
        _context(identity, "activate-timeout"), ActivateGoal(first.goal_id)
    )
    run = await application.request_run(
        _context(identity, "run-timeout"), RequestRun(first.goal_id)
    )
    await application.prepare_run_context(
        _context(identity, "context-timeout"),
        PrepareRunContext(run.run_id, (), (), (), "history-timeout", ()),
    )
    task_id = uuid4()
    await application.create_validated_plan(
        _context(identity, "plan-timeout"),
        CreateValidatedPlan(
            run.run_id,
            (TaskDefinition("read", "read complete", task_id=task_id),),
            (),
            (),
            "balanced",
            "vertical-policy@1",
        ),
    )
    await application.start_task(_context(identity, "start-timeout"), StartTask(task_id))
    action = await application.propose_action(
        _context(identity, "action-timeout"),
        ProposeAction(
            task_id,
            "records",
            "1.0.0",
            "read",
            "records/42",
            {},
            RiskLevel.L1_READ,
            "record returned",
        ),
    )
    with pytest.raises(ValueError, match="deadline has expired"):
        await application.authorize_action_at_execution_time(
            _context(identity, "authorize-timeout"),
            AuthorizeActionAtExecutionTime(
                action.action_id,
                "vertical-policy@1",
                True,
                "allowed",
                None,
                "vertical-agent@1",
                "delegation://operator",
                "budget://run",
                datetime.now(UTC) - timedelta(seconds=1),
                "00-timeout-trace",
            ),
        )


@pytest.mark.asyncio
async def test_manual_takeover_and_cancellation_are_application_transitions() -> None:
    _, application, identity = _setup()
    _, _, action = await _prepare_action(
        application, identity, suffix="takeover", risk=RiskLevel.L1_READ
    )
    blocked = await application.take_over_run(
        _context(identity, "take-over"),
        TakeOverRun(action.run_id, "operator assumed manual control"),
    )
    assert blocked.status is RunStatus.BLOCKED
    cancelled = await application.cancel_run(
        _context(identity, "cancel-after-takeover"),
        CancelRun(action.run_id, "manual process replaced automation"),
    )
    assert cancelled.status is RunStatus.CANCELLED


class _FailingRunSaveStore(InMemoryPlatformStore):
    async def save_run(self, *args: object, **kwargs: object) -> None:
        _ = (args, kwargs)
        raise ConcurrencyConflict("injected optimistic conflict")


@pytest.mark.asyncio
async def test_plan_and_idempotency_roll_back_when_run_update_conflicts() -> None:
    injected = _FailingRunSaveStore()
    store, application, identity = _setup(injected)
    goal = await application.create_goal(_context(identity, "goal-rollback"), _goal_command())
    await application.activate_goal(
        _context(identity, "activate-rollback"), ActivateGoal(goal.goal_id)
    )
    run = await application.request_run(
        _context(identity, "run-rollback"), RequestRun(goal.goal_id)
    )
    await application.prepare_run_context(
        _context(identity, "context-rollback"),
        PrepareRunContext(run.run_id, (), (), (), "history-rollback", ()),
    )
    with pytest.raises(ConcurrencyConflict, match="injected"):
        await application.create_validated_plan(
            _context(identity, "plan-rollback"),
            CreateValidatedPlan(
                run.run_id,
                (TaskDefinition("compute", "computed"),),
                (),
                (),
                "balanced",
                "vertical-policy@1",
            ),
        )
    assert store.plans == {}
    assert store.tasks == {}
    assert (
        await store.get_idempotency(identity.tenant_id, "create_validated_plan:plan-rollback")
        is None
    )
