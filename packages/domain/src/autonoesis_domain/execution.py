"""Execution objects that make plans, side effects, and evidence explicit."""

from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from enum import StrEnum
from hashlib import sha256
from uuid import UUID, uuid4

from autonoesis_domain.transitions import require_transition


class TaskStatus(StrEnum):
    PENDING = "pending"
    READY = "ready"
    RUNNING = "running"
    BLOCKED = "blocked"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class RiskLevel(StrEnum):
    L0_COMPUTE = "l0_compute"
    L1_READ = "l1_read"
    L2_REVERSIBLE_WRITE = "l2_reversible_write"
    L3_HIGH_IMPACT_WRITE = "l3_high_impact_write"
    L4_PRIVILEGED = "l4_privileged"


class ActionStatus(StrEnum):
    PROPOSED = "proposed"
    AWAITING_APPROVAL = "awaiting_approval"
    AUTHORIZED = "authorized"
    EXECUTING = "executing"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    DENIED = "denied"
    UNKNOWN = "unknown"


class DecisionKind(StrEnum):
    EXECUTE = "execute"
    APPROVE = "approve"
    REJECT = "reject"
    ESCALATE = "escalate"
    REPLAN = "replan"


class OutcomeStatus(StrEnum):
    VERIFIED = "verified"
    NOT_MET = "not_met"
    UNKNOWN = "unknown"


