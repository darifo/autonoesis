"""Bootstrap Goal and Run aggregates."""

from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from enum import StrEnum
from uuid import UUID, uuid4

from autonoesis_domain.transitions import require_transition


class GoalStatus(StrEnum):
    DRAFT = "draft"
    ACTIVE = "active"
    SATISFIED = "satisfied"
    CANCELLED = "cancelled"


class RunStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    BLOCKED = "blocked"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"


_GOAL_TRANSITIONS: dict[GoalStatus, frozenset[GoalStatus]] = {
    GoalStatus.DRAFT: frozenset({GoalStatus.ACTIVE, GoalStatus.CANCELLED}),
    GoalStatus.ACTIVE: frozenset({GoalStatus.SATISFIED, GoalStatus.CANCELLED}),
}

_RUN_TRANSITIONS: dict[RunStatus, frozenset[RunStatus]] = {
    RunStatus.PENDING: frozenset({RunStatus.RUNNING, RunStatus.CANCELLED}),
    RunStatus.RUNNING: frozenset(
        {RunStatus.BLOCKED, RunStatus.SUCCEEDED, RunStatus.FAILED, RunStatus.CANCELLED}
    ),
    RunStatus.BLOCKED: frozenset({RunStatus.RUNNING, RunStatus.FAILED, RunStatus.CANCELLED}),
}


@dataclass(frozen=True, slots=True)
class Goal:
    tenant_id: UUID
    statement: str
    success_criteria: tuple[str, ...]
    goal_id: UUID = field(default_factory=uuid4)
    status: GoalStatus = GoalStatus.DRAFT
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    def __post_init__(self) -> None:
        if not self.statement.strip():
            raise ValueError("goal statement must not be empty")
        if not self.success_criteria:
            raise ValueError("goal must define at least one success criterion")

    def transition_to(self, target: GoalStatus) -> "Goal":
        require_transition(self.status, target, _GOAL_TRANSITIONS)
        return replace(self, status=target)


@dataclass(frozen=True, slots=True)
class Run:
    tenant_id: UUID
    goal_id: UUID
    run_id: UUID = field(default_factory=uuid4)
    status: RunStatus = RunStatus.PENDING
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    def transition_to(self, target: RunStatus) -> "Run":
        require_transition(self.status, target, _RUN_TRANSITIONS)
        return replace(self, status=target)
