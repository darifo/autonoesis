from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from autonoesis_domain import (
    CandidateStatus,
    CandidateVersion,
    GoalContract,
    GoalStatus,
    InvalidStateTransition,
    Run,
    RunStatus,
    Session,
    SessionStatus,
    SubjectRef,
    SuccessCriterion,
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
        risk_tier="medium",
        budget_limit=100,
        deadline=datetime.now(UTC) + timedelta(days=1),
        input_payload={"request": "deliver"},
    )


def test_goal_is_industry_neutral_and_requires_external_subjects() -> None:
    goal = make_goal()
    assert goal.subject_refs[0].system == "crm"
    assert goal.transition_to(GoalStatus.ACTIVE).status is GoalStatus.ACTIVE


def test_session_closure_does_not_change_goal_or_run() -> None:
    goal = make_goal().transition_to(GoalStatus.ACTIVE)
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
    with pytest.raises(InvalidStateTransition):
        candidate.transition_to(CandidateStatus.STABLE)
    stable = (
        candidate.transition_to(CandidateStatus.EVALUATING)
        .transition_to(CandidateStatus.AWAITING_APPROVAL)
        .transition_to(CandidateStatus.APPROVED)
        .transition_to(CandidateStatus.STABLE)
    )
    assert stable.status is CandidateStatus.STABLE
