"""Execution-time governance pipeline for external side effects."""

from dataclasses import dataclass
from typing import Protocol

from autonoesis_domain import Action, ActionStatus, ApprovalRequest, ApprovalStatus


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
    def __init__(
        self,
        policy: PolicyPort,
        budget: BudgetPort,
        idempotency: IdempotencyPort,
        executors: dict[str, ToolExecutor],
    ) -> None:
        self._policy = policy
        self._budget = budget
        self._idempotency = idempotency
        self._executors = executors

    async def execute(
        self,
        context: AuthorizationContext,
        action: Action,
        approval: ApprovalRequest | None,
        cost_units: int,
    ) -> tuple[Action, ToolReceipt]:
        if action.status not in {ActionStatus.PROPOSED, ActionStatus.AWAITING_APPROVAL}:
            raise ValueError("action is not executable from its current state")
        decision = await self._policy.authorize(context, action)
        if not decision.allowed:
            return action.transition_to(ActionStatus.DENIED), ToolReceipt("", False, ())
        if decision.requires_approval:
            if approval is None or approval.status is not ApprovalStatus.APPROVED:
                raise PermissionError("approved action parameters are required")
            if approval.action_digest != action.parameter_digest:
                raise PermissionError("approved parameters differ from execution parameters")
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
