"""Vertical Application use cases for governed Goal execution."""

import json
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from typing import Any
from uuid import NAMESPACE_URL, UUID, uuid4, uuid5

from autonoesis_capability import validate_payload
from autonoesis_domain import (
    Action,
    ActionAttempt,
    ActionAttemptStatus,
    ActionExecutionEnvelope,
    ActionStatus,
    ApprovalRequest,
    ApprovalStatus,
    BudgetAmount,
    CompensationCapability,
    ContextSnapshot,
    DataClassification,
    DataPolicy,
    EnvironmentFact,
    Evidence,
    EvidenceCaptureMethod,
    EvidenceIntegrity,
    ExecutionMode,
    GoalContract,
    GoalStatus,
    JsonObject,
    KnowledgeRef,
    Outcome,
    OutcomeStatus,
    Plan,
    RiskLevel,
    Run,
    RunExecutionSnapshot,
    RunStatus,
    SubjectRef,
    Task,
    TaskStatus,
)
from autonoesis_runtime import (
    AuthorizationContext,
    GatewayResult,
    GovernedToolGateway,
    ToolReceipt,
    ToolResultStatus,
)

from autonoesis_application.platform import (
    AuditEvent,
    CapabilityCatalog,
    ConcurrencyConflict,
    CreateGoal,
    IdentityContext,
)
from autonoesis_application.repositories import ApplicationRepository
from autonoesis_application.verification import (
    AuthoritativeReadback,
    EvidenceAdmissionPolicy,
    EvidenceArtifactDescriptor,
    EvidenceArtifactStore,
    EvidenceCaptureSaga,
    EvidenceDeletionRecord,
    EvidenceDeletionStatus,
    TrustedOutcomeVerifier,
)


@dataclass(frozen=True, slots=True)
class CommandContext:
    identity: IdentityContext
    correlation_id: UUID
    causation_id: UUID
    idempotency_key: str
    request_digest: str

    def __post_init__(self) -> None:
        if not self.idempotency_key.strip() or len(self.idempotency_key) > 300:
            raise ValueError("command idempotency key must be non-empty and bounded")
        if len(self.request_digest) != 64 or any(
            char not in "0123456789abcdef" for char in self.request_digest
        ):
            raise ValueError("command request digest must be lowercase SHA-256")


@dataclass(frozen=True, slots=True)
class ActivateGoal:
    goal_id: UUID
    reason: str = "goal activated"


@dataclass(frozen=True, slots=True)
class RequestRun:
    goal_id: UUID


@dataclass(frozen=True, slots=True)
class PrepareRunContext:
    run_id: UUID
    environment_facts: tuple[EnvironmentFact, ...]
    knowledge_refs: tuple[KnowledgeRef, ...]
    memory_ids: tuple[UUID, ...]
    history_digest: str
    tool_versions: tuple[str, ...]
    conflicts: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class TaskDefinition:
    name: str
    completion_criterion: str
    depends_on: tuple[UUID, ...] = ()
    preconditions: tuple[str, ...] = ()
    estimated_cost: BudgetAmount = field(default_factory=lambda: BudgetAmount(0))
    risk_level: RiskLevel = RiskLevel.L0_COMPUTE
    compensation: CompensationCapability = CompensationCapability.NONE
    evidence_requirements: tuple[str, ...] = ()
    task_id: UUID | None = None


@dataclass(frozen=True, slots=True)
class CreateValidatedPlan:
    run_id: UUID
    tasks: tuple[TaskDefinition, ...]
    skill_versions: tuple[str, ...]
    tool_versions: tuple[str, ...]
    model_route: str
    policy_version: str


@dataclass(frozen=True, slots=True)
class StartTask:
    task_id: UUID


@dataclass(frozen=True, slots=True)
class CompleteTask:
    task_id: UUID
    succeeded: bool
    reason: str


@dataclass(frozen=True, slots=True)
class ProposeAction:
    task_id: UUID
    tool_name: str
    tool_version: str
    operation: str
    resource_scope: str
    parameters: dict[str, Any]
    risk_level: RiskLevel
    expected_effect: str
    classification: DataClassification = DataClassification.INTERNAL
    execution_mode: ExecutionMode = ExecutionMode.SUPERVISED


@dataclass(frozen=True, slots=True)
class RequestApproval:
    action_id: UUID
    policy_version: str
    impact_summary: str
    required_role: str
    expires_at: datetime


@dataclass(frozen=True, slots=True)
class DecideApproval:
    approval_id: UUID
    action_digest: str
    approved: bool
    reason: str


@dataclass(frozen=True, slots=True)
class AuthorizeActionAtExecutionTime:
    action_id: UUID
    policy_version: str
    policy_allowed: bool
    policy_reason: str
    approval_id: UUID | None
    agent_identity: str
    delegation_ref: str
    budget_ref: str
    deadline: datetime
    traceparent: str


@dataclass(frozen=True, slots=True)
class ExecuteGovernedAction:
    action_id: UUID
    approval_id: UUID | None
    policy_version: str
    delegation_id: str | None
    cost_units: int


@dataclass(frozen=True, slots=True)
class GovernedActionExecution:
    result: GatewayResult
    attempt: ActionAttempt
    evidence: Evidence


@dataclass(frozen=True, slots=True)
class RecordActionAttempt:
    action_id: UUID
    invocation_id: UUID
    status: ActionAttemptStatus
    receipt_ref: str
    executor_identity: str
    failure_reason: str | None = None


@dataclass(frozen=True, slots=True)
class RecordEvidence:
    evidence: Evidence


@dataclass(frozen=True, slots=True)
class CaptureAuthoritativeEvidence:
    run_id: UUID
    action_id: UUID
    criterion_id: str
    source: str
    declared_classification: DataClassification = DataClassification.INTERNAL
    content_type: str = "application/json"


@dataclass(frozen=True, slots=True)
class RequestEvidenceDeletion:
    evidence_id: UUID
    reason: str


@dataclass(frozen=True, slots=True)
class ReconcileUnknownAction:
    action_id: UUID
    invocation_id: UUID
    succeeded: bool
    receipt_ref: str
    executor_identity: str
    failure_reason: str | None = None


@dataclass(frozen=True, slots=True)
class VerifyOutcome:
    run_id: UUID
    criterion_id: str
    evidence_ids: tuple[UUID, ...]


@dataclass(frozen=True, slots=True)
class CompleteRun:
    run_id: UUID


@dataclass(frozen=True, slots=True)
class SatisfyOrFailGoal:
    goal_id: UUID
    satisfied: bool
    reason: str


@dataclass(frozen=True, slots=True)
class CancelRun:
    run_id: UUID
    reason: str


@dataclass(frozen=True, slots=True)
class FailRun:
    run_id: UUID
    reason: str