class ApprovalStatus(StrEnum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    EXPIRED = "expired"


_TASK_TRANSITIONS: dict[TaskStatus, frozenset[TaskStatus]] = {
    TaskStatus.PENDING: frozenset({TaskStatus.READY, TaskStatus.BLOCKED}),
    TaskStatus.READY: frozenset({TaskStatus.RUNNING, TaskStatus.BLOCKED}),
    TaskStatus.RUNNING: frozenset({TaskStatus.BLOCKED, TaskStatus.SUCCEEDED, TaskStatus.FAILED}),
    TaskStatus.BLOCKED: frozenset({TaskStatus.READY, TaskStatus.FAILED}),
}

_ACTION_TRANSITIONS: dict[ActionStatus, frozenset[ActionStatus]] = {
    ActionStatus.PROPOSED: frozenset(
        {ActionStatus.AWAITING_APPROVAL, ActionStatus.AUTHORIZED, ActionStatus.DENIED}
    ),
    ActionStatus.AWAITING_APPROVAL: frozenset({ActionStatus.AUTHORIZED, ActionStatus.DENIED}),
    ActionStatus.AUTHORIZED: frozenset({ActionStatus.EXECUTING}),
    ActionStatus.EXECUTING: frozenset(
        {ActionStatus.SUCCEEDED, ActionStatus.FAILED, ActionStatus.UNKNOWN}
    ),
    ActionStatus.UNKNOWN: frozenset({ActionStatus.SUCCEEDED, ActionStatus.FAILED}),
}


@dataclass(frozen=True, slots=True)
class Task:
    tenant_id: UUID
    run_id: UUID
    name: str
    completion_criterion: str
    depends_on: tuple[UUID, ...] = ()
    task_id: UUID = field(default_factory=uuid4)
    status: TaskStatus = TaskStatus.PENDING

    def __post_init__(self) -> None:
        if not self.name.strip() or not self.completion_criterion.strip():
            raise ValueError("task name and completion criterion must not be empty")
        if self.task_id in self.depends_on:
            raise ValueError("task cannot depend on itself")

    def transition_to(self, target: TaskStatus) -> "Task":
        require_transition(self.status, target, _TASK_TRANSITIONS)
        return replace(self, status=target)


@dataclass(frozen=True, slots=True)
class Plan:
    tenant_id: UUID
    goal_id: UUID
    run_id: UUID
    tasks: tuple[Task, ...]
    version: int = 1
    plan_id: UUID = field(default_factory=uuid4)

    def __post_init__(self) -> None:
        if self.version < 1:
            raise ValueError("plan version must be positive")
        if not self.tasks:
            raise ValueError("plan must contain at least one task")
        task_ids = {task.task_id for task in self.tasks}
        if len(task_ids) != len(self.tasks):
            raise ValueError("plan task ids must be unique")
        for task in self.tasks:
            if task.tenant_id != self.tenant_id or task.run_id != self.run_id:
                raise ValueError("plan tasks must share tenant_id and run_id")
            if not set(task.depends_on).issubset(task_ids):
                raise ValueError("task dependency must exist in the same plan")


@dataclass(frozen=True, slots=True)
class Action:
    """The smallest governed external side-effect boundary."""

    tenant_id: UUID
    run_id: UUID
    task_id: UUID
    tool_name: str
    operation: str
    resource_id: str
    parameters: tuple[tuple[str, str], ...]
    risk_level: RiskLevel
    idempotency_key: str
    expected_effect: str
    action_id: UUID = field(default_factory=uuid4)
    status: ActionStatus = ActionStatus.PROPOSED

    def __post_init__(self) -> None:
        required = (
            self.tool_name,
            self.operation,
            self.resource_id,
            self.idempotency_key,
            self.expected_effect,
        )
        if any(not value.strip() for value in required):
            raise ValueError("action identifiers and expected effect must not be empty")
        if len(dict(self.parameters)) != len(self.parameters):
            raise ValueError("action parameter names must be unique")

    def transition_to(self, target: ActionStatus) -> "Action":
        require_transition(self.status, target, _ACTION_TRANSITIONS)
        return replace(self, status=target)

    @property
    def parameter_digest(self) -> str:
        canonical = "\n".join(f"{key}={value}" for key, value in sorted(self.parameters))
        return sha256(canonical.encode()).hexdigest()


@dataclass(frozen=True, slots=True)
class ApprovalRequest:
    tenant_id: UUID
    run_id: UUID
    action_id: UUID
    action_digest: str
    impact_summary: str
    required_role: str
    expires_at: datetime
    approval_id: UUID = field(default_factory=uuid4)
    status: ApprovalStatus = ApprovalStatus.PENDING
    decided_by: UUID | None = None
    reason: str | None = None

    def __post_init__(self) -> None:
        if any(
            not item.strip()
            for item in (self.action_digest, self.impact_summary, self.required_role)
        ):
            raise ValueError("approval action digest, impact, and role are required")
        if self.expires_at.tzinfo is None:
            raise ValueError("approval expiry must be timezone-aware")

    def decide(self, approver_id: UUID, approved: bool, reason: str) -> "ApprovalRequest":
        if self.status is not ApprovalStatus.PENDING:
            raise ValueError("approval has already been decided")
        if not reason.strip():
            raise ValueError("approval decision requires a reason")
        if datetime.now(UTC) >= self.expires_at:
            return replace(self, status=ApprovalStatus.EXPIRED)
        return replace(
            self,
            status=ApprovalStatus.APPROVED if approved else ApprovalStatus.REJECTED,
            decided_by=approver_id,
            reason=reason,
        )


@dataclass(frozen=True, slots=True)
class DecisionRecord:
    tenant_id: UUID
    run_id: UUID
    action_id: UUID
    decision: DecisionKind
    rationale: str
    policy_version: str
    actor_id: UUID
    principal_id: UUID
    agent_id: str
    fact_references: tuple[str, ...]
    decision_id: UUID = field(default_factory=uuid4)
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    def __post_init__(self) -> None:
        if not self.rationale.strip() or not self.policy_version.strip():
            raise ValueError("decision rationale and policy version must not be empty")
        if not self.agent_id.strip():
            raise ValueError("agent_id must not be empty")
        if self.created_at.tzinfo is None:
            raise ValueError("created_at must be timezone-aware")


@dataclass(frozen=True, slots=True)
class Evidence:
    tenant_id: UUID
    run_id: UUID
    action_id: UUID
    source: str
    reference: str
    observed_state: str
    evidence_id: UUID = field(default_factory=uuid4)
    captured_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    def __post_init__(self) -> None:
        if any(not value.strip() for value in (self.source, self.reference, self.observed_state)):
            raise ValueError("evidence source, reference, and observed state must not be empty")
        if self.captured_at.tzinfo is None:
            raise ValueError("captured_at must be timezone-aware")


@dataclass(frozen=True, slots=True)
class Outcome:
    tenant_id: UUID
    goal_id: UUID
    run_id: UUID
    criterion: str
    status: OutcomeStatus
    evidence_ids: tuple[UUID, ...]
    outcome_id: UUID = field(default_factory=uuid4)

    def __post_init__(self) -> None:
        if not self.criterion.strip():
            raise ValueError("outcome criterion must not be empty")
        if self.status is OutcomeStatus.VERIFIED and not self.evidence_ids:
            raise ValueError("verified outcome requires evidence")
