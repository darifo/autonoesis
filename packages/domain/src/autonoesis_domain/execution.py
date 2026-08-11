"""Execution objects that make plans, side effects, and evidence explicit."""

from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from enum import StrEnum
from hashlib import sha256
from uuid import UUID, uuid4

from autonoesis_domain.goals import SubjectRef
from autonoesis_domain.transitions import (
    SYSTEM_ACTOR_ID,
    StateTransition,
    require_transition,
    transition_record,
)
from autonoesis_domain.values import (
    BudgetAmount,
    DataClassification,
    ExecutionMode,
    JsonObject,
)


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


class ActionAttemptStatus(StrEnum):
    STARTED = "started"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
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


class CompensationCapability(StrEnum):
    NONE = "none"
    AVAILABLE = "available"
    REQUIRED = "required"


class EvidenceCaptureMethod(StrEnum):
    AUTHORITATIVE_READBACK = "authoritative_readback"
    SIGNED_EVENT = "signed_event"
    SYSTEM_QUERY = "system_query"
    HUMAN_ATTESTATION = "human_attestation"


class EvidenceIntegrity(StrEnum):
    VERIFIED = "verified"
    UNVERIFIED = "unverified"
    INVALID = "invalid"


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
    preconditions: tuple[str, ...] = ()
    estimated_cost: BudgetAmount = field(default_factory=lambda: BudgetAmount(0))
    risk_level: RiskLevel = RiskLevel.L0_COMPUTE
    compensation: CompensationCapability = CompensationCapability.NONE
    evidence_requirements: tuple[str, ...] = ()
    task_id: UUID = field(default_factory=uuid4)
    status: TaskStatus = TaskStatus.PENDING
    optimistic_version: int = 1
    transitions: tuple[StateTransition, ...] = ()

    def __post_init__(self) -> None:
        if not self.name.strip() or not self.completion_criterion.strip():
            raise ValueError("task name and completion criterion must not be empty")
        if not isinstance(self.estimated_cost, BudgetAmount):
            raise ValueError("task estimated cost must include a constrained unit")
        if self.task_id in self.depends_on:
            raise ValueError("task cannot depend on itself")
        if any(not item.strip() for item in (*self.preconditions, *self.evidence_requirements)):
            raise ValueError("task preconditions and evidence requirements must not be empty")
        if (
            self.risk_level
            in {
                RiskLevel.L2_REVERSIBLE_WRITE,
                RiskLevel.L3_HIGH_IMPACT_WRITE,
                RiskLevel.L4_PRIVILEGED,
            }
            and not self.evidence_requirements
        ):
            raise ValueError("write task requires evidence requirements")
        if self.optimistic_version < 1:
            raise ValueError("task optimistic version must be positive")

    def transition_to(
        self,
        target: TaskStatus,
        *,
        actor_id: UUID = SYSTEM_ACTOR_ID,
        reason: str = "system transition",
        occurred_at: datetime | None = None,
    ) -> "Task":
        require_transition(self.status, target, _TASK_TRANSITIONS)
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
        dependencies = {task.task_id: task.depends_on for task in self.tasks}
        visiting: set[UUID] = set()
        visited: set[UUID] = set()

        def visit(task_id: UUID) -> None:
            if task_id in visiting:
                raise ValueError("plan task graph must not contain a cycle")
            if task_id in visited:
                return
            visiting.add(task_id)
            for dependency in dependencies[task_id]:
                visit(dependency)
            visiting.remove(task_id)
            visited.add(task_id)

        for task_id in task_ids:
            visit(task_id)


