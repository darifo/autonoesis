from dataclasses import replace
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from autonoesis_domain import (
    Action,
    ActionExecutionEnvelope,
    ApprovalRequest,
    BudgetAmount,
    CandidateStatus,
    CandidateVersion,
    DataClassification,
    DeploymentStatus,
    Evidence,
    EvidenceCaptureMethod,
    EvidenceIntegrity,
    ExecutionMode,
    GoalContract,
    GoalStatus,
    InvalidStateTransition,
    JsonObject,
    Outcome,
    OutcomeStatus,
    Plan,
    RiskLevel,
    RiskTier,
    Run,
    RunExecutionSnapshot,
    RunStatus,
    Session,
    SessionStatus,
    SubjectRef,
    SuccessCriterion,
    Task,
)


def make_goal() -> GoalContract:
    return GoalContract(
        tenant_id=uuid4(),
        goal_type="example.deliver-result",
        statement="Deliver a verified result",
        desired_outcome="authoritative state meets the requested condition",
        subject_refs=(SubjectRef("crm", "account", "A-42", "v7"),),
        success_criteria=(SuccessCriterion("verified", "state is verified", "system-read"),),
        constraints=("no unauthorized writes",),
        owner_id=uuid4(),
        risk_tier=RiskTier.MEDIUM,
        budget_limit=BudgetAmount(100),
        deadline=datetime.now(UTC) + timedelta(days=1),
        input_payload=JsonObject.from_value({"request": "deliver"}),
    )


def test_goal_is_industry_neutral_and_requires_external_subjects() -> None:
    goal = make_goal()
    actor_id = uuid4()
    active = goal.transition_to(
        GoalStatus.ACTIVE,
        actor_id=actor_id,
        reason="test activation",
    )
    assert goal.subject_refs[0].system == "crm"
    assert active.status is GoalStatus.ACTIVE
    assert active.version == goal.version + 1
    assert active.transitions[-1].actor_id == actor_id
    assert active.transitions[-1].reason == "test activation"


def test_goal_rejects_expired_deadline_and_illegal_budget() -> None:
    with pytest.raises(ValueError, match="budget"):
        replace(make_goal(), budget_limit=BudgetAmount(0))
    with pytest.raises(ValueError, match="deadline"):
        replace(make_goal(), deadline=datetime.now(UTC) - timedelta(seconds=1))


def test_session_closure_does_not_change_goal_or_run() -> None:
    goal = make_goal().transition_to(GoalStatus.ACTIVE, reason="test activation")
    run = Run(goal.tenant_id, goal.goal_id, uuid4())
    session = Session(goal.tenant_id, uuid4(), "web", (goal.goal_id,)).close()
    assert session.status is SessionStatus.CLOSED
    assert run.status is RunStatus.PENDING
    assert goal.status is GoalStatus.ACTIVE


def test_run_cannot_skip_pending_to_success() -> None:
    run = Run(uuid4(), uuid4(), uuid4())
    with pytest.raises(InvalidStateTransition):
        run.transition_to(RunStatus.SUCCEEDED)


def test_candidate_requires_evaluation_and_approval_before_stable() -> None:
    candidate = CandidateVersion(uuid4(), uuid4(), uuid4(), "s3://candidate", "generator")
    approved = (
        candidate.transition_to(CandidateStatus.EVALUATING)
        .transition_to(CandidateStatus.AWAITING_APPROVAL)
        .transition_to(CandidateStatus.APPROVED)
    )
    deployment = approved.begin_deployment(actor_id=uuid4(), reason="approved for shadow")
    with pytest.raises(InvalidStateTransition):
        deployment.transition_to(
            DeploymentStatus.STABLE,
            actor_id=uuid4(),
            reason="attempted gate bypass",
        )
    stable = deployment.transition_to(
        DeploymentStatus.CANARY, actor_id=uuid4(), reason="shadow passed"
    ).transition_to(DeploymentStatus.STABLE, actor_id=uuid4(), reason="canary passed")
    assert stable.status is DeploymentStatus.STABLE


def test_plan_rejects_indirect_dependency_cycle() -> None:
    tenant_id, run_id, goal_id = uuid4(), uuid4(), uuid4()
    first_id, second_id = uuid4(), uuid4()
    first = Task(tenant_id, run_id, "first", "done", (second_id,), task_id=first_id)
    second = Task(tenant_id, run_id, "second", "done", (first_id,), task_id=second_id)
    with pytest.raises(ValueError, match="cycle"):
        Plan(tenant_id, goal_id, run_id, (first, second))


