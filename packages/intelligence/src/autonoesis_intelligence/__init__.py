"""Goal clarification, planning, decision, and capability selection for Autonoesis."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from uuid import UUID, uuid4

from autonoesis_domain import (
    EnvironmentFact,
    GoalContract,
    KnowledgeRef,
    MemoryRecord,
    Plan,
    Task,
)

# ── Clarification ───────────────────────────────────────────────────────────


class ClarificationStatus(StrEnum):
    PENDING = "pending"
    RESOLVED = "resolved"
    BLOCKED = "blocked"


@dataclass(frozen=True, slots=True)
class ClarificationQuestion:
    """A question raised during goal clarification that needs an answer."""

    question_id: UUID = field(default_factory=uuid4)
    question: str = ""
    context: str = ""
    status: ClarificationStatus = ClarificationStatus.PENDING
    answer: str | None = None
    resolved_at: datetime | None = None
    resolved_by: str | None = None


class GoalClarifier:
    """Analyses a GoalContract and identifies ambiguities that need resolution."""

    @staticmethod
    async def clarify(goal: GoalContract) -> tuple[ClarificationQuestion, ...]:
        questions: list[ClarificationQuestion] = []
        if not goal.subject_refs:
            questions.append(
                ClarificationQuestion(
                    question="No subjects specified. Which entities does this goal act on?",
                    context="goal_subjects",
                )
            )
        if not goal.success_criteria:
            questions.append(
                ClarificationQuestion(
                    question="No success criteria defined. How will completion be measured?",
                    context="goal_criteria",
                )
            )
        return tuple(questions)


# ── Planning ────────────────────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class PlanContext:
    """Inputs available to the planner when building a Plan."""

    goal: GoalContract
    environment_facts: tuple[EnvironmentFact, ...] = ()
    knowledge_refs: tuple[KnowledgeRef, ...] = ()
    memory_records: tuple[MemoryRecord, ...] = ()
    available_tools: tuple[str, ...] = ()
    available_skills: tuple[str, ...] = ()


class Planner:
    """Produces a Plan (ordered Tasks with dependencies) from a clarified Goal."""

    @staticmethod
    async def plan(context: PlanContext) -> Plan:
        task = Task(
            tenant_id=context.goal.tenant_id,
            run_id=uuid4(),
            name="execute_goal",
            completion_criterion="all success criteria verified",
            depends_on=(),
        )
        return Plan(
            tenant_id=context.goal.tenant_id,
            goal_id=context.goal.goal_id,
            run_id=task.run_id,
            tasks=(task,),
            version=1,
        )


# ── Decision ────────────────────────────────────────────────────────────────


class DecisionMode(StrEnum):
    AUTO = "auto"
    SUGGEST = "suggest"
    REQUIRE_APPROVAL = "require_approval"


@dataclass(frozen=True, slots=True)
class CapabilityDecision:
    """Which Agent, Skills, and Tools to use for a Task."""

    task_id: UUID
    agent_id: UUID
    agent_version: int
    skill_ids: tuple[str, ...]
    tool_ids: tuple[str, ...]
    model_route: str
    decision_mode: DecisionMode = DecisionMode.AUTO
    rationale: str = ""


class CapabilitySelector:
    """Selects the appropriate Agent, Skills, and Tools for each Task."""

    @staticmethod
    async def select(
        task: Task,
        goal: GoalContract,
        available_agents: tuple[tuple[str, int], ...],
        available_skills: tuple[str, ...],
        available_tools: tuple[str, ...],
    ) -> CapabilityDecision:
        if not available_agents:
            return CapabilityDecision(
                task_id=task.task_id,
                agent_id=uuid4(),
                agent_version=1,
                skill_ids=available_skills,
                tool_ids=available_tools,
                model_route="balanced",
                decision_mode=DecisionMode.AUTO,
                rationale="default - no agents registered",
            )
        agent_name, agent_version = available_agents[0]
        return CapabilityDecision(
            task_id=task.task_id,
            agent_id=uuid4(),
            agent_version=agent_version,
            skill_ids=available_skills,
            tool_ids=available_tools,
            model_route="balanced",
            rationale=f"selected {agent_name}",
        )


__all__ = [
    "CapabilityDecision",
    "CapabilitySelector",
    "ClarificationQuestion",
    "ClarificationStatus",
    "DecisionMode",
    "GoalClarifier",
    "PlanContext",
    "Planner",
]