@dataclass(frozen=True, slots=True)
class Action:
    """The smallest governed external side-effect boundary."""

    tenant_id: UUID
    run_id: UUID
    task_id: UUID
    tool_name: str
    tool_version: str
    operation: str
    resource_scope: str
    parameters: JsonObject
    risk_level: RiskLevel
    idempotency_key: str
    expected_effect: str
    classification: DataClassification = DataClassification.INTERNAL
    execution_mode: ExecutionMode = ExecutionMode.SUPERVISED
    action_id: UUID = field(default_factory=uuid4)
    status: ActionStatus = ActionStatus.PROPOSED
    optimistic_version: int = 1
    transitions: tuple[StateTransition, ...] = ()

    def __post_init__(self) -> None:
        required = (
            self.tool_name,
            self.tool_version,
            self.operation,
            self.resource_scope,
            self.idempotency_key,
            self.expected_effect,
        )
        if any(not value.strip() for value in required):
            raise ValueError("action identifiers and expected effect must not be empty")
        if not isinstance(self.parameters, JsonObject):
            raise ValueError("action parameters must be canonical JSON")
        if not isinstance(self.risk_level, RiskLevel):
            raise ValueError("action risk must be constrained")
        if not isinstance(self.classification, DataClassification):
            raise ValueError("action classification must be constrained")
        if not isinstance(self.execution_mode, ExecutionMode):
            raise ValueError("action execution mode must be constrained")
        if self.optimistic_version < 1:
            raise ValueError("action optimistic version must be positive")

    def transition_to(
        self,
        target: ActionStatus,
        *,
        actor_id: UUID = SYSTEM_ACTOR_ID,
        reason: str = "system transition",
        occurred_at: datetime | None = None,
    ) -> "Action":
        require_transition(self.status, target, _ACTION_TRANSITIONS)
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

    @property
    def parameter_digest(self) -> str:
        return self.parameters.digest

    @property
    def canonical_digest(self) -> str:
        canonical = "\n".join(
            (
                str(self.tenant_id),
                str(self.run_id),
                str(self.task_id),
                str(self.action_id),
                self.tool_name,
                self.tool_version,
                self.operation,
                self.resource_scope,
                self.parameters.canonical,
                self.risk_level.value,
                self.idempotency_key,
                self.expected_effect,
                self.classification.value,
                self.execution_mode.value,
            )
        )
        return sha256(canonical.encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class ActionAttempt:
    """Immutable execution or reconciliation receipt for one Action invocation."""

    tenant_id: UUID
    run_id: UUID
    action_id: UUID
    invocation_id: UUID
    status: ActionAttemptStatus
    idempotency_key: str
    receipt_ref: str
    executor_identity: str
    failure_reason: str | None = None
    attempt_id: UUID = field(default_factory=uuid4)
    recorded_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    def __post_init__(self) -> None:
        if any(
            not value.strip()
            for value in (self.idempotency_key, self.receipt_ref, self.executor_identity)
        ):
            raise ValueError("action attempt identity, idempotency, and receipt are required")
        if self.recorded_at.tzinfo is None:
            raise ValueError("action attempt timestamp must be timezone-aware")
        if self.status is ActionAttemptStatus.FAILED and not (
            self.failure_reason and self.failure_reason.strip()
        ):
            raise ValueError("failed action attempt requires a failure reason")


@dataclass(frozen=True, slots=True)
class ApprovalRequest:
    tenant_id: UUID
    run_id: UUID
    action_id: UUID
    action_digest: str
    tool_version: str
    operation: str
    resource_scope: str
    argument_digest: str
    policy_version: str
    impact_summary: str
    required_role: str
    expires_at: datetime
    approval_id: UUID = field(default_factory=uuid4)
    status: ApprovalStatus = ApprovalStatus.PENDING
    decided_by: UUID | None = None
    reason: str | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    decided_at: datetime | None = None
    optimistic_version: int = 1
    transitions: tuple[StateTransition, ...] = ()

    def __post_init__(self) -> None:
        if any(
            not item.strip()
            for item in (
                self.action_digest,
                self.tool_version,
                self.operation,
                self.resource_scope,
                self.argument_digest,
                self.policy_version,
                self.impact_summary,
                self.required_role,
            )
        ):
            raise ValueError("approval binding, impact, and role are required")
        if self.expires_at.tzinfo is None or self.created_at.tzinfo is None:
            raise ValueError("approval timestamps must be timezone-aware")
        if self.expires_at <= self.created_at:
            raise ValueError("approval expiry must be after creation")
        for value in (self.action_digest, self.argument_digest):
            if len(value) != 64 or any(char not in "0123456789abcdef" for char in value):
                raise ValueError("approval digests must be lowercase SHA-256 values")
        if self.optimistic_version < 1:
            raise ValueError("approval optimistic version must be positive")

    def decide(self, approver_id: UUID, approved: bool, reason: str) -> "ApprovalRequest":
        if self.status is not ApprovalStatus.PENDING:
            raise ValueError("approval has already been decided")
        if not reason.strip():
            raise ValueError("approval decision requires a reason")
        now = datetime.now(UTC)
        if now >= self.expires_at:
            transition = transition_record(
                self.status,
                ApprovalStatus.EXPIRED,
                actor_id=approver_id,
                reason="approval expired before decision",
                occurred_at=now,
            )
            return replace(
                self,
                status=ApprovalStatus.EXPIRED,
                decided_at=now,
                optimistic_version=self.optimistic_version + 1,
                transitions=(*self.transitions, transition),
            )
        target = ApprovalStatus.APPROVED if approved else ApprovalStatus.REJECTED
        transition = transition_record(
            self.status,
            target,
            actor_id=approver_id,
            reason=reason,
            occurred_at=now,
        )
        return replace(
            self,
            status=target,
            decided_by=approver_id,
            reason=reason,
            decided_at=now,
            optimistic_version=self.optimistic_version + 1,
            transitions=(*self.transitions, transition),
        )

    def authorizes(
        self, action: Action, policy_version: str, *, at: datetime | None = None
    ) -> bool:
        now = at or datetime.now(UTC)
        return (
            self.status is ApprovalStatus.APPROVED
            and now < self.expires_at
            and self.tenant_id == action.tenant_id
            and self.run_id == action.run_id
            and self.action_id == action.action_id
            and self.action_digest == action.canonical_digest
            and self.tool_version == action.tool_version
            and self.operation == action.operation
            and self.resource_scope == action.resource_scope
            and self.argument_digest == action.parameter_digest
            and self.policy_version == policy_version
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
    source_identity: str
    capture_method: EvidenceCaptureMethod
    reference: str
    observed_state: str
    content_digest: str
    classification: DataClassification
    valid_from: datetime
    valid_until: datetime
    integrity: EvidenceIntegrity
    source_reference: str = ""
    subject_refs: tuple[SubjectRef, ...] = ()
    retained_until: datetime | None = None
    artifact_version_id: str | None = None
    evidence_id: UUID = field(default_factory=uuid4)
    captured_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    def __post_init__(self) -> None:
        if any(
            not value.strip()
            for value in (self.source, self.source_identity, self.reference, self.observed_state)
        ):
            raise ValueError("evidence source, identity, reference, and state must not be empty")
        if len(self.content_digest) != 64 or any(
            char not in "0123456789abcdef" for char in self.content_digest
        ):
            raise ValueError("evidence content digest must be a lowercase SHA-256 value")
        if any(
            timestamp.tzinfo is None
            for timestamp in (self.captured_at, self.valid_from, self.valid_until)
        ):
            raise ValueError("evidence timestamps must be timezone-aware")
        if self.valid_from > self.captured_at or self.valid_until < self.captured_at:
            raise ValueError("evidence capture must fall within its validity interval")
        if self.source_reference and not self.source_reference.strip():
            raise ValueError("evidence source reference must not be blank")
        if len(set(self.subject_refs)) != len(self.subject_refs):
            raise ValueError("evidence subject references must be unique")
        if self.retained_until is not None:
            if self.retained_until.tzinfo is None:
                raise ValueError("evidence retention timestamp must be timezone-aware")
            if self.retained_until < self.captured_at:
                raise ValueError("evidence retention cannot end before capture")


@dataclass(frozen=True, slots=True)
class Outcome:
    tenant_id: UUID
    goal_id: UUID
    run_id: UUID
    criterion_id: str
    verifier_version: str
    status: OutcomeStatus
    evidence: tuple[Evidence, ...]
    outcome_id: UUID = field(default_factory=uuid4)
    verified_at: datetime | None = None

    def __post_init__(self) -> None:
        if not self.criterion_id.strip() or not self.verifier_version.strip():
            raise ValueError("outcome criterion id and verifier version must not be empty")
        evidence_ids = self.evidence_ids
        if len(set(evidence_ids)) != len(evidence_ids):
            raise ValueError("outcome evidence ids must be unique")
        if self.status is OutcomeStatus.VERIFIED and not self.evidence:
            raise ValueError("verified outcome requires evidence")
        if self.status is OutcomeStatus.VERIFIED and self.verified_at is None:
            raise ValueError("verified outcome requires a verification timestamp")
        if self.verified_at is not None and self.verified_at.tzinfo is None:
            raise ValueError("outcome verification timestamp must be timezone-aware")
        if self.status is OutcomeStatus.VERIFIED:
            assert self.verified_at is not None
            for item in self.evidence:
                if item.tenant_id != self.tenant_id or item.run_id != self.run_id:
                    raise ValueError("outcome evidence must share tenant and run")
                if item.integrity is not EvidenceIntegrity.VERIFIED:
                    raise ValueError("verified outcome requires integrity-verified evidence")
                if not item.valid_from <= self.verified_at <= item.valid_until:
                    raise ValueError("verified outcome requires currently valid evidence")

    @property
    def evidence_ids(self) -> tuple[UUID, ...]:
        return tuple(item.evidence_id for item in self.evidence)


@dataclass(frozen=True, slots=True)
class ActionExecutionEnvelope:
    invocation_id: UUID
    tenant_id: UUID
    run_id: UUID
    task_id: UUID
    action_id: UUID
    actor_id: UUID
    principal_id: UUID
    agent_identity: str
    delegation_ref: str
    tool_name: str
    tool_version: str
    operation: str
    resource_scope: str
    arguments: JsonObject
    action_digest: str
    risk_level: RiskLevel
    idempotency_key: str
    budget_ref: str
    approval_id: UUID | None
    policy_version: str
    expected_effect: str
    deadline: datetime
    traceparent: str
    classification: DataClassification
    execution_mode: ExecutionMode

    def __post_init__(self) -> None:
        strings = (
            self.agent_identity,
            self.delegation_ref,
            self.tool_name,
            self.tool_version,
            self.operation,
            self.resource_scope,
            self.idempotency_key,
            self.budget_ref,
            self.policy_version,
            self.expected_effect,
            self.traceparent,
        )
        if any(not value.strip() for value in strings):
            raise ValueError("execution envelope identifiers must not be empty")
        if self.deadline.tzinfo is None:
            raise ValueError("execution envelope deadline must be timezone-aware")
        if len(self.action_digest) != 64 or any(
            char not in "0123456789abcdef" for char in self.action_digest
        ):
            raise ValueError("execution envelope action digest must be SHA-256")
        canonical = "\n".join(
            (
                str(self.tenant_id),
                str(self.run_id),
                str(self.task_id),
                str(self.action_id),
                self.tool_name,
                self.tool_version,
                self.operation,
                self.resource_scope,
                self.arguments.canonical,
                self.risk_level.value,
                self.idempotency_key,
                self.expected_effect,
                self.classification.value,
                self.execution_mode.value,
            )
        )
        if sha256(canonical.encode("utf-8")).hexdigest() != self.action_digest:
            raise ValueError("execution envelope digest does not match executable fields")

    @classmethod
    def from_action(
        cls,
        action: Action,
        *,
        actor_id: UUID,
        principal_id: UUID,
        agent_identity: str,
        delegation_ref: str,
        budget_ref: str,
        approval_id: UUID | None,
        policy_version: str,
        deadline: datetime,
        traceparent: str,
    ) -> "ActionExecutionEnvelope":
        return cls(
            invocation_id=uuid4(),
            tenant_id=action.tenant_id,
            run_id=action.run_id,
            task_id=action.task_id,
            action_id=action.action_id,
            actor_id=actor_id,
            principal_id=principal_id,
            agent_identity=agent_identity,
            delegation_ref=delegation_ref,
            tool_name=action.tool_name,
            tool_version=action.tool_version,
            operation=action.operation,
            resource_scope=action.resource_scope,
            arguments=action.parameters,
            action_digest=action.canonical_digest,
            risk_level=action.risk_level,
            idempotency_key=action.idempotency_key,
            budget_ref=budget_ref,
            approval_id=approval_id,
            policy_version=policy_version,
            expected_effect=action.expected_effect,
            deadline=deadline,
            traceparent=traceparent,
            classification=action.classification,
            execution_mode=action.execution_mode,
        )
