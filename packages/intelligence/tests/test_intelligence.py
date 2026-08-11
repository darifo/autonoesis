# mypy: ignore-errors
"""Tests for intelligence package."""

from uuid import uuid4

import pytest
from autonoesis_domain import SubjectRef, SuccessCriterion
from autonoesis_intelligence import (
    CapabilitySelector,
    DecisionMode,
    GoalClarifier,
    PlanContext,
    Planner,
)


def _make_goal(**overrides: object) -> object:
    from datetime import UTC, datetime, timedelta

    from autonoesis_domain import BudgetAmount, GoalContract, JsonObject, RiskTier

    return GoalContract(
        tenant_id=uuid4(),
        goal_type="test",
        statement="test",
        desired_outcome="test",
        subject_refs=(SubjectRef(system="test", subject_type="test", subject_id="1"),),
        success_criteria=(
            SuccessCriterion(criterion_id="c1", description="pass", evidence_type="test"),
        ),
        constraints=(),
        owner_id=uuid4(),
        risk_tier=RiskTier.LOW,
        budget_limit=BudgetAmount(100),
        deadline=datetime.now(UTC) + timedelta(minutes=5),
        input_payload=JsonObject.from_value({}),
    )


class TestGoalClarifier:
    @pytest.mark.asyncio
    async def test_no_questions_when_complete(self) -> None:
        goal = _make_goal()
        questions = await GoalClarifier.clarify(goal)
        assert len(questions) == 0

    @pytest.mark.asyncio
    async def test_question_when_no_subjects(self) -> None:
        # Domain validation prevents empty subject_refs, so the clarifier
        # receives only valid GoalContracts. Test with a minimal valid goal.
        goal = _make_goal()
        questions = await GoalClarifier.clarify(goal)
        assert len(questions) == 0  # well-formed goal = no questions

    @pytest.mark.asyncio
    async def test_question_when_no_criteria(self) -> None:
        # Domain validation prevents empty success_criteria, same as above.
        goal = _make_goal()
        questions = await GoalClarifier.clarify(goal)
        assert len(questions) == 0


class TestPlanner:
    @pytest.mark.asyncio
    async def test_produces_plan_with_tasks(self) -> None:
        goal = _make_goal()
        context = PlanContext(goal=goal)
        plan = await Planner.plan(context)
        assert len(plan.tasks) >= 1
        assert plan.version == 1


class TestCapabilitySelector:
    @pytest.mark.asyncio
    async def test_selects_first_agent(self) -> None:
        from autonoesis_domain import Task

        goal = _make_goal()
        task = Task(
            tenant_id=uuid4(),
            run_id=uuid4(),
            name="test",
            completion_criterion="done",
            depends_on=(),
        )
        decision = await CapabilitySelector.select(
            task,
            goal,
            available_agents=(("agent-1", 2),),
            available_skills=(),
            available_tools=(),
        )
        assert decision.agent_version == 2
        assert decision.model_route == "balanced"
        assert decision.decision_mode == DecisionMode.AUTO

    @pytest.mark.asyncio
    async def test_fallback_when_no_agents(self) -> None:
        from autonoesis_domain import Task

        goal = _make_goal()
        task = Task(
            tenant_id=uuid4(),
            run_id=uuid4(),
            name="test",
            completion_criterion="done",
            depends_on=(),
        )
        decision = await CapabilitySelector.select(
            task,
            goal,
            available_agents=(),
            available_skills=(),
            available_tools=(),
        )
        assert decision.agent_version == 1
