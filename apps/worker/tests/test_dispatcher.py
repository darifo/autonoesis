"""Tests for recoverable Outbox dispatch and DB/Temporal reconciliation."""

from datetime import UTC, datetime, timedelta

import pytest
from autonoesis_worker.contracts import GoalRunInput
from autonoesis_worker.dispatcher import (
    ReconciliationRun,
    RunDispatchRequest,
    RunWorkflowDispatcher,
    RunWorkflowReconciler,
    WorkflowObservation,
    workflow_id_for_run,
)


def command(run_id: str = "run-1") -> GoalRunInput:
    return GoalRunInput(
        "tenant-1",
        "goal-1",
        run_id,
        (datetime.now(UTC) + timedelta(hours=1)).timestamp(),
    )


class MemoryDispatchStore:
    def __init__(self) -> None:
        self.pending = [RunDispatchRequest("event-1", command())]
        self.active = [ReconciliationRun(command(), "pending")]
        self.mark_failures = 0

    async def list_pending(self, limit: int) -> tuple[RunDispatchRequest, ...]:
        return tuple(self.pending[:limit])

    async def mark_dispatched(self, event_id: str) -> None:
        if self.mark_failures:
            self.mark_failures -= 1
            raise RuntimeError("injected mark failure")
        self.pending = [item for item in self.pending if item.event_id != event_id]

    async def list_reconciliation_runs(self, limit: int) -> tuple[ReconciliationRun, ...]:
        return tuple(self.active[:limit])


class MemoryWorkflowControl:
    def __init__(self) -> None:
        self.failures = 0
        self.start_calls = 0
        self.started: set[str] = set()
        self.observations: dict[str, WorkflowObservation] = {}

    async def start(self, item: GoalRunInput) -> str:
        self.start_calls += 1
        if self.failures:
            self.failures -= 1
            raise ConnectionError("Temporal unavailable")
        workflow_id = workflow_id_for_run(item.run_id)
        self.started.add(workflow_id)
        self.observations[workflow_id] = WorkflowObservation(True, True, "running")
        return workflow_id

    async def observe(self, workflow_id: str) -> WorkflowObservation:
        return self.observations.get(workflow_id, WorkflowObservation(False, False, "not_found"))


@pytest.mark.asyncio
async def test_failed_start_leaves_outbox_for_recovery() -> None:
    store = MemoryDispatchStore()
    workflows = MemoryWorkflowControl()
    workflows.failures = 1
    dispatcher = RunWorkflowDispatcher(store, workflows)

    assert await dispatcher.poll_once() == 0
    assert len(store.pending) == 1
    assert await dispatcher.poll_once() == 1
    assert store.pending == []
    assert workflows.started == {"goal-run-run-1"}


@pytest.mark.asyncio
async def test_fixed_id_deduplicates_when_start_succeeds_before_outbox_mark() -> None:
    store = MemoryDispatchStore()
    store.mark_failures = 1
    workflows = MemoryWorkflowControl()
    dispatcher = RunWorkflowDispatcher(store, workflows)

    with pytest.raises(RuntimeError, match="mark failure"):
        await dispatcher.poll_once()
    assert await dispatcher.poll_once() == 1
    assert workflows.start_calls == 2
    assert workflows.started == {"goal-run-run-1"}


@pytest.mark.asyncio
async def test_reconciler_recovers_missing_and_reports_closed_workflow() -> None:
    store = MemoryDispatchStore()
    workflows = MemoryWorkflowControl()
    reconciler = RunWorkflowReconciler(store, workflows)

    recovered = await reconciler.reconcile_once()
    assert recovered[0].kind == "missing_workflow"
    assert recovered[0].recovered is True

    workflows.observations["goal-run-run-1"] = WorkflowObservation(True, False, "failed")
    finding = await reconciler.reconcile_once()
    assert finding[0].kind == "closed_workflow_with_active_run"
    assert finding[0].recovered is False
    assert "Temporal=failed" in finding[0].detail

    store.active = [ReconciliationRun(command(), "cancelled")]
    workflows.observations["goal-run-run-1"] = WorkflowObservation(True, True, "running")
    reverse = await reconciler.reconcile_once()
    assert reverse[0].kind == "running_workflow_with_terminal_or_manual_run"