@dataclass(frozen=True, slots=True)
class TakeOverRun:
    run_id: UUID
    reason: str


class GoalExecutionApplication:
    """Own authorization, idempotency, transactions, and execution state advancement."""

    _OPERATORS = frozenset({"platform_admin", "tenant_admin", "operator", "worker"})

    def __init__(
        self,
        repository: ApplicationRepository,
        catalog: CapabilityCatalog,
        *,
        governed_gateway: GovernedToolGateway | None = None,
        legacy_authorization_enabled: bool = False,
        evidence_artifacts: EvidenceArtifactStore | None = None,
        authoritative_readback: AuthoritativeReadback | None = None,
        evidence_policy: EvidenceAdmissionPolicy | None = None,
    ) -> None:
        self._repository = repository
        self._catalog = catalog
        self._governed_gateway = governed_gateway
        self._legacy_authorization_enabled = legacy_authorization_enabled
        self._evidence_artifacts = evidence_artifacts
        self._authoritative_readback = authoritative_readback
        self._evidence_policy = evidence_policy or EvidenceAdmissionPolicy()
        self._outcome_verifier = (
            TrustedOutcomeVerifier(authoritative_readback, evidence_artifacts)
            if authoritative_readback is not None and evidence_artifacts is not None
            else None
        )

    async def create_goal(self, context: CommandContext, command: CreateGoal) -> GoalContract:
        self._require_any(context, self._OPERATORS)
        key = self._key("create_goal", context)
        async with self._repository.transaction():
            if cached := await self._load_idempotency(context, key):
                return await self._repository.get_goal(context.identity.tenant_id, cached)
            goal_type = await self._catalog.get_goal_type(
                context.identity.tenant_id, command.goal_type
            )
            validate_payload(goal_type, command.input_payload)
            goal = GoalContract(
                tenant_id=context.identity.tenant_id,
                goal_type=command.goal_type,
                statement=command.statement,
                desired_outcome=command.desired_outcome,
                subject_refs=command.subject_refs,
                success_criteria=command.success_criteria,
                constraints=command.constraints,
                owner_id=command.owner_id,
                risk_tier=command.risk_tier,
                budget_limit=BudgetAmount(
                    command.budget_limit or goal_type.default_budget, command.budget_unit
                ),
                deadline=command.deadline,
                input_payload=JsonObject.from_value(command.input_payload),
                delegation_id=command.delegation_id,
                data_policy=DataPolicy(
                    maximum_classification=command.maximum_classification,
                    allowed_regions=command.allowed_regions,
                    retention_days=command.retention_days,
                ),
                execution_mode=command.execution_mode,
                max_concurrent_runs=command.max_concurrent_runs,
            )
            await self._repository.add_goal(goal, self._audit(context, "goal.created", goal))
            await self._remember(context, key, goal.goal_id)
            return goal

    async def activate_goal(self, context: CommandContext, command: ActivateGoal) -> GoalContract:
        self._require_any(context, self._OPERATORS)
        key = self._key("activate_goal", context)
        async with self._repository.transaction():
            goal = await self._cached_goal(context, key, command.goal_id)
            if goal.status is GoalStatus.ACTIVE:
                await self._remember(context, key, goal.goal_id)
                return goal
            active = goal.transition_to(
                GoalStatus.ACTIVE,
                actor_id=context.identity.actor_id,
                reason=command.reason,
            )
            await self._repository.save_goal(
                active, goal.version, self._audit(context, "goal.activated", active)
            )
            await self._remember(context, key, active.goal_id)
            return active

    async def request_run(self, context: CommandContext, command: RequestRun) -> Run:
        self._require_any(context, self._OPERATORS)
        key = self._key("request_run", context)
        async with self._repository.transaction():
            cached = await self._load_idempotency(context, key)
            if cached is not None:
                return await self._repository.get_run(context.identity.tenant_id, cached)
            goal = await self._repository.get_goal(context.identity.tenant_id, command.goal_id)
            runs = await self._repository.list_runs(context.identity.tenant_id, goal.goal_id)
            goal.assert_run_request_allowed(sum(self._run_is_active(run) for run in runs))
            goal_type = await self._catalog.get_goal_type(
                context.identity.tenant_id, goal.goal_type
            )
            agent = await self._catalog.get_stable_agent(
                context.identity.tenant_id, goal_type.agent
            )
            run = Run(context.identity.tenant_id, goal.goal_id, agent.agent_version_id)
            await self._repository.add_run(run, self._audit(context, "run.requested", run))
            await self._remember(context, key, run.run_id)
            return run

    async def prepare_run_context(
        self, context: CommandContext, command: PrepareRunContext
    ) -> ContextSnapshot:
        self._require_any(context, self._OPERATORS)
        key = self._key("prepare_run_context", context)
        async with self._repository.transaction():
            cached = await self._load_idempotency(context, key)
            if cached is not None:
                return await self._repository.get_context_snapshot(
                    context.identity.tenant_id, command.run_id
                )
            run = await self._repository.get_run(context.identity.tenant_id, command.run_id)
            snapshot = ContextSnapshot(
                tenant_id=context.identity.tenant_id,
                goal_id=run.goal_id,
                run_id=run.run_id,
                environment_facts=command.environment_facts,
                knowledge_refs=command.knowledge_refs,
                memory_ids=command.memory_ids,
                history_digest=command.history_digest,
                tool_versions=command.tool_versions,
                conflicts=command.conflicts,
            )
            await self._repository.add_context_snapshot(snapshot)
            await self._repository.record_audit(
                self._audit(context, "run.context_prepared", snapshot)
            )
            await self._remember(context, key, snapshot.snapshot_id)
            return snapshot

    async def create_validated_plan(
        self, context: CommandContext, command: CreateValidatedPlan
    ) -> Plan:
        self._require_any(context, self._OPERATORS)
        key = self._key("create_validated_plan", context)
        async with self._repository.transaction():
            cached = await self._load_idempotency(context, key)
            if cached is not None:
                return await self._repository.get_plan(context.identity.tenant_id, cached)
            run = await self._repository.get_run(context.identity.tenant_id, command.run_id)
            if run.status is not RunStatus.PENDING:
                raise ValueError("a Plan can only be created for a pending Run")
            snapshot = await self._repository.get_context_snapshot(
                context.identity.tenant_id, run.run_id
            )
            tasks = tuple(
                self._build_task(context.identity.tenant_id, run.run_id, item)
                for item in command.tasks
            )
            plan = Plan(context.identity.tenant_id, run.goal_id, run.run_id, tasks)
            bound = run.bind_execution(
                RunExecutionSnapshot(
                    plan.plan_id,
                    snapshot.snapshot_id,
                    run.agent_version_id,
                    command.skill_versions,
                    command.tool_versions,
                    command.model_route,
                    command.policy_version,
                )
            ).transition_to(
                RunStatus.RUNNING,
                actor_id=context.identity.actor_id,
                reason="validated Plan and immutable execution snapshot bound",
            )
            await self._repository.add_plan(plan)
            await self._repository.save_run(
                bound, run.optimistic_version, self._audit(context, "run.started", bound)
            )
            await self._remember(context, key, plan.plan_id)
            return plan

    async def start_task(self, context: CommandContext, command: StartTask) -> Task:
        self._require_any(context, self._OPERATORS)
        key = self._key("start_task", context)
        async with self._repository.transaction():
            task = await self._cached_task(context, key, command.task_id)
            if task.status is TaskStatus.RUNNING:
                await self._remember(context, key, task.task_id)
                return task
            dependencies: list[Task] = []
            for item in task.depends_on:
                dependencies.append(
                    await self._repository.get_task(context.identity.tenant_id, item)
                )
            if any(item.status is not TaskStatus.SUCCEEDED for item in dependencies):
                raise ValueError("task dependencies must succeed before the task starts")
            started = task
            if started.status is TaskStatus.PENDING:
                started = started.transition_to(
                    TaskStatus.READY,
                    actor_id=context.identity.actor_id,
                    reason="task dependencies satisfied",
                )
            started = started.transition_to(
                TaskStatus.RUNNING,
                actor_id=context.identity.actor_id,
                reason="task execution started",
            )
            await self._repository.save_task(started, task.optimistic_version)
            await self._repository.record_audit(self._audit(context, "task.started", started))
            await self._remember(context, key, started.task_id)
            return started

    async def complete_task(self, context: CommandContext, command: CompleteTask) -> Task:
        self._require_any(context, self._OPERATORS)
        if not command.reason.strip():
            raise ValueError("Task completion requires a reason")
        key = self._key("complete_task", context)
        async with self._repository.transaction():
            task = await self._cached_task(context, key, command.task_id)
            target = TaskStatus.SUCCEEDED if command.succeeded else TaskStatus.FAILED
            if task.status is target:
                await self._remember(context, key, task.task_id)
                return task
            if task.status is not TaskStatus.RUNNING:
                raise ValueError("only a running Task can be completed")
            completed = task.transition_to(
                target,
                actor_id=context.identity.actor_id,
                reason=command.reason,
            )
            await self._repository.save_task(completed, task.optimistic_version)
            await self._repository.record_audit(
                self._audit(context, f"task.{target.value}", completed)
            )
            await self._remember(context, key, completed.task_id)
            return completed

    async def propose_action(self, context: CommandContext, command: ProposeAction) -> Action:
        self._require_any(context, self._OPERATORS)
        key = self._key("propose_action", context)
        async with self._repository.transaction():
            cached = await self._load_idempotency(context, key)
            if cached is not None:
                return await self._repository.get_action(context.identity.tenant_id, cached)
            task = await self._repository.get_task(context.identity.tenant_id, command.task_id)
            if task.status is not TaskStatus.RUNNING:
                raise ValueError("Action proposal requires a running Task")
            run = await self._repository.get_run(context.identity.tenant_id, task.run_id)
            tool_ref = f"{command.tool_name}@{command.tool_version}"
            if (
                run.execution_snapshot is None
                or tool_ref not in run.execution_snapshot.tool_versions
            ):
                raise PermissionError("Action tool version is not bound to the Run snapshot")
            action = Action(
                tenant_id=context.identity.tenant_id,
                run_id=task.run_id,
                task_id=task.task_id,
                tool_name=command.tool_name,
                tool_version=command.tool_version,
                operation=command.operation,
                resource_scope=command.resource_scope,
                parameters=JsonObject.from_value(command.parameters),
                risk_level=command.risk_level,
                idempotency_key=context.idempotency_key,
                expected_effect=command.expected_effect,
                classification=command.classification,
                execution_mode=command.execution_mode,
            )
            await self._repository.add_action(action)
            await self._repository.record_audit(self._audit(context, "action.proposed", action))
            await self._remember(context, key, action.action_id)
            return action

    async def request_approval(
        self, context: CommandContext, command: RequestApproval
    ) -> ApprovalRequest:
        self._require_any(context, self._OPERATORS)
        key = self._key("request_approval", context)
        async with self._repository.transaction():
            cached = await self._load_idempotency(context, key)
            if cached is not None:
                return await self._repository.get_approval(context.identity.tenant_id, cached)
            action = await self._repository.get_action(
                context.identity.tenant_id, command.action_id
            )
            if action.status is not ActionStatus.PROPOSED:
                raise ValueError("approval can only be requested for a proposed Action")
            approval = ApprovalRequest(
                tenant_id=action.tenant_id,
                run_id=action.run_id,
                action_id=action.action_id,
                action_digest=action.canonical_digest,
                tool_version=action.tool_version,
                operation=action.operation,
                resource_scope=action.resource_scope,
                argument_digest=action.parameter_digest,
                policy_version=command.policy_version,
                impact_summary=command.impact_summary,
                required_role=command.required_role,
                expires_at=command.expires_at,
            )
            awaiting = action.transition_to(
                ActionStatus.AWAITING_APPROVAL,
                actor_id=context.identity.actor_id,
                reason="approval required before execution",
            )
            await self._repository.add_approval(approval)
            await self._repository.save_action(awaiting, action.optimistic_version)
            await self._repository.record_audit(
                self._audit(context, "approval.requested", approval)
            )
            await self._remember(context, key, approval.approval_id)
            return approval

    async def decide_approval(
        self, context: CommandContext, command: DecideApproval
    ) -> ApprovalRequest:
        key = self._key("decide_approval", context)
        async with self._repository.transaction():
            cached = await self._load_idempotency(context, key)
            if cached is not None:
                return await self._repository.get_approval(context.identity.tenant_id, cached)
            approval = await self._repository.get_approval(
                context.identity.tenant_id, command.approval_id
            )
            self._require_any(
                context,
                frozenset({approval.required_role, "tenant_admin", "platform_admin"}),
            )
            if approval.action_digest != command.action_digest:
                raise PermissionError("approval digest does not match the persisted request")
            decided = approval.decide(context.identity.actor_id, command.approved, command.reason)
            await self._repository.save_approval(decided, approval.optimistic_version)
            if decided.status in {ApprovalStatus.REJECTED, ApprovalStatus.EXPIRED}:
                action = await self._repository.get_action(
                    context.identity.tenant_id, approval.action_id
                )
                denied = action.transition_to(
                    ActionStatus.DENIED,
                    actor_id=context.identity.actor_id,
                    reason=f"approval {decided.status.value}",
                )
                await self._repository.save_action(denied, action.optimistic_version)
            await self._repository.record_audit(
                self._audit(context, f"approval.{decided.status.value}", decided)
            )
            await self._remember(context, key, decided.approval_id)
            return decided

    async def authorize_action_at_execution_time(
        self, context: CommandContext, command: AuthorizeActionAtExecutionTime
    ) -> ActionExecutionEnvelope:
        if not self._legacy_authorization_enabled:
            raise RuntimeError(
                "direct execution authorization is disabled; use execute_governed_action"
            )
        self._require_any(context, self._OPERATORS)
        if command.deadline <= datetime.now(UTC):
            raise ValueError("execution authorization deadline has expired")
        key = self._key("authorize_action", context)
        denied_reason: str | None = None
        async with self._repository.transaction():
            cached_invocation = await self._load_idempotency(context, key)
            action = await self._repository.get_action(
                context.identity.tenant_id, command.action_id
            )
            approval: ApprovalRequest | None = None
            if command.approval_id is not None:
                approval = await self._repository.get_approval(
                    context.identity.tenant_id, command.approval_id
                )
            requires_approval = action.risk_level in {
                RiskLevel.L2_REVERSIBLE_WRITE,
                RiskLevel.L3_HIGH_IMPACT_WRITE,
                RiskLevel.L4_PRIVILEGED,
            }
            if not command.policy_allowed:
                denied_reason = command.policy_reason or "policy denied execution"
            elif requires_approval and (
                approval is None or not approval.authorizes(action, command.policy_version)
            ):
                denied_reason = "a current, exact-bound approval is required"
            if denied_reason is not None:
                if action.status in {ActionStatus.PROPOSED, ActionStatus.AWAITING_APPROVAL}:
                    denied = action.transition_to(
                        ActionStatus.DENIED,
                        actor_id=context.identity.actor_id,
                        reason=denied_reason,
                    )
                    await self._repository.save_action(denied, action.optimistic_version)
                    await self._repository.record_audit(
                        self._audit(context, "action.denied", denied)
                    )
                    await self._remember(context, key, denied.action_id)
            else:
                if action.status in {ActionStatus.PROPOSED, ActionStatus.AWAITING_APPROVAL}:
                    authorized = action.transition_to(
                        ActionStatus.AUTHORIZED,
                        actor_id=context.identity.actor_id,
                        reason=f"execution-time policy {command.policy_version} allowed",
                    )
                    await self._repository.save_action(authorized, action.optimistic_version)
                    action = authorized
                    await self._repository.record_audit(
                        self._audit(context, "action.authorized", action)
                    )
                if action.status is not ActionStatus.AUTHORIZED:
                    raise ValueError("Action is not executable in its current state")
                envelope = ActionExecutionEnvelope.from_action(
                    action,
                    actor_id=context.identity.actor_id,
                    principal_id=context.identity.principal_id,
                    agent_identity=command.agent_identity,
                    delegation_ref=command.delegation_ref,
                    budget_ref=command.budget_ref,
                    approval_id=command.approval_id,
                    policy_version=command.policy_version,
                    deadline=command.deadline,
                    traceparent=command.traceparent,
                )
                if cached_invocation is not None:
                    return replace(envelope, invocation_id=cached_invocation)
                await self._remember(context, key, envelope.invocation_id)
                return envelope
        assert denied_reason is not None
        raise PermissionError(denied_reason)

    async def execute_governed_action(
        self, context: CommandContext, command: ExecuteGovernedAction
    ) -> GovernedActionExecution:
        """Execute through the mandatory Gateway and persist all resulting facts."""

        self._require_any(context, self._OPERATORS)
        if self._governed_gateway is None:
            raise RuntimeError("a governed tool gateway is required for external execution")
        key = self._key("execute_governed_action", context)
        async with self._repository.transaction():
            cached = await self._load_idempotency(context, key)
            if cached is not None:
                action = await self._repository.get_action(context.identity.tenant_id, cached)
                attempts = await self._repository.list_action_attempts(
                    context.identity.tenant_id, action.action_id
                )
                items = tuple(
                    item
                    for item in await self._repository.list_evidence(context.identity.tenant_id)
                    if item.action_id == action.action_id
                )
                if not attempts or not items:
                    raise RuntimeError("cached governed execution is missing durable facts")
                attempt = max(attempts, key=lambda item: item.recorded_at)
                evidence = max(items, key=lambda item: item.captured_at)
                # The receipt is reconstructed without claiming more than durable state proves.
                status = {
                    ActionStatus.SUCCEEDED: ToolResultStatus.SUCCEEDED,
                    ActionStatus.FAILED: ToolResultStatus.FAILED,
                    ActionStatus.DENIED: ToolResultStatus.REJECTED,
                    ActionStatus.UNKNOWN: ToolResultStatus.UNKNOWN,
                }.get(action.status, ToolResultStatus.UNKNOWN)
                return GovernedActionExecution(
                    GatewayResult(action, ToolReceipt(attempt.receipt_ref, status), True),
                    attempt,
                    evidence,
                )
            action = await self._repository.get_action(
                context.identity.tenant_id, command.action_id
            )
            approval = (
                await self._repository.get_approval(context.identity.tenant_id, command.approval_id)
                if command.approval_id is not None
                else None
            )

        authorization = AuthorizationContext(
            tenant_id=str(context.identity.tenant_id),
            actor_id=str(context.identity.actor_id),
            principal_id=str(context.identity.principal_id),
            agent_id=context.identity.agent_id or "human-operator",
            roles=tuple(sorted(context.identity.roles)),
            policy_version=command.policy_version,
            delegation_id=command.delegation_id,
            correlation_id=str(context.correlation_id),
        )
        result = await self._governed_gateway.execute(
            authorization, action, approval, command.cost_units
        )
        attempt_status = {
            ToolResultStatus.SUCCEEDED: ActionAttemptStatus.SUCCEEDED,
            ToolResultStatus.ACCEPTED: ActionAttemptStatus.UNKNOWN,
            ToolResultStatus.UNKNOWN: ActionAttemptStatus.UNKNOWN,
            ToolResultStatus.FAILED: ActionAttemptStatus.FAILED,
            ToolResultStatus.REJECTED: ActionAttemptStatus.FAILED,
        }[result.receipt.status]
        receipt_ref = result.receipt.external_id or (
            f"gateway://{result.receipt.status.value}/{action.action_id}"
        )
        failure_reason = (
            dict(result.receipt.output).get("reason", result.receipt.status.value)
            if attempt_status is ActionAttemptStatus.FAILED
            else None
        )
        attempt = ActionAttempt(
            tenant_id=action.tenant_id,
            run_id=action.run_id,
            action_id=action.action_id,
            invocation_id=uuid4(),
            status=attempt_status,
            idempotency_key=action.idempotency_key,
            receipt_ref=receipt_ref,
            executor_identity=f"gateway:{action.tool_name}@{action.tool_version}",
            failure_reason=failure_reason,
        )
        now = datetime.now(UTC)
        evidence_payload = json.dumps(
            {
                "external_id": result.receipt.external_id,
                "output": result.receipt.output,
                "status": result.receipt.status.value,
            },
            sort_keys=True,
            separators=(",", ":"),
        )
        evidence = Evidence(
            tenant_id=action.tenant_id,
            run_id=action.run_id,
            action_id=action.action_id,
            source="governed-tool-gateway",
            source_identity=f"{action.tool_name}@{action.tool_version}",
            capture_method=EvidenceCaptureMethod.SYSTEM_QUERY,
            reference=receipt_ref,
            observed_state=result.receipt.status.value,
            content_digest=sha256(evidence_payload.encode()).hexdigest(),
            classification=action.classification,
            valid_from=now,
            valid_until=now + timedelta(days=1),
            # A Tool receipt proves only invocation, never the external business Outcome.
            integrity=EvidenceIntegrity.UNVERIFIED,
            captured_at=now,
        )
        async with self._repository.transaction():
            current = await self._repository.get_action(action.tenant_id, action.action_id)
            if current.optimistic_version != action.optimistic_version:
                raise ConcurrencyConflict("Action changed while external execution was in flight")
            await self._repository.save_action(result.action, action.optimistic_version)
            await self._repository.add_action_attempt(attempt)
            await self._repository.add_evidence(evidence)
            await self._repository.record_audit(
                self._audit(context, "action.governed_execution_recorded", attempt)
            )
            await self._repository.record_audit(self._audit(context, "evidence.recorded", evidence))
            await self._remember(context, key, action.action_id)
        return GovernedActionExecution(result, attempt, evidence)

    async def record_action_attempt(
        self, context: CommandContext, command: RecordActionAttempt
    ) -> Action:
        self._require_any(context, self._OPERATORS)
        key = self._key("record_action_attempt", context)
        async with self._repository.transaction():
            cached = await self._load_idempotency(context, key)
            if cached is not None:
                return await self._repository.get_action(context.identity.tenant_id, cached)
            action = await self._repository.get_action(
                context.identity.tenant_id, command.action_id
            )
            if action.status not in {ActionStatus.AUTHORIZED, ActionStatus.EXECUTING}:
                raise ValueError("Action attempt requires execution-time authorization")
            updated = action
            if action.status is ActionStatus.AUTHORIZED:
                updated = action.transition_to(
                    ActionStatus.EXECUTING,
                    actor_id=context.identity.actor_id,
                    reason="tool invocation started",
                )
            target = self._action_target(command.status)
            if target is not None:
                updated = updated.transition_to(
                    target,
                    actor_id=context.identity.actor_id,
                    reason=command.failure_reason or f"tool receipt: {command.receipt_ref}",
                )
            attempt = ActionAttempt(
                tenant_id=action.tenant_id,
                run_id=action.run_id,
                action_id=action.action_id,
                invocation_id=command.invocation_id,
                status=command.status,
                idempotency_key=context.idempotency_key,
                receipt_ref=command.receipt_ref,
                executor_identity=command.executor_identity,
                failure_reason=(
                    command.failure_reason
                    or (
                        "tool execution failed"
                        if command.status is ActionAttemptStatus.FAILED
                        else None
                    )
                ),
            )
            await self._repository.add_action_attempt(attempt)
            await self._repository.save_action(updated, action.optimistic_version)
            await self._repository.record_audit(
                self._audit(context, "action.attempt_recorded", attempt)
            )
            await self._remember(context, key, updated.action_id)
            return updated

    async def record_evidence(self, context: CommandContext, command: RecordEvidence) -> Evidence:
        self._require_any(context, self._OPERATORS)
        item = command.evidence
        if item.integrity is EvidenceIntegrity.VERIFIED:
            raise ValueError(
                "integrity-verified Evidence must be captured through authoritative readback"
            )
        if item.tenant_id != context.identity.tenant_id:
            raise PermissionError("Evidence tenant does not match command identity")
        key = self._key("record_evidence", context)
        async with self._repository.transaction():
            cached = await self._load_idempotency(context, key)
            if cached is not None:
                return await self._repository.get_evidence(context.identity.tenant_id, cached)
            action = await self._repository.get_action(item.tenant_id, item.action_id)
            if action.status is not ActionStatus.SUCCEEDED or action.run_id != item.run_id:
                raise ValueError("Evidence requires a succeeded authoritative Action")
            await self._repository.add_evidence(item)
            await self._repository.record_audit(self._audit(context, "evidence.recorded", item))
            await self._remember(context, key, item.evidence_id)
            return item

    async def capture_authoritative_evidence(
        self, context: CommandContext, command: CaptureAuthoritativeEvidence
    ) -> Evidence:
        """Capture an authoritative observation through an immutable, recoverable artifact Saga."""

        self._require_any(context, self._OPERATORS)
        if self._evidence_artifacts is None or self._authoritative_readback is None:
            raise RuntimeError("authoritative Evidence capture is not configured")
        key = self._key("capture_authoritative_evidence", context)
        cached = await self._load_idempotency(context, key)
        if cached is not None:
            return await self._repository.get_evidence(context.identity.tenant_id, cached)
        evidence_id = uuid5(
            NAMESPACE_URL,
            f"autonoesis:evidence:{context.identity.tenant_id}:{context.idempotency_key}",
        )
        try:
            pending = await self._repository.get_evidence_capture(
                context.identity.tenant_id, evidence_id
            )
        except LookupError:
            pending = None
        if pending is not None:
            if pending.status.value == "committed":
                return await self._repository.get_evidence(context.identity.tenant_id, evidence_id)
            definition = pending.definition
            descriptor = EvidenceArtifactDescriptor(
                pending.tenant_id,
                pending.evidence_id,
                pending.artifact_uri,
                pending.expected_digest,
                DataClassification(str(definition["classification"])),
                int(str(definition["size_bytes"])),
                datetime.fromisoformat(str(definition["retained_until"])),
            )
            content = await self._evidence_artifacts.retrieve_verified(descriptor)
            stored = await self._evidence_artifacts.store(
                descriptor, content, str(definition["content_type"])
            )
            return await self._commit_evidence_capture(context, key, pending, stored)
        run = await self._repository.get_run(context.identity.tenant_id, command.run_id)
        goal = await self._repository.get_goal(context.identity.tenant_id, run.goal_id)
        action = await self._repository.get_action(context.identity.tenant_id, command.action_id)
        if action.run_id != run.run_id or action.status is not ActionStatus.SUCCEEDED:
            raise ValueError("authoritative Evidence requires a succeeded Action in the Run")
        criterion = next(
            (item for item in goal.success_criteria if item.criterion_id == command.criterion_id),
            None,
        )
        if criterion is None:
            raise ValueError("Evidence criterion is not part of the Goal contract")
        observation = await self._authoritative_readback.observe(
            command.source,
            context.identity.tenant_id,
            goal.subject_refs,
            criterion,
        )
        classification = self._evidence_policy.admit(
            observation.content,
            command.declared_classification,
            goal.data_policy.maximum_classification,
            goal.data_policy.retention_days,
        )
        retained_until = observation.captured_at + timedelta(days=goal.data_policy.retention_days)
        descriptor = self._evidence_artifacts.describe(
            context.identity.tenant_id,
            evidence_id,
            observation.content_digest,
            classification,
            len(observation.content),
            retained_until,
        )
        capture_definition: dict[str, object] = {
            "source": observation.source,
            "source_identity": observation.source_identity,
            "source_reference": observation.reference,
            "observed_state": observation.observed_state,
            "captured_at": observation.captured_at.isoformat(),
            "valid_until": observation.valid_until.isoformat(),
            "retained_until": retained_until.isoformat(),
            "classification": classification.value,
            "size_bytes": len(observation.content),
            "content_type": command.content_type,
            "subject_refs": [
                {
                    "system": item.system,
                    "subject_type": item.subject_type,
                    "subject_id": item.subject_id,
                    "version": item.version,
                }
                for item in goal.subject_refs
            ],
        }
        saga = EvidenceCaptureSaga(
            context.identity.tenant_id,
            evidence_id,
            run.run_id,
            action.action_id,
            criterion.criterion_id,
            command.source,
            descriptor.artifact_uri,
            descriptor.content_digest,
            capture_definition,
        )
        await self._repository.start_evidence_capture(saga)
        stored = await self._evidence_artifacts.store(
            descriptor, observation.content, command.content_type
        )
        await self._evidence_artifacts.retrieve_verified(stored)
        return await self._commit_evidence_capture(context, key, saga, stored)

    async def _commit_evidence_capture(
        self,
        context: CommandContext,
        key: str,
        saga: EvidenceCaptureSaga,
        stored: EvidenceArtifactDescriptor,
    ) -> Evidence:
        definition = saga.definition
        raw_subjects = definition["subject_refs"]
        if not isinstance(raw_subjects, list):
            raise ValueError("Evidence capture Saga subject references are invalid")
        captured_at = datetime.fromisoformat(str(definition["captured_at"]))
        retained_until = datetime.fromisoformat(str(definition["retained_until"]))
        subjects = tuple(
            SubjectRef(
                str(item["system"]),
                str(item["subject_type"]),
                str(item["subject_id"]),
                str(item["version"]) if item.get("version") else None,
            )
            for item in raw_subjects
            if isinstance(item, dict)
        )
        evidence = Evidence(
            tenant_id=saga.tenant_id,
            run_id=saga.run_id,
            action_id=saga.action_id,
            source=str(definition["source"]),
            source_identity=str(definition["source_identity"]),
            capture_method=EvidenceCaptureMethod.AUTHORITATIVE_READBACK,
            reference=stored.artifact_uri,
            observed_state=str(definition["observed_state"]),
            content_digest=stored.content_digest,
            classification=DataClassification(str(definition["classification"])),
            valid_from=captured_at,
            valid_until=datetime.fromisoformat(str(definition["valid_until"])),
            integrity=EvidenceIntegrity.VERIFIED,
            source_reference=str(definition["source_reference"]),
            subject_refs=subjects,
            retained_until=retained_until,
            artifact_version_id=stored.version_id,
            evidence_id=saga.evidence_id,
            captured_at=captured_at,
        )
        async with self._repository.transaction():
            await self._repository.add_evidence(evidence)
            await self._repository.complete_evidence_capture(
                context.identity.tenant_id, evidence.evidence_id
            )
            await self._repository.record_audit(
                self._audit(context, "evidence.authoritative_captured", evidence)
            )
            await self._remember(context, key, evidence.evidence_id)
        return evidence

    async def request_evidence_deletion(
        self, context: CommandContext, command: RequestEvidenceDeletion
    ) -> EvidenceDeletionRecord:
        """Retain metadata and a proof-bearing tombstone while deleting artifact bytes."""

        self._require_any(context, frozenset({"platform_admin", "tenant_admin"}))
        if self._evidence_artifacts is None:
            raise RuntimeError("Evidence artifact deletion is not configured")
        if not command.reason.strip():
            raise ValueError("Evidence deletion reason must not be empty")
        evidence = await self._repository.get_evidence(
            context.identity.tenant_id, command.evidence_id
        )
        now = datetime.now(UTC)
        record = EvidenceDeletionRecord(
            context.identity.tenant_id,
            evidence.evidence_id,
            evidence.reference,
            context.identity.actor_id,
            command.reason,
            now,
        )
        async with self._repository.transaction():
            await self._repository.record_evidence_deletion(record)
            await self._repository.record_audit(
                self._audit(context, "evidence.deletion_requested", evidence)
            )
        descriptor = EvidenceArtifactDescriptor(
            evidence.tenant_id,
            evidence.evidence_id,
            evidence.reference,
            evidence.content_digest,
            evidence.classification,
            0,
            evidence.retained_until or evidence.valid_until,
            evidence.artifact_version_id,
        )
        try:
            receipt = await self._evidence_artifacts.delete(descriptor)
        except PermissionError as exc:
            final = replace(
                record,
                status=EvidenceDeletionStatus.RETENTION_BLOCKED,
                failure_reason=str(exc),
            )
        except Exception as exc:
            final = replace(
                record,
                status=EvidenceDeletionStatus.FAILED,
                failure_reason=type(exc).__name__,
            )
        else:
            final = replace(
                record,
                status=EvidenceDeletionStatus.DELETED,
                deleted_at=receipt.deleted_at,
                provider_version_id=receipt.provider_version_id,
                proof_digest=receipt.proof_digest,
            )
        async with self._repository.transaction():
            await self._repository.record_evidence_deletion(final)
            await self._repository.record_audit(
                self._audit(context, f"evidence.deletion_{final.status.value}", evidence)
            )
        return final

    async def reconcile_unknown_action(
        self, context: CommandContext, command: ReconcileUnknownAction
    ) -> Action:
        self._require_any(context, self._OPERATORS)
        key = self._key("reconcile_unknown_action", context)
        async with self._repository.transaction():
            cached = await self._load_idempotency(context, key)
            if cached is not None:
                return await self._repository.get_action(context.identity.tenant_id, cached)
            action = await self._repository.get_action(
                context.identity.tenant_id, command.action_id
            )
            if action.status is not ActionStatus.UNKNOWN:
                raise ValueError("only an Unknown Action can be reconciled")
            target = ActionStatus.SUCCEEDED if command.succeeded else ActionStatus.FAILED
            reason = command.failure_reason or f"reconciled from {command.receipt_ref}"
            updated = action.transition_to(
                target, actor_id=context.identity.actor_id, reason=reason
            )
            attempt = ActionAttempt(
                tenant_id=action.tenant_id,
                run_id=action.run_id,
                action_id=action.action_id,
                invocation_id=command.invocation_id,
                status=(
                    ActionAttemptStatus.SUCCEEDED
                    if command.succeeded
                    else ActionAttemptStatus.FAILED
                ),
                idempotency_key=context.idempotency_key,
                receipt_ref=command.receipt_ref,
                executor_identity=command.executor_identity,
                failure_reason=(
                    command.failure_reason
                    or ("reconciliation reported failure" if not command.succeeded else None)
                ),
            )
            await self._repository.add_action_attempt(attempt)
            await self._repository.save_action(updated, action.optimistic_version)
            await self._repository.record_audit(self._audit(context, "action.reconciled", updated))
            await self._remember(context, key, updated.action_id)
            return updated

    async def verify_outcome(self, context: CommandContext, command: VerifyOutcome) -> Outcome:
        self._require_any(context, self._OPERATORS)
        if self._outcome_verifier is None:
            raise RuntimeError("trusted Outcome verification is not configured")
        key = self._key("verify_outcome", context)
        async with self._repository.transaction():
            cached = await self._load_idempotency(context, key)
            if cached is not None:
                return await self._repository.get_outcome(context.identity.tenant_id, cached)
            run = await self._repository.get_run(context.identity.tenant_id, command.run_id)
            goal = await self._repository.get_goal(context.identity.tenant_id, run.goal_id)
            criterion = next(
                (
                    item
                    for item in goal.success_criteria
                    if item.criterion_id == command.criterion_id
                ),
                None,
            )
            if criterion is None:
                raise ValueError("Outcome criterion is not part of the Goal contract")
            items = tuple(
                [
                    await self._repository.get_evidence(context.identity.tenant_id, item)
                    for item in command.evidence_ids
                ]
            )
            if any(item.run_id != run.run_id for item in items):
                raise ValueError("Outcome Evidence must belong to the verified Run")
            decision = await self._outcome_verifier.verify(
                context.identity.tenant_id,
                goal.subject_refs,
                criterion,
                items,
                datetime.now(UTC),
            )
            outcome = Outcome(
                tenant_id=context.identity.tenant_id,
                goal_id=goal.goal_id,
                run_id=run.run_id,
                criterion_id=command.criterion_id,
                verifier_version=decision.verifier_version,
                status=decision.status,
                evidence=items,
                verified_at=decision.verified_at,
            )
            await self._repository.add_outcome(outcome)
            await self._repository.record_audit(self._audit(context, "outcome.verified", outcome))
            await self._remember(context, key, outcome.outcome_id)
            return outcome

    async def complete_run(self, context: CommandContext, command: CompleteRun) -> Run:
        self._require_any(context, self._OPERATORS)
        key = self._key("complete_run", context)
        async with self._repository.transaction():
            run = await self._cached_run(context, key, command.run_id)
            if run.status in {RunStatus.SUCCEEDED, RunStatus.FAILED}:
                await self._remember(context, key, run.run_id)
                return run
            if run.status not in {RunStatus.RUNNING, RunStatus.AWAITING_EVIDENCE}:
                raise ValueError("Run is not ready for completion evaluation")
            goal = await self._repository.get_goal(context.identity.tenant_id, run.goal_id)
            tasks = await self._repository.list_tasks(context.identity.tenant_id, run.run_id)
            actions = await self._repository.list_actions(context.identity.tenant_id, run.run_id)
            outcomes = await self._repository.list_outcomes(context.identity.tenant_id, run.run_id)
            required = {item.criterion_id for item in goal.success_criteria}
            verified = {
                item.criterion_id for item in outcomes if item.status is OutcomeStatus.VERIFIED
            }
            observed = {item.criterion_id for item in outcomes}
            if any(task.status is not TaskStatus.SUCCEEDED for task in tasks) or any(
                action.status is not ActionStatus.SUCCEEDED for action in actions
            ):
                raise ValueError("Run tasks and Actions must succeed before completion")
            if required.issubset(verified):
                target, reason = RunStatus.SUCCEEDED, "all required Outcomes verified"
            elif required.issubset(observed) and any(
                item.status is OutcomeStatus.NOT_MET for item in outcomes
            ):
                target, reason = RunStatus.FAILED, "one or more required Outcomes were not met"
            else:
                target, reason = RunStatus.AWAITING_EVIDENCE, "required Outcomes remain unverified"
            if run.status is target:
                await self._remember(context, key, run.run_id)
                return run
            updated = run.transition_to(target, actor_id=context.identity.actor_id, reason=reason)
            await self._repository.save_run(
                updated,
                run.optimistic_version,
                self._audit(context, f"run.{target.value}", updated),
            )
            await self._remember(context, key, updated.run_id)
            return updated

    async def satisfy_or_fail_goal(
        self, context: CommandContext, command: SatisfyOrFailGoal
    ) -> GoalContract:
        self._require_any(context, self._OPERATORS)
        if not command.reason.strip():
            raise ValueError("Goal terminal decision requires a reason")
        key = self._key("finish_goal", context)
        async with self._repository.transaction():
            goal = await self._cached_goal(context, key, command.goal_id)
            if goal.status in {GoalStatus.SATISFIED, GoalStatus.FAILED}:
                await self._remember(context, key, goal.goal_id)
                return goal
            runs = await self._repository.list_runs(context.identity.tenant_id, goal.goal_id)
            if command.satisfied:
                succeeded = [run for run in runs if run.status is RunStatus.SUCCEEDED]
                if not succeeded:
                    raise ValueError("Goal satisfaction requires a succeeded Run")
                for run in succeeded:
                    outcomes = await self._repository.list_outcomes(
                        context.identity.tenant_id, run.run_id
                    )
                    required = {item.criterion_id for item in goal.success_criteria}
                    verified = {
                        item.criterion_id
                        for item in outcomes
                        if item.status is OutcomeStatus.VERIFIED
                    }
                    if required.issubset(verified):
                        break
                else:
                    raise ValueError("Goal satisfaction requires all required Outcomes")
                target = GoalStatus.SATISFIED
            else:
                if not runs or any(self._run_is_active(run) for run in runs):
                    raise ValueError("Goal failure requires all Runs to be terminal")
                target = GoalStatus.FAILED
            updated = goal.transition_to(
                target,
                actor_id=context.identity.actor_id,
                reason=command.reason,
            )
            await self._repository.save_goal(
                updated,
                goal.version,
                self._audit(context, f"goal.{target.value}", updated),
            )
            await self._remember(context, key, updated.goal_id)
            return updated

    async def cancel_run(self, context: CommandContext, command: CancelRun) -> Run:
        self._require_any(context, self._OPERATORS)
        return await self._transition_run(
            context, command.run_id, RunStatus.CANCELLED, command.reason, "cancel_run"
        )

    async def fail_run(self, context: CommandContext, command: FailRun) -> Run:
        self._require_any(context, self._OPERATORS)
        return await self._transition_run(
            context, command.run_id, RunStatus.FAILED, command.reason, "fail_run"
        )

    async def take_over_run(self, context: CommandContext, command: TakeOverRun) -> Run:
        self._require_any(context, frozenset({"platform_admin", "tenant_admin", "operator"}))
        return await self._transition_run(
            context, command.run_id, RunStatus.BLOCKED, command.reason, "take_over_run"
        )

    async def _transition_run(
        self,
        context: CommandContext,
        run_id: UUID,
        target: RunStatus,
        reason: str,
        operation: str,
    ) -> Run:
        if not reason.strip():
            raise ValueError("Run transition requires a reason")
        key = self._key(operation, context)
        async with self._repository.transaction():
            run = await self._cached_run(context, key, run_id)
            if run.status is target:
                await self._remember(context, key, run.run_id)
                return run
            updated = run.transition_to(target, actor_id=context.identity.actor_id, reason=reason)
            await self._repository.save_run(
                updated,
                run.optimistic_version,
                self._audit(context, f"run.{target.value}", updated),
            )
            await self._remember(context, key, updated.run_id)
            return updated

    async def _cached_goal(
        self, context: CommandContext, key: str, requested_id: UUID
    ) -> GoalContract:
        cached = await self._load_idempotency(context, key)
        return await self._repository.get_goal(context.identity.tenant_id, cached or requested_id)

    async def _cached_run(self, context: CommandContext, key: str, requested_id: UUID) -> Run:
        cached = await self._load_idempotency(context, key)
        return await self._repository.get_run(context.identity.tenant_id, cached or requested_id)

    async def _cached_task(self, context: CommandContext, key: str, requested_id: UUID) -> Task:
        cached = await self._load_idempotency(context, key)
        return await self._repository.get_task(context.identity.tenant_id, cached or requested_id)

    async def _remember(self, context: CommandContext, key: str, value: UUID) -> None:
        await self._repository.put_idempotency(
            context.identity.tenant_id, key, value, context.request_digest
        )

    async def _load_idempotency(self, context: CommandContext, key: str) -> UUID | None:
        return await self._repository.get_idempotency(
            context.identity.tenant_id, key, context.request_digest
        )

    @staticmethod
    def _key(operation: str, context: CommandContext) -> str:
        return f"{operation}:{context.idempotency_key}"

    @staticmethod
    def _run_is_active(run: Run) -> bool:
        return run.status in {
            RunStatus.PENDING,
            RunStatus.RUNNING,
            RunStatus.BLOCKED,
            RunStatus.AWAITING_EVIDENCE,
        }

    @staticmethod
    def _action_target(status: ActionAttemptStatus) -> ActionStatus | None:
        return {
            ActionAttemptStatus.STARTED: None,
            ActionAttemptStatus.SUCCEEDED: ActionStatus.SUCCEEDED,
            ActionAttemptStatus.FAILED: ActionStatus.FAILED,
            ActionAttemptStatus.UNKNOWN: ActionStatus.UNKNOWN,
        }[status]

    @staticmethod
    def _build_task(tenant_id: UUID, run_id: UUID, item: TaskDefinition) -> Task:
        values: dict[str, Any] = {
            "tenant_id": tenant_id,
            "run_id": run_id,
            "name": item.name,
            "completion_criterion": item.completion_criterion,
            "depends_on": item.depends_on,
            "preconditions": item.preconditions,
            "estimated_cost": item.estimated_cost,
            "risk_level": item.risk_level,
            "compensation": item.compensation,
            "evidence_requirements": item.evidence_requirements,
        }
        if item.task_id is not None:
            values["task_id"] = item.task_id
        return Task(**values)

    @staticmethod
    def _require_any(context: CommandContext, allowed: frozenset[str]) -> None:
        if not context.identity.roles.intersection(allowed):
            raise PermissionError("the current principal does not have the required role")

    @staticmethod
    def _audit(context: CommandContext, event_type: str, item: object) -> AuditEvent:
        object_type = item.__class__.__name__.replace("Contract", "").lower()
        object_id = next(
            str(getattr(item, name))
            for name in (
                "goal_id",
                "run_id",
                "snapshot_id",
                "plan_id",
                "task_id",
                "action_id",
                "approval_id",
                "attempt_id",
                "evidence_id",
                "outcome_id",
            )
            if hasattr(item, name)
        )
        details: dict[str, Any] = {
            "causation_id": str(context.causation_id),
            "idempotency_key": context.idempotency_key,
        }
        for name in (
            "goal_id",
            "run_id",
            "task_id",
            "action_id",
            "approval_id",
            "criterion_id",
            "policy_version",
            "verifier_version",
            "source_identity",
            "tool_name",
            "tool_version",
        ):
            if hasattr(item, name):
                value = getattr(item, name)
                details[name] = value.value if hasattr(value, "value") else str(value)
        if isinstance(item, Outcome):
            details["evidence_ids"] = [str(value) for value in item.evidence_ids]
            details["outcome_status"] = item.status.value
        return AuditEvent(
            tenant_id=context.identity.tenant_id,
            actor_id=context.identity.actor_id,
            principal_id=context.identity.principal_id,
            event_type=event_type,
            object_type=object_type,
            object_id=object_id,
            correlation_id=context.correlation_id,
            details=details,
        )


__all__ = [
    "ActivateGoal",
    "AuthorizeActionAtExecutionTime",
    "CancelRun",
    "CaptureAuthoritativeEvidence",
    "CommandContext",
    "CompleteRun",
    "CompleteTask",
    "CreateValidatedPlan",
    "DecideApproval",
    "ExecuteGovernedAction",
    "FailRun",
    "GoalExecutionApplication",
    "GovernedActionExecution",
    "PrepareRunContext",
    "ProposeAction",
    "ReconcileUnknownAction",
    "RecordActionAttempt",
    "RecordEvidence",
    "RequestApproval",
    "RequestEvidenceDeletion",
    "RequestRun",
    "SatisfyOrFailGoal",
    "StartTask",
    "TakeOverRun",
    "TaskDefinition",
    "VerifyOutcome",
]
