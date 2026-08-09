"""Industry-neutral Goal, Subject, Session, and Run aggregates."""

from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any
from uuid import UUID, uuid4

from autonoesis_domain.transitions import require_transition


class GoalStatus(StrEnum):
    DRAFT = "draft"
    ACTIVE = "active"
    PAUSED = "paused"
    SATISFIED = "satisfied"
    FAILED = "failed"
    CANCELLED = "cancelled"


class SessionStatus(StrEnum):
    OPEN = "open"
    CLOSED = "closed"


class RunStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    BLOCKED = "blocked"
    AWAITING_EVIDENCE = "awaiting_evidence"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"


_GOAL_TRANSITIONS: dict[GoalStatus, frozenset[GoalStatus]] = {
    GoalStatus.DRAFT: frozenset({GoalStatus.ACTIVE, GoalStatus.CANCELLED}),
    GoalStatus.ACTIVE: frozenset(
        {GoalStatus.PAUSED, GoalStatus.SATISFIED, GoalStatus.FAILED, GoalStatus.CANCELLED}
    ),
    GoalStatus.PAUSED: frozenset({GoalStatus.ACTIVE, GoalStatus.FAILED, GoalStatus.CANCELLED}),
}

_RUN_TRANSITIONS: dict[RunStatus, frozenset[RunStatus]] = {
    RunStatus.PENDING: frozenset({RunStatus.RUNNING, RunStatus.CANCELLED}),
    RunStatus.RUNNING: frozenset(
        {
            RunStatus.BLOCKED,
            RunStatus.AWAITING_EVIDENCE,
            RunStatus.SUCCEEDED,
            RunStatus.FAILED,
            RunStatus.CANCELLED,
        }
    ),
    RunStatus.BLOCKED: frozenset({RunStatus.RUNNING, RunStatus.FAILED, RunStatus.CANCELLED}),
    RunStatus.AWAITING_EVIDENCE: frozenset(
        {RunStatus.SUCCEEDED, RunStatus.FAILED, RunStatus.CANCELLED}
    ),
}


@dataclass(frozen=True, slots=True)
class SubjectRef:
    """Reference to a business object owned by an external authoritative system."""

    system: str
    subject_type: str
    subject_id: str
    version: str | None = None

    def __post_init__(self) -> None:
        if any(not item.strip() for item in (self.system, self.subject_type, self.subject_id)):
            raise ValueError("subject system, type, and id must not be empty")


@dataclass(frozen=True, slots=True)
class SuccessCriterion:
    criterion_id: str
    description: str
    evidence_type: str

    def __post_init__(self) -> None:
        if any(
            not item.strip() for item in (self.criterion_id, self.description, self.evidence_type)
        ):
            raise ValueError("success criterion fields must not be empty")


@dataclass(frozen=True, slots=True)
class GoalContract:
    tenant_id: UUID
    goal_type: str
    statement: str
    desired_outcome: str
    subject_refs: tuple[SubjectRef, ...]
    success_criteria: tuple[SuccessCriterion, ...]
    constraints: tuple[str, ...]
    owner_id: UUID
    risk_tier: str
    budget_limit: int
    deadline: datetime
    input_payload: dict[str, Any]
    goal_id: UUID = field(default_factory=uuid4)
    version: int = 1
    status: GoalStatus = GoalStatus.DRAFT
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    def __post_init__(self) -> None:
        if any(not item.strip() for item in (self.goal_type, self.statement, self.desired_outcome)):
            raise ValueError("goal type, statement, and desired outcome must not be empty")
        if not self.subject_refs or not self.success_criteria:
            raise ValueError("goal requires subjects and success criteria")
        if self.budget_limit <= 0:
            raise ValueError("goal budget must be positive")
        if self.version < 1:
            raise ValueError("goal version must be positive")
        if self.deadline.tzinfo is None or self.created_at.tzinfo is None:
            raise ValueError("goal timestamps must be timezone-aware")

    def transition_to(self, target: GoalStatus) -> "GoalContract":
        require_transition(self.status, target, _GOAL_TRANSITIONS)
        return replace(self, status=target)


@dataclass(frozen=True, slots=True)
class Session:
    tenant_id: UUID
    actor_id: UUID
    channel: str
    goal_ids: tuple[UUID, ...] = ()
    session_id: UUID = field(default_factory=uuid4)
    status: SessionStatus = SessionStatus.OPEN
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    def close(self) -> "Session":
        if self.status is SessionStatus.CLOSED:
            return self
        return replace(self, status=SessionStatus.CLOSED)


@dataclass(frozen=True, slots=True)
class Run:
    tenant_id: UUID
    goal_id: UUID
    agent_version_id: UUID
    run_id: UUID = field(default_factory=uuid4)
    status: RunStatus = RunStatus.PENDING
    optimistic_version: int = 1
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    def transition_to(self, target: RunStatus) -> "Run":
        require_transition(self.status, target, _RUN_TRANSITIONS)
        return replace(self, status=target, optimistic_version=self.optimistic_version + 1)
