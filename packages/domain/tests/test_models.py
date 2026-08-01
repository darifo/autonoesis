from uuid import uuid4

import pytest
from autonoesis_domain import Goal, GoalStatus, InvalidStateTransition, Run, RunStatus


def test_goal_requires_success_criteria() -> None:
    with pytest.raises(ValueError, match="success criterion"):
        Goal(tenant_id=uuid4(), statement="Ship a reliable vertical slice", success_criteria=())


def test_goal_can_be_activated_and_satisfied() -> None:
    goal = Goal(
        tenant_id=uuid4(),
        statement="Ship a reliable vertical slice",
        success_criteria=("recovery scenario passes",),
    )

    active = goal.transition_to(GoalStatus.ACTIVE)
    satisfied = active.transition_to(GoalStatus.SATISFIED)

    assert satisfied.status is GoalStatus.SATISFIED


def test_run_cannot_skip_from_pending_to_succeeded() -> None:
    run = Run(tenant_id=uuid4(), goal_id=uuid4())

    with pytest.raises(InvalidStateTransition):
        run.transition_to(RunStatus.SUCCEEDED)


def test_blocked_run_can_resume() -> None:
    run = Run(tenant_id=uuid4(), goal_id=uuid4())

    resumed = run.transition_to(RunStatus.RUNNING).transition_to(RunStatus.BLOCKED)
    resumed = resumed.transition_to(RunStatus.RUNNING)

    assert resumed.status is RunStatus.RUNNING
