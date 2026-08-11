"""Industry-neutral Goal, Subject, Session, and Run aggregates."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from enum import StrEnum
from uuid import UUID, uuid4

from autonoesis_domain.transitions import (
    SYSTEM_ACTOR_ID,
    StateTransition,
    require_transition,
    transition_record,
)
from autonoesis_domain.values import (
    BudgetAmount,
    DataPolicy,
    ExecutionMode,
    JsonObject,
    RiskTier,
)


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
    risk_tier: RiskTier
    budget_limit: BudgetAmount
    deadline: datetime
    input_payload: JsonObject
    delegation_id: UUID | None = None
    data_policy: DataPolicy = field(default_factory=DataPolicy)
    execution_mode: ExecutionMode = ExecutionMode.SUPERVISED
    max_concurrent_runs: int = 1
    goal_id: UUID = field(default_factory=uuid4)
    version: int = 1
    status: GoalStatus = GoalStatus.DRAFT
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    transitions: tuple[StateTransition, ...] = ()

    def __post_init__(self) -> None:
        if any(not item.strip() for item in (self.goal_type, self.statement, self.desired_outcome)):
            raise ValueError("goal type, statement, and desired outcome must not be empty")
        if not self.subject_refs or not self.success_criteria:
            raise ValueError("goal requires subjects and success criteria")
        if not isinstance(self.risk_tier, RiskTier):
            raise ValueError("goal risk tier must be constrained")
        if not isinstance(self.budget_limit, BudgetAmount):
            raise ValueError("goal budget must include a constrained unit")
        if not isinstance(self.input_payload, JsonObject):
            raise ValueError("goal input payload must be canonical JSON")
        if not isinstance(self.data_policy, DataPolicy):
            raise ValueError("goal data policy must be constrained")
        if not isinstance(self.execution_mode, ExecutionMode):
            raise ValueError("goal execution mode must be constrained")
        if self.budget_limit.amount <= 0:
            raise ValueError("goal budget must be positive")
        if self.max_concurrent_runs <= 0:
            raise ValueError("goal concurrent run limit must be positive")
        if self.version < 1:
            raise ValueError("goal version must be positive")
        if self.deadline.tzinfo is None or self.created_at.tzinfo is None:
            raise ValueError("goal timestamps must be timezone-aware")
        if self.deadline <= self.created_at:
            raise ValueError("goal deadline must be after creation")

    def transition_to(
        self,
        target: GoalStatus,
        *,
        actor_id: UUID = SYSTEM_ACTOR_ID,
        reason: str = "system transition",
        occurred_at: datetime | None = None,
    ) -> GoalContract:
        require_transition(self.status, target, _GOAL_TRANSITIONS)
        at = occurred_at or datetime.now(UTC)
        if target is GoalStatus.ACTIVE and at >= self.deadline:
            raise ValueError("expired goal cannot be activated")
        transition = transition_record(
            self.status,
            target,
            actor_id=actor_id,
            reason=reason,
            occurred_at=at,
        )
        return replace(
            self,
            status=target,
            version=self.version + 1,
            transitions=(*self.transitions, transition),
        )

    def assert_run_request_allowed(
        self, active_run_count: int, *, at: datetime | None = None
    ) -> None:
        now = at or datetime.now(UTC)
        if self.status is not GoalStatus.ACTIVE:
            raise ValueError("run requires an active goal")
        if now >= self.deadline:
            raise ValueError("run cannot be requested for an expired goal")
        if active_run_count >= self.max_concurrent_runs:
            raise ValueError("goal concurrent run limit reached")


@dataclass(frozen=True, slots=True)
class Session:
    tenant_id: UUID
    actor_id: UUID
    channel: str
    goal_ids: tuple[UUID, ...] = ()
    session_id: UUID = field(default_factory=uuid4)
    status: SessionStatus = SessionStatus.OPEN
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    def close(self) -> Session:
        if self.status is SessionStatus.CLOSED:
            return self
        return replace(self, status=SessionStatus.CLOSED)


@dataclass(frozen=True, slots=True)
class Run:
    tenant_id: UUID
    goal_id: UUID
    agent_version_id: UUID
    execution_snapshot: RunExecutionSnapshot | None = None
    run_id: UUID = field(default_factory=uuid4)
    status: RunStatus = RunStatus.PENDING
    optimistic_version: int = 1
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    transitions: tuple[StateTransition, ...] = ()

    def __post_init__(self) -> None:
        if self.created_at.tzinfo is None:
            raise ValueError("run creation timestamp must be timezone-aware")
        if self.optimistic_version < 1:
            raise ValueError("run optimistic version must be positive")

    def bind_execution(self, snapshot: RunExecutionSnapshot) -> Run:
        if self.status is not RunStatus.PENDING:
            raise ValueError("execution snapshot can only be bound while run is pending")
        if self.execution_snapshot is not None and self.execution_snapshot != snapshot:
            raise ValueError("run execution snapshot is immutable once bound")
        if snapshot.agent_version_id != self.agent_version_id:
            raise ValueError("run and snapshot agent versions must match")
        return replace(self, execution_snapshot=snapshot)

    def transition_to(
        self,
        target: RunStatus,
        *,
        actor_id: UUID = SYSTEM_ACTOR_ID,
        reason: str = "system transition",
        occurred_at: datetime | None = None,
    ) -> Run:
        require_transition(self.status, target, _RUN_TRANSITIONS)
        if target is RunStatus.RUNNING and self.execution_snapshot is None:
            raise ValueError("run requires a fixed execution snapshot before starting")
        transition = transition_record(
            self.status,
            target,
            actor_id=actor_id,
            reason=reason,
            occurred_at=occurred_at,
        )
        return replace(
            self,
            status=target,
            optimistic_version=self.optimistic_version + 1,
            transitions=(*self.transitions, transition),
        )


@dataclass(frozen=True, slots=True)
class RunExecutionSnapshot:
    plan_id: UUID
    context_snapshot_id: UUID
    agent_version_id: UUID
    skill_versions: tuple[str, ...]
    tool_versions: tuple[str, ...]
    model_route: str
    policy_version: str

    def __post_init__(self) -> None:
        if not self.model_route.strip() or not self.policy_version.strip():
            raise ValueError("run model route and policy version must not be empty")
        for versions, label in (
            (self.skill_versions, "skill"),
            (self.tool_versions, "tool"),
        ):
            if any("@" not in version or not version.strip("@") for version in versions):
                raise ValueError(f"run {label} versions must use immutable name@version references")
            if len(set(versions)) != len(versions):
                raise ValueError(f"run {label} versions must be unique")
