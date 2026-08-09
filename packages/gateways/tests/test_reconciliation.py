"""Tests for Tool reconciliation, timeout, and compensation."""

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from autonoesis_domain import Action, ActionStatus, RiskLevel
from autonoesis_gateways import (
    CompensationExecutor,
    ReconciliationResult,
    TimeoutWatchdog,
    UnknownReconciler,
)


def _make_action(**overrides: object) -> Action:
    defaults: dict[str, object] = {
        "tenant_id": uuid4(),
        "run_id": uuid4(),
        "task_id": uuid4(),
        "tool_name": "test-tool",
        "operation": "test-op",
        "resource_id": "res-1",
        "idempotency_key": "key-1",
        "expected_effect": "test effect",
        "risk_level": RiskLevel.L1_READ,
        "parameters": tuple(),
    }
    defaults.update({k: v for k, v in overrides.items() if v is not None})
    return Action(**defaults)  # type: ignore[arg-type]


class TestTimeoutWatchdog:
    @pytest.mark.asyncio
    async def test_action_past_deadline_becomes_unknown(self) -> None:
        action = _make_action()
        action = action.transition_to(ActionStatus.AUTHORIZED)
        action = action.transition_to(ActionStatus.EXECUTING)

        past = datetime.now(UTC) - timedelta(minutes=10)
        result = await TimeoutWatchdog.check(action, past)
        assert result.status is ActionStatus.UNKNOWN

    @pytest.mark.asyncio
    async def test_action_before_deadline_is_unchanged(self) -> None:
        action = _make_action()
        action = action.transition_to(ActionStatus.AUTHORIZED)
        action = action.transition_to(ActionStatus.EXECUTING)

        future = datetime.now(UTC) + timedelta(hours=1)
        result = await TimeoutWatchdog.check(action, future)
        assert result.status is ActionStatus.EXECUTING

    @pytest.mark.asyncio
    async def test_already_succeeded_action_unchanged(self) -> None:
        action = _make_action()
        action = action.transition_to(ActionStatus.AUTHORIZED)
        action = action.transition_to(ActionStatus.EXECUTING)
        action = action.transition_to(ActionStatus.SUCCEEDED)

        past = datetime.now(UTC) - timedelta(minutes=10)
        result = await TimeoutWatchdog.check(action, past)
        assert result.status is ActionStatus.SUCCEEDED

    @pytest.mark.asyncio
    async def test_no_deadline_leaves_action_unchanged(self) -> None:
        action = _make_action()
        action = action.transition_to(ActionStatus.AUTHORIZED)
        action = action.transition_to(ActionStatus.EXECUTING)

        result = await TimeoutWatchdog.check(action, None)
        assert result.status is ActionStatus.EXECUTING


class TestUnknownReconciler:
    @pytest.mark.asyncio
    async def test_reconcile_still_unknown_by_default(self) -> None:
        action = _make_action()
        action = action.transition_to(ActionStatus.AUTHORIZED)
        action = action.transition_to(ActionStatus.EXECUTING)
        action = action.transition_to(ActionStatus.UNKNOWN)

        reconciler = UnknownReconciler()
        updated, record = await reconciler.reconcile(action)

        assert updated.status is ActionStatus.UNKNOWN
        assert record.result is ReconciliationResult.STILL_UNKNOWN
        assert record.escalated is True

    @pytest.mark.asyncio
    async def test_reconcile_rejects_non_unknown(self) -> None:
        action = _make_action()
        action = action.transition_to(ActionStatus.AUTHORIZED)

        reconciler = UnknownReconciler()
        with pytest.raises(ValueError, match="only UNKNOWN actions"):
            await reconciler.reconcile(action)


class TestCompensationExecutor:
    @pytest.mark.asyncio
    async def test_compensate_fails_when_no_plan(self) -> None:
        action = _make_action()
        executor = CompensationExecutor()
        with pytest.raises(ValueError, match="no compensation plan"):
            await executor.compensate(action, "test", None)

    @pytest.mark.asyncio
    async def test_compensate_transitions_to_failed(self) -> None:
        action = _make_action()
        action = action.transition_to(ActionStatus.AUTHORIZED)
        action = action.transition_to(ActionStatus.EXECUTING)
        plan = {"steps": [{"undo": "test"}]}
        executor = CompensationExecutor()
        result = await executor.compensate(action, "test reason", plan)
        assert result.status is ActionStatus.FAILED
