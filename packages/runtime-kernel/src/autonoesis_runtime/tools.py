"""Execution-time governance pipeline for external side effects."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Protocol
from uuid import UUID, uuid4

from autonoesis_domain import Action, ActionStatus, ApprovalRequest, ApprovalStatus


class KillSwitchDimension(StrEnum):
    """The six dimensions at which a kill switch can be activated."""

    TENANT = "tenant"
    AGENT = "agent"
    TOOL = "tool"
    OPERATION = "operation"
    PROVIDER = "provider"
    CAPABILITY_PACK = "capability_pack"


@dataclass(frozen=True, slots=True)
class KillSwitchQuery:
    """Keys used to check whether a context is blocked by any active kill switch."""

    tenant_id: str | None = None
    agent_id: str | None = None
    tool_name: str | None = None
    operation: str | None = None
    provider: str | None = None
    capability_pack_id: str | None = None

    def dimensions(self) -> list[tuple[KillSwitchDimension, str]]:
        pairs: list[tuple[KillSwitchDimension, str]] = []
        if self.tenant_id is not None:
            pairs.append((KillSwitchDimension.TENANT, self.tenant_id))
        if self.agent_id is not None:
            pairs.append((KillSwitchDimension.AGENT, self.agent_id))
        if self.tool_name is not None:
            pairs.append((KillSwitchDimension.TOOL, self.tool_name))
        if self.operation is not None:
            pairs.append((KillSwitchDimension.OPERATION, self.operation))
        if self.provider is not None:
            pairs.append((KillSwitchDimension.PROVIDER, self.provider))
        if self.capability_pack_id is not None:
            pairs.append((KillSwitchDimension.CAPABILITY_PACK, self.capability_pack_id))
        return pairs


class KillSwitchPort(Protocol):
    """Contract for querying kill switch state."""

    async def is_blocked(self, query: KillSwitchQuery) -> bool:
        """Return True when any dimension in *query* matches an active switch."""

    async def activate(
        self,
        dimension: KillSwitchDimension,
        target: str,
        reason: str,
        activated_by: str,
    ) -> KillSwitchRecord:
        """Activate a kill switch for *dimension*:*target*."""

    async def deactivate(
        self,
        dimension: KillSwitchDimension,
        target: str,
    ) -> KillSwitchRecord | None:
        """Deactivate the kill switch for *dimension*:*target*."""

    async def list_active(self) -> tuple[KillSwitchRecord, ...]:
        """Return all currently active kill switches."""


@dataclass(frozen=True, slots=True)
class KillSwitchRecord:
    """An active kill switch entry."""

    kill_switch_id: UUID = field(default_factory=uuid4)
    dimension: KillSwitchDimension = KillSwitchDimension.TENANT
    target: str = ""
    reason: str = ""
    activated_by: str = ""
    activated_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    deactivated_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class AuthorizationContext:
    tenant_id: str
    actor_id: str
    principal_id: str
    agent_id: str
    roles: tuple[str, ...]
    policy_version: str


@dataclass(frozen=True, slots=True)
class PolicyDecision:
    allowed: bool
    requires_approval: bool
    reason: str


@dataclass(frozen=True, slots=True)
class ToolReceipt:
    external_id: str
    accepted: bool
    output: tuple[tuple[str, str], ...]


class PolicyPort(Protocol):
    async def authorize(self, context: AuthorizationContext, action: Action) -> PolicyDecision: ...


class BudgetPort(Protocol):
    async def reserve(self, tenant_id: str, run_id: str, units: int) -> bool: ...


class ToolExecutor(Protocol):
    async def execute(self, action: Action) -> ToolReceipt: ...

    async def verify(self, action: Action, receipt: ToolReceipt) -> bool: ...


class IdempotencyPort(Protocol):
    async def get(self, key: str) -> ToolReceipt | None: ...

    async def put(self, key: str, receipt: ToolReceipt) -> None: ...


class GovernedToolGateway:
    """Enforces identity, policy, budget, idempotency, and kill-switch
    checks before executing any external side effect.

    Execution pipeline (in order):
    1. Validate action state (PROPOSED or AWAITING_APPROVAL)
    2. Kill Switch gate — deny if any matching switch is active
    3. Policy decision — deny if policy says no
    4. Approval check — require validated approval if policy demands it
    5. Budget reservation — fail if run budget is exhausted
    6. Idempotency check — return cached receipt for duplicate keys
    7. Executor lookup — fail if no executor registered for the tool
    8. Execute + verify — return SUCCEEDED or UNKNOWN

    Returns:
        (updated Action, ToolReceipt).  The Action status will be one of:
        - SUCCEEDED: side effect confirmed
        - DENIED: blocked by kill switch or policy
        - UNKNOWN: executed but verification failed (caller must reconcile)
    """

    def __init__(
        self,
        policy: PolicyPort,
        budget: BudgetPort,
        idempotency: IdempotencyPort,
        executors: dict[str, ToolExecutor],
        *,
        kill_switch: KillSwitchPort | None = None,
    ) -> None:
        self._policy = policy
        self._budget = budget
        self._idempotency = idempotency
        self._executors = executors
        self._kill_switch = kill_switch

    async def execute(
        self,
        context: AuthorizationContext,
        action: Action,
        approval: ApprovalRequest | None,
        cost_units: int,
    ) -> tuple[Action, ToolReceipt]:
        if action.status not in {ActionStatus.PROPOSED, ActionStatus.AWAITING_APPROVAL}:
            raise ValueError("action is not executable from its current state")
        if context.tenant_id != str(action.tenant_id):
            raise PermissionError("authorization tenant differs from action tenant")

        # ── Kill Switch gate ──────────────────────────────────────────
        if self._kill_switch is not None:
            blocked = await self._kill_switch.is_blocked(
                KillSwitchQuery(
                    tenant_id=str(action.tenant_id),
                    agent_id=context.agent_id,
                    tool_name=action.tool_name,
                    operation=action.operation,
                )
            )
            if blocked:
                reason = "kill_switch_active"
                return action.transition_to(ActionStatus.DENIED), ToolReceipt(
                    external_id="", accepted=False, output=(("reason", reason),)
                )

        decision = await self._policy.authorize(context, action)
        if not decision.allowed:
            return action.transition_to(ActionStatus.DENIED), ToolReceipt("", False, ())
        if decision.requires_approval:
            if approval is None or approval.status is not ApprovalStatus.APPROVED:
                raise PermissionError("approved action parameters are required")
            if not approval.authorizes(action, context.policy_version):
                raise PermissionError("approval does not bind the executable action")
        if not await self._budget.reserve(str(action.tenant_id), str(action.run_id), cost_units):
            raise PermissionError("run budget is exhausted")
        existing = await self._idempotency.get(action.idempotency_key)
        if existing is not None:
            return action.transition_to(ActionStatus.AUTHORIZED).transition_to(
                ActionStatus.EXECUTING
            ).transition_to(ActionStatus.SUCCEEDED), existing
        executor = self._executors.get(action.tool_name)
        if executor is None:
            raise LookupError("tool executor is not registered")
        executing = action
        if executing.status in {
            ActionStatus.AWAITING_APPROVAL,
            ActionStatus.PROPOSED,
        }:
            executing = executing.transition_to(ActionStatus.AUTHORIZED)
        executing = executing.transition_to(ActionStatus.EXECUTING)
        receipt = await executor.execute(executing)
        if not receipt.accepted or not await executor.verify(executing, receipt):
            return executing.transition_to(ActionStatus.UNKNOWN), receipt
        await self._idempotency.put(action.idempotency_key, receipt)
        return executing.transition_to(ActionStatus.SUCCEEDED), receipt
