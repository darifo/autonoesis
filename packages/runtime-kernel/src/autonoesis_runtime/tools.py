"""Non-bypassable execution-time governance for external side effects."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Protocol
from uuid import UUID, uuid4

from autonoesis_domain import Action, ActionStatus, ApprovalRequest, ApprovalStatus, RiskLevel


class KillSwitchDimension(StrEnum):
    TENANT = "tenant"
    AGENT = "agent"
    TOOL = "tool"
    OPERATION = "operation"
    PROVIDER = "provider"
    CAPABILITY_PACK = "capability_pack"


@dataclass(frozen=True, slots=True)
class KillSwitchQuery:
    tenant_id: str | None = None
    agent_id: str | None = None
    tool_name: str | None = None
    operation: str | None = None
    provider: str | None = None
    capability_pack_id: str | None = None

    def dimensions(self) -> list[tuple[KillSwitchDimension, str]]:
        values = (
            (KillSwitchDimension.TENANT, self.tenant_id),
            (KillSwitchDimension.AGENT, self.agent_id),
            (KillSwitchDimension.TOOL, self.tool_name),
            (KillSwitchDimension.OPERATION, self.operation),
            (KillSwitchDimension.PROVIDER, self.provider),
            (KillSwitchDimension.CAPABILITY_PACK, self.capability_pack_id),
        )
        return [(dimension, value) for dimension, value in values if value is not None]


@dataclass(frozen=True, slots=True)
class KillSwitchRecord:
    kill_switch_id: UUID = field(default_factory=uuid4)
    dimension: KillSwitchDimension = KillSwitchDimension.TENANT
    target: str = ""
    reason: str = ""
    activated_by: str = ""
    activated_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    deactivated_at: datetime | None = None


class KillSwitchPort(Protocol):
    async def is_blocked(self, query: KillSwitchQuery) -> bool: ...

    async def activate(
        self, dimension: KillSwitchDimension, target: str, reason: str, activated_by: str
    ) -> KillSwitchRecord: ...

    async def deactivate(
        self, dimension: KillSwitchDimension, target: str
    ) -> KillSwitchRecord | None: ...

    async def list_active(self) -> tuple[KillSwitchRecord, ...]: ...


@dataclass(frozen=True, slots=True)
class AuthorizationContext:
    tenant_id: str
    actor_id: str
    principal_id: str
    agent_id: str
    roles: tuple[str, ...]
    policy_version: str
    delegation_id: str | None = None
    correlation_id: str = ""


@dataclass(frozen=True, slots=True)
class PolicyDecision:
    allowed: bool
    requires_approval: bool
    reason: str
    policy_version: str


@dataclass(frozen=True, slots=True)
class ResolvedToolVersion:
    """Immutable server-side tool definition used for one invocation."""

    tool_name: str
    version: str
    provider: str
    operations: frozenset[str]
    resource_prefixes: tuple[str, ...]
    input_schema: dict[str, Any]
    risk_level: RiskLevel
    credential_scope: str

    def __post_init__(self) -> None:
        required = (self.tool_name, self.version, self.provider, self.credential_scope)
        if any(not value.strip() for value in required) or not self.operations:
            raise ValueError("tool version identity and operations are required")


class ToolCatalogPort(Protocol):
    async def resolve(self, tool_name: str, version: str) -> ResolvedToolVersion: ...


class DelegationPort(Protocol):
    async def authorize(
        self, context: AuthorizationContext, action: Action, tool: ResolvedToolVersion
    ) -> bool: ...


class SchemaValidationPort(Protocol):
    async def validate(self, schema: dict[str, Any], value: dict[str, Any]) -> None: ...


class PolicyPort(Protocol):
    async def authorize(self, context: AuthorizationContext, action: Action) -> PolicyDecision: ...


@dataclass(frozen=True, slots=True)
class CredentialLease:
    reference: str
    scope: str
    expires_at: datetime

    def __post_init__(self) -> None:
        if not self.reference.strip() or not self.scope.strip() or self.expires_at.tzinfo is None:
            raise ValueError("credential lease must be scoped, referenced, and timezone-aware")


class CredentialBrokerPort(Protocol):
    async def issue(
        self, context: AuthorizationContext, action: Action, tool: ResolvedToolVersion
    ) -> CredentialLease: ...


class ToolResultStatus(StrEnum):
    REJECTED = "rejected"
    ACCEPTED = "accepted"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class ToolReceipt:
    external_id: str
    status: ToolResultStatus
    output: tuple[tuple[str, str], ...] = ()

    @property
    def accepted(self) -> bool:
        return self.status in {ToolResultStatus.ACCEPTED, ToolResultStatus.SUCCEEDED}


class ControlledEgressPort(Protocol):
    async def execute(
        self, action: Action, tool: ResolvedToolVersion, credential: CredentialLease
    ) -> ToolReceipt: ...

    async def verify(
        self, action: Action, tool: ResolvedToolVersion, receipt: ToolReceipt
    ) -> bool: ...


class ReservationStatus(StrEnum):
    ACQUIRED = "acquired"
    CACHED = "cached"
    IN_PROGRESS = "in_progress"
    UNKNOWN = "unknown"
    CONFLICT = "conflict"
    BUDGET_EXHAUSTED = "budget_exhausted"


@dataclass(frozen=True, slots=True)
class ExecutionReservation:
    tenant_id: str
    run_id: str
    action_id: str
    tool_name: str
    tool_version: str
    idempotency_key: str
    request_digest: str
    cost_units: int


@dataclass(frozen=True, slots=True)
class ReservationDecision:
    status: ReservationStatus
    reservation_id: str | None = None
    receipt: ToolReceipt | None = None


class AtomicExecutionReservationPort(Protocol):
    """Atomically bind idempotency identity and reserve budget once."""

    async def reserve(self, request: ExecutionReservation) -> ReservationDecision: ...

    async def complete(self, tenant_id: str, reservation_id: str, receipt: ToolReceipt) -> None: ...


@dataclass(frozen=True, slots=True)
class GatewayAuditRecord:
    tenant_id: str
    action_id: str
    correlation_id: str
    event: str
    status: ToolResultStatus
    reason: str
    request_digest: str
    external_id: str = ""
    occurred_at: datetime = field(default_factory=lambda: datetime.now(UTC))


class GatewayAuditPort(Protocol):
    async def record(self, item: GatewayAuditRecord) -> None: ...


@dataclass(frozen=True, slots=True)
class GatewayResult:
    action: Action
    receipt: ToolReceipt
    cached: bool = False


class GovernedToolGateway:
    """The only runtime path allowed to perform a governed external side effect."""

    def __init__(
        self,
        *,
        catalog: ToolCatalogPort,
        delegation: DelegationPort,
        schema_validator: SchemaValidationPort,
        policy: PolicyPort,
        kill_switch: KillSwitchPort,
        reservations: AtomicExecutionReservationPort,
        credentials: CredentialBrokerPort,
        egress: ControlledEgressPort,
        audit: GatewayAuditPort,
        allow_l4: bool = False,
    ) -> None:
        self._catalog = catalog
        self._delegation = delegation
        self._schema_validator = schema_validator
        self._policy = policy
        self._kill_switch = kill_switch
        self._reservations = reservations
        self._credentials = credentials
        self._egress = egress
        self._audit = audit
        self._allow_l4 = allow_l4

    async def execute(
        self,
        context: AuthorizationContext,
        action: Action,
        approval: ApprovalRequest | None,
        cost_units: int,
    ) -> GatewayResult:
        if action.status not in {ActionStatus.PROPOSED, ActionStatus.AWAITING_APPROVAL}:
            raise ValueError("action is not executable from its current state")
        if context.tenant_id != str(action.tenant_id):
            raise PermissionError("authorization tenant differs from action tenant")
        if cost_units <= 0:
            raise ValueError("execution cost must be positive")

        try:
            tool = await self._catalog.resolve(action.tool_name, action.tool_version)
        except LookupError:
            return await self._reject(context, action, "immutable_tool_version_not_found")
        if tool.tool_name != action.tool_name or tool.version != action.tool_version:
            return await self._reject(context, action, "immutable_tool_version_mismatch")
        if not await self._delegation.authorize(context, action, tool):
            return await self._reject(context, action, "delegation_denied_or_revoked")
        if action.operation not in tool.operations:
            return await self._reject(context, action, "operation_not_allowed")
        if not any(action.resource_scope.startswith(prefix) for prefix in tool.resource_prefixes):
            return await self._reject(context, action, "resource_scope_not_allowed")
        try:
            await self._schema_validator.validate(tool.input_schema, action.parameters.to_value())
        except ValueError:
            return await self._reject(context, action, "schema_or_semantic_validation_failed")
        if action.risk_level is not tool.risk_level:
            return await self._reject(
                context, action, "server_risk_reclassification_changed_digest"
            )
        if tool.risk_level is RiskLevel.L4_PRIVILEGED and not self._allow_l4:
            return await self._reject(context, action, "l4_default_deny")

        decision = await self._policy.authorize(context, action)
        if decision.policy_version != context.policy_version:
            return await self._reject(context, action, "policy_version_changed")
        if not decision.allowed:
            return await self._reject(context, action, decision.reason or "policy_denied")

        blocked = await self._kill_switch.is_blocked(
            KillSwitchQuery(
                tenant_id=str(action.tenant_id),
                agent_id=context.agent_id,
                tool_name=action.tool_name,
                operation=action.operation,
                provider=tool.provider,
            )
        )
        if blocked:
            return await self._reject(context, action, "kill_switch_active")

        if decision.requires_approval and not self._approval_is_exact(
            context, action, approval, decision
        ):
            return await self._reject(context, action, "approval_invalid_expired_or_stale")

        credential = await self._credentials.issue(context, action, tool)
        if credential.scope != tool.credential_scope or credential.expires_at <= datetime.now(UTC):
            return await self._reject(context, action, "credential_scope_or_expiry_invalid")

        reservation = await self._reservations.reserve(
            ExecutionReservation(
                tenant_id=str(action.tenant_id),
                run_id=str(action.run_id),
                action_id=str(action.action_id),
                tool_name=action.tool_name,
                tool_version=action.tool_version,
                idempotency_key=action.idempotency_key,
                request_digest=action.canonical_digest,
                cost_units=cost_units,
            )
        )
        if reservation.status is ReservationStatus.CONFLICT:
            raise ValueError("idempotency key was reused with a different request digest")
        if reservation.status is ReservationStatus.BUDGET_EXHAUSTED:
            return await self._reject(context, action, "budget_exhausted")
        if reservation.status in {ReservationStatus.IN_PROGRESS, ReservationStatus.UNKNOWN}:
            return await self._unknown(context, action, "execution_not_safe_to_retry")
        if reservation.status is ReservationStatus.CACHED:
            if reservation.receipt is None:
                raise RuntimeError("cached reservation is missing its receipt")
            result = self._result_from_receipt(action, reservation.receipt, cached=True)
            await self._record(context, result, "idempotency_cache_hit")
            return result
        if reservation.reservation_id is None:
            raise RuntimeError("acquired reservation has no identity")

        executing = action.transition_to(ActionStatus.AUTHORIZED).transition_to(
            ActionStatus.EXECUTING
        )
        try:
            receipt = await self._egress.execute(executing, tool, credential)
            if receipt.status is ToolResultStatus.SUCCEEDED:
                verified = await self._egress.verify(executing, tool, receipt)
                if not verified:
                    receipt = ToolReceipt(
                        receipt.external_id, ToolResultStatus.UNKNOWN, receipt.output
                    )
            elif receipt.status is ToolResultStatus.ACCEPTED:
                # Asynchronous acceptance is not evidence of the requested external effect.
                receipt = ToolReceipt(
                    receipt.external_id, ToolResultStatus.ACCEPTED, receipt.output
                )
        except TimeoutError:
            receipt = ToolReceipt("", ToolResultStatus.UNKNOWN, (("reason", "egress_timeout"),))
        except Exception as exc:  # executor failures are normalized at the boundary
            receipt = ToolReceipt("", ToolResultStatus.FAILED, (("reason", type(exc).__name__),))

        await self._reservations.complete(
            str(action.tenant_id), reservation.reservation_id, receipt
        )
        result = self._result_from_receipt(executing, receipt)
        await self._record(context, result, "external_execution_completed")
        return result

    @staticmethod
    def _approval_is_exact(
        context: AuthorizationContext,
        action: Action,
        approval: ApprovalRequest | None,
        decision: PolicyDecision,
    ) -> bool:
        return bool(
            approval is not None
            and approval.status is ApprovalStatus.APPROVED
            and approval.decided_by is not None
            and approval.required_role.strip()
            and approval.expires_at > datetime.now(UTC)
            and approval.policy_version == decision.policy_version
            and approval.authorizes(action, decision.policy_version)
            and context.policy_version == decision.policy_version
        )

    async def _reject(
        self, context: AuthorizationContext, action: Action, reason: str
    ) -> GatewayResult:
        result = GatewayResult(
            action.transition_to(ActionStatus.DENIED),
            ToolReceipt("", ToolResultStatus.REJECTED, (("reason", reason),)),
        )
        await self._record(context, result, reason)
        return result

    async def _unknown(
        self, context: AuthorizationContext, action: Action, reason: str
    ) -> GatewayResult:
        executing = action.transition_to(ActionStatus.AUTHORIZED).transition_to(
            ActionStatus.EXECUTING
        )
        result = GatewayResult(
            executing.transition_to(ActionStatus.UNKNOWN),
            ToolReceipt("", ToolResultStatus.UNKNOWN, (("reason", reason),)),
            cached=True,
        )
        await self._record(context, result, reason)
        return result

    @staticmethod
    def _result_from_receipt(
        action: Action, receipt: ToolReceipt, *, cached: bool = False
    ) -> GatewayResult:
        current = action
        if current.status in {ActionStatus.PROPOSED, ActionStatus.AWAITING_APPROVAL}:
            current = current.transition_to(ActionStatus.AUTHORIZED).transition_to(
                ActionStatus.EXECUTING
            )
        target = {
            ToolResultStatus.SUCCEEDED: ActionStatus.SUCCEEDED,
            ToolResultStatus.FAILED: ActionStatus.FAILED,
            ToolResultStatus.UNKNOWN: ActionStatus.UNKNOWN,
            ToolResultStatus.ACCEPTED: ActionStatus.UNKNOWN,
            ToolResultStatus.REJECTED: ActionStatus.FAILED,
        }[receipt.status]
        return GatewayResult(current.transition_to(target), receipt, cached)

    async def _record(
        self, context: AuthorizationContext, result: GatewayResult, reason: str
    ) -> None:
        await self._audit.record(
            GatewayAuditRecord(
                tenant_id=str(result.action.tenant_id),
                action_id=str(result.action.action_id),
                correlation_id=context.correlation_id,
                event="tool.execution",
                status=result.receipt.status,
                reason=reason,
                request_digest=result.action.canonical_digest,
                external_id=result.receipt.external_id,
            )
        )