def test_nested_action_digest_binds_every_executable_field() -> None:
    action = Action(
        tenant_id=uuid4(),
        run_id=uuid4(),
        task_id=uuid4(),
        tool_name="records",
        tool_version="2.1.0",
        operation="create",
        resource_scope="accounts/A-42/records",
        parameters=JsonObject.from_value(
            {"record": {"tags": ["governed", "verified"], "priority": 2}}
        ),
        risk_level=RiskLevel.L2_REVERSIBLE_WRITE,
        idempotency_key="action-1",
        expected_effect="one record exists",
    )
    modified = replace(action, resource_scope="accounts/A-99/records")
    variants = (
        replace(action, tool_name="other-records"),
        replace(action, tool_version="2.2.0"),
        replace(action, operation="update"),
        modified,
        replace(
            action,
            parameters=JsonObject.from_value(
                {"record": {"tags": ["governed", "verified"], "priority": 3}}
            ),
        ),
    )
    assert all(action.canonical_digest != variant.canonical_digest for variant in variants)

    approval = ApprovalRequest(
        tenant_id=action.tenant_id,
        run_id=action.run_id,
        action_id=action.action_id,
        action_digest=action.canonical_digest,
        tool_version=action.tool_version,
        operation=action.operation,
        resource_scope=action.resource_scope,
        argument_digest=action.parameter_digest,
        policy_version="policy-v3",
        impact_summary="create a reversible record",
        required_role="approver",
        expires_at=datetime.now(UTC) + timedelta(minutes=5),
    ).decide(uuid4(), True, "scope checked")
    assert approval.authorizes(action, "policy-v3")
    assert not approval.authorizes(modified, "policy-v3")
    assert not approval.authorizes(action, "policy-v4")
    with pytest.raises(ValueError, match="binding"):
        replace(approval, policy_version="")


def test_run_requires_and_freezes_execution_snapshot() -> None:
    run = Run(uuid4(), uuid4(), uuid4())
    with pytest.raises(ValueError, match="fixed execution snapshot"):
        run.transition_to(RunStatus.RUNNING)
    snapshot = RunExecutionSnapshot(
        plan_id=uuid4(),
        context_snapshot_id=uuid4(),
        agent_version_id=run.agent_version_id,
        skill_versions=("review@1.2.0",),
        tool_versions=("records@2.1.0",),
        model_route="balanced-v2",
        policy_version="policy-v3",
    )
    bound = run.bind_execution(snapshot)
    assert bound.transition_to(RunStatus.RUNNING).execution_snapshot == snapshot
    with pytest.raises(ValueError, match="immutable"):
        bound.bind_execution(
            RunExecutionSnapshot(
                plan_id=uuid4(),
                context_snapshot_id=snapshot.context_snapshot_id,
                agent_version_id=run.agent_version_id,
                skill_versions=snapshot.skill_versions,
                tool_versions=snapshot.tool_versions,
                model_route=snapshot.model_route,
                policy_version=snapshot.policy_version,
            )
        )


def test_verified_outcome_requires_complete_evidence_metadata() -> None:
    now = datetime.now(UTC)
    evidence = Evidence(
        tenant_id=uuid4(),
        run_id=uuid4(),
        action_id=uuid4(),
        source="crm",
        source_identity="crm-readback-service",
        capture_method=EvidenceCaptureMethod.AUTHORITATIVE_READBACK,
        reference="crm://records/42",
        observed_state="record exists",
        content_digest="a" * 64,
        classification=DataClassification.INTERNAL,
        valid_from=now - timedelta(seconds=1),
        valid_until=now + timedelta(minutes=5),
        integrity=EvidenceIntegrity.VERIFIED,
        captured_at=now,
    )
    outcome = Outcome(
        tenant_id=evidence.tenant_id,
        goal_id=uuid4(),
        run_id=evidence.run_id,
        criterion_id="record-created",
        verifier_version="crm-readback@1.0.0",
        status=OutcomeStatus.VERIFIED,
        evidence=(evidence,),
        verified_at=now,
    )
    assert outcome.status is OutcomeStatus.VERIFIED
    with pytest.raises(ValueError, match="integrity-verified"):
        replace(outcome, evidence=(replace(evidence, integrity=EvidenceIntegrity.UNVERIFIED),))


def test_execution_envelope_rejects_tampered_action_digest() -> None:
    action = Action(
        tenant_id=uuid4(),
        run_id=uuid4(),
        task_id=uuid4(),
        tool_name="records",
        tool_version="2.1.0",
        operation="read",
        resource_scope="accounts/A-42",
        parameters=JsonObject.from_value({"include": ["status"]}),
        risk_level=RiskLevel.L1_READ,
        idempotency_key="read-1",
        expected_effect="account state returned",
        classification=DataClassification.CONFIDENTIAL,
        execution_mode=ExecutionMode.SUPERVISED,
    )
    envelope = ActionExecutionEnvelope.from_action(
        action,
        actor_id=uuid4(),
        principal_id=uuid4(),
        agent_identity="agent@7",
        delegation_ref="delegation://42",
        budget_ref="budget://run",
        approval_id=None,
        policy_version="policy-v3",
        deadline=datetime.now(UTC) + timedelta(minutes=2),
        traceparent="00-0123456789abcdef0123456789abcdef-0123456789abcdef-01",
    )
    assert envelope.action_digest == action.canonical_digest
    with pytest.raises(ValueError, match="does not match"):
        replace(envelope, action_digest="b" * 64)
