"""Tool timeout, unknown reconciliation, and compensation logic.

See docs/runbooks/action-unknown.md for the reconciliation procedure.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any
from uuid import UUID, uuid4

from autonoesis_domain import Action, ActionStatus


class ReconciliationResult(StrEnum):
    """Outcome of reconciling an UNKNOWN action."""

    SUCCEEDED = "succeeded"  # side effect confirmed, action → SUCCEEDED
    FAILED = "failed"  # side effect confirmed absent, action → FAILED
    STILL_UNKNOWN = "still_unknown"  # cannot determine, escalate


@dataclass(frozen=True, slots=True)
class ReconciliationRecord:
    """Result of a reconciliation attempt."""

    reconciliation_id: UUID = field(default_factory=uuid4)
    action_id: UUID = field(default_factory=uuid4)
    result: ReconciliationResult = ReconciliationResult.STILL_UNKNOWN
    evidence_source: str = ""
    evidence_reference: str = ""
    observed_state: str = ""
    escalated: bool = False
    resolved_at: datetime = field(default_factory=lambda: datetime.now(UTC))


class TimeoutWatchdog:
    """Monitors Actions for deadline breaches and transitions them to UNKNOWN.

    The deadline comes from the Run or GoalContract, not the Action itself.
    """

    @staticmethod
    async def check(action: Action, deadline: datetime | None = None) -> Action:
        """If *action* is past *deadline* and still executing, mark UNKNOWN."""
        now = datetime.now(UTC)
        if (
            deadline is not None
            and now > deadline
            and action.status
            in {ActionStatus.PROPOSED, ActionStatus.AUTHORIZED, ActionStatus.EXECUTING}
        ):
            return action.transition_to(ActionStatus.UNKNOWN)
        return action

    @staticmethod
    async def with_timeout(
        coro: Awaitable[Any],
        timeout_seconds: float,
        on_timeout: Action | None = None,
    ) -> Action | None:
        """Run *coro* with a timeout; return the UNKNOWN action on timeout."""
        try:
            await asyncio.wait_for(coro, timeout=timeout_seconds)
            return None
        except TimeoutError:
            return on_timeout.transition_to(ActionStatus.UNKNOWN) if on_timeout else None


class UnknownReconciler:
    """Implements the three-case reconciliation procedure from the runbook.

    Case 1: side effect DID occur → Evidence → SUCCEEDED
    Case 2: side effect did NOT occur → retry or FAILED
    Case 3: cannot determine → escalate to human
    """

    async def reconcile(
        self,
        action: Action,
        *,
        check_external: bool = True,
        idempotency_check: bool = True,
    ) -> tuple[Action, ReconciliationRecord]:
        """Attempt to resolve an UNKNOWN action.

        Returns the updated Action and a ReconciliationRecord.
        """
        if action.status is not ActionStatus.UNKNOWN:
            raise ValueError("only UNKNOWN actions can be reconciled")

        # Case 1: Check external system for evidence of the side effect.
        if check_external:
            evidence = await self._check_external_effect(action)
            if evidence is not None:
                return (
                    action.transition_to(ActionStatus.SUCCEEDED),
                    ReconciliationRecord(
                        action_id=action.action_id,
                        result=ReconciliationResult.SUCCEEDED,
                        evidence_source="external_system",
                        evidence_reference=evidence,
                        observed_state="side_effect_confirmed",
                    ),
                )

        # Case 2: Side effect did not occur — retry if idempotent.
        if idempotency_check:
            confirmed_absent = await self._confirm_no_side_effect(action)
            if confirmed_absent:
                return (
                    action.transition_to(ActionStatus.FAILED),
                    ReconciliationRecord(
                        action_id=action.action_id,
                        result=ReconciliationResult.FAILED,
                        evidence_source="external_system",
                        evidence_reference="idempotency_check",
                        observed_state="no_side_effect",
                    ),
                )

        # Case 3: Cannot determine — escalate.
        return (
            action,
            ReconciliationRecord(
                action_id=action.action_id,
                result=ReconciliationResult.STILL_UNKNOWN,
                escalated=True,
            ),
        )

    async def _check_external_effect(self, action: Action) -> str | None:
        """Query the external system for the side effect.

        Override in subclasses with real system queries.
        """
        _ = action
        return None

    async def _confirm_no_side_effect(self, action: Action) -> bool:
        """Verify the side effect definitely did not occur.

        Override in subclasses with real system queries.
        """
        _ = action
        return False


class CompensationExecutor:
    """Executes predefined compensation plans for partial side effects.

    The compensation plan is stored in the ToolDefinition (not the Action).
    """

    async def compensate(
        self, action: Action, reason: str, plan: dict[str, Any] | None = None
    ) -> Action:
        """Execute the compensation *plan* for *action*.

        Returns the compensated Action (status → FAILED after compensation).
        """
        if plan is None:
            raise ValueError(f"no compensation plan provided for action {action.action_id}")

        # In a full implementation this would:
        # 1. Execute each step of the plan with idempotency
        # 2. Record evidence of compensation
        # 3. Transition the action to FAILED
        _ = reason
        _ = plan
        return action.transition_to(ActionStatus.FAILED)
