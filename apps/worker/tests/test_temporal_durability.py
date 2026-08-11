"""Real Temporal durability, control-signal, Continue-as-New, and Replay tests."""

import asyncio
import os
from collections import defaultdict
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

import pytest
from autonoesis_worker.contracts import (
    ApprovalLookupInput,
    ApprovalState,
    CancelRunInput,
    EvaluateRunInput,
    ExecuteRunInput,
    GoalRunInput,
    PrepareRunInput,
    RejectRunInput,
    TakeOverRunInput,
)
from autonoesis_worker.workflows import GoalRunWorkflow
from temporalio import activity
from temporalio.client import Client, WorkflowHandle
from temporalio.worker import Replayer, Worker
from temporalio.worker.workflow_sandbox import SandboxedWorkflowRunner

pytestmark = pytest.mark.skipif(
    not os.getenv("AUTONOESIS_TEST_TEMPORAL_TARGET"),
    reason="requires an explicitly configured Temporal component endpoint",
)

_calls: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
_execute_started: dict[str, asyncio.Event] = {}
_prepare_started: dict[str, asyncio.Event] = {}
_continuation_runs: set[str] = set()
_approval_ids: dict[str, list[str]] = defaultdict(list)


@activity.defn(name="prepare_run")
async def temporal_prepare(input: PrepareRunInput) -> str:
    _calls[input.run_id]["prepare"] += 1
    event = _prepare_started.get(input.run_id)
    if event is not None:
        event.set()
        await asyncio.sleep(0.2)
    return "planned"


@activity.defn(name="load_approval")
async def temporal_load_approval(input: ApprovalLookupInput) -> ApprovalState:
    _calls[input.run_id]["approval"] += 1
    _approval_ids[input.run_id].append(input.approval_id)
    return ApprovalState(input.approval_id, "approved")


@activity.defn(name="execute_run")
async def temporal_execute(input: ExecuteRunInput) -> str:
    _calls[input.run_id]["execute"] += 1
    event = _execute_started.get(input.run_id)
    if event is not None:
        event.set()
        await asyncio.sleep(0.2)
    return "dispatched"


@activity.defn(name="evaluate_run")
async def temporal_evaluate(input: EvaluateRunInput) -> str:
    _calls[input.run_id]["evaluate"] += 1
    if input.run_id in _continuation_runs and _calls[input.run_id]["evaluate"] == 1:
        return "running"
    return "succeeded"


@activity.defn(name="cancel_run")
async def temporal_cancel(input: CancelRunInput) -> str:
    _calls[input.run_id]["cancel"] += 1
    return "cancelled"


@activity.defn(name="reject_run")
async def temporal_reject(input: RejectRunInput) -> str:
    _calls[input.run_id]["reject"] += 1
    return "rejected"


@activity.defn(name="take_over_run")
async def temporal_takeover(input: TakeOverRunInput) -> str:
    _calls[input.run_id]["takeover"] += 1
    return "taken_over"


_ACTIVITIES: list[Callable[..., Any]] = [
    temporal_prepare,
    temporal_load_approval,
    temporal_execute,
    temporal_evaluate,
    temporal_cancel,
    temporal_reject,
    temporal_takeover,
]


def _input(run_id: str, *, approval: bool = False) -> GoalRunInput:
    return GoalRunInput(
        str(uuid4()),
        str(uuid4()),
        run_id,
        (datetime.now(UTC) + timedelta(minutes=5)).timestamp(),
        requires_approval=approval,
    )


async def _wait_phase(handle: WorkflowHandle[GoalRunWorkflow, str], phase: str) -> None:
    for _ in range(100):
        if await handle.query(GoalRunWorkflow.current_phase) == phase:
            return
        await asyncio.sleep(0.02)
    raise AssertionError(f"workflow did not reach {phase}")


@pytest.mark.asyncio
async def test_approval_wait_survives_worker_restart_and_history_replays() -> None:
    client = await Client.connect(os.environ["AUTONOESIS_TEST_TEMPORAL_TARGET"])
    task_queue = f"p006-restart-{uuid4()}"
    run_id = str(uuid4())
    workflow_id = f"p006-restart-{run_id}"

    async with Worker(
        client,
        task_queue=task_queue,
        workflows=[GoalRunWorkflow],
        activities=_ACTIVITIES,
        workflow_runner=SandboxedWorkflowRunner(),
    ):
        handle = await client.start_workflow(
            GoalRunWorkflow.run,
            _input(run_id, approval=True),
            id=workflow_id,
            task_queue=task_queue,
        )
        await _wait_phase(handle, "awaiting_approval")

    # Signal while no Worker is polling; Temporal persists the Approval ID in history.
    await handle.signal(GoalRunWorkflow.approval_decided, "approval-authoritative-1")

    async with Worker(
        client,
        task_queue=task_queue,
        workflows=[GoalRunWorkflow],
        activities=_ACTIVITIES,
        workflow_runner=SandboxedWorkflowRunner(),
    ):
        assert await handle.result() == "succeeded"

    assert _approval_ids[run_id] == ["approval-authoritative-1"]
    assert _calls[run_id]["execute"] == 1
    history = await handle.fetch_history()
    await Replayer(workflows=[GoalRunWorkflow]).replay_workflow(history)


@pytest.mark.asyncio
async def test_cancel_during_write_waits_for_activity_and_never_retries_it() -> None:
    client = await Client.connect(os.environ["AUTONOESIS_TEST_TEMPORAL_TARGET"])
    task_queue = f"p006-cancel-{uuid4()}"
    run_id = str(uuid4())
    _execute_started[run_id] = asyncio.Event()
    async with Worker(
        client,
        task_queue=task_queue,
        workflows=[GoalRunWorkflow],
        activities=_ACTIVITIES,
        workflow_runner=SandboxedWorkflowRunner(),
    ):
        handle = await client.start_workflow(
            GoalRunWorkflow.run,
            _input(run_id),
            id=f"p006-cancel-{run_id}",
            task_queue=task_queue,
        )
        await asyncio.wait_for(_execute_started[run_id].wait(), timeout=5)
        await handle.signal(GoalRunWorkflow.cancel, "operator cancellation")
        assert await handle.result() == "cancelled"

    assert _calls[run_id]["execute"] == 1
    assert _calls[run_id]["evaluate"] == 0
    assert _calls[run_id]["cancel"] == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("stage", ["planning", "awaiting_approval"])
async def test_cancel_before_execution_has_deterministic_semantics(stage: str) -> None:
    client = await Client.connect(os.environ["AUTONOESIS_TEST_TEMPORAL_TARGET"])
    task_queue = f"p006-cancel-before-{uuid4()}"
    run_id = str(uuid4())
    if stage == "planning":
        _prepare_started[run_id] = asyncio.Event()
    async with Worker(
        client,
        task_queue=task_queue,
        workflows=[GoalRunWorkflow],
        activities=_ACTIVITIES,
        workflow_runner=SandboxedWorkflowRunner(),
    ):
        handle = await client.start_workflow(
            GoalRunWorkflow.run,
            _input(run_id, approval=stage == "awaiting_approval"),
            id=f"p006-cancel-before-{run_id}",
            task_queue=task_queue,
        )
        if stage == "planning":
            await asyncio.wait_for(_prepare_started[run_id].wait(), timeout=5)
        else:
            await _wait_phase(handle, "awaiting_approval")
        await handle.signal(GoalRunWorkflow.cancel, f"cancel during {stage}")
        assert await handle.result() == "cancelled"

    assert _calls[run_id]["execute"] == 0
    assert _calls[run_id]["cancel"] == 1


@pytest.mark.asyncio
async def test_external_progress_continues_as_new_without_replanning() -> None:
    client = await Client.connect(os.environ["AUTONOESIS_TEST_TEMPORAL_TARGET"])
    task_queue = f"p006-continue-{uuid4()}"
    run_id = str(uuid4())
    _continuation_runs.add(run_id)
    async with Worker(
        client,
        task_queue=task_queue,
        workflows=[GoalRunWorkflow],
        activities=_ACTIVITIES,
        workflow_runner=SandboxedWorkflowRunner(),
    ):
        handle = await client.start_workflow(
            GoalRunWorkflow.run,
            _input(run_id),
            id=f"p006-continue-{run_id}",
            task_queue=task_queue,
        )
        await _wait_phase(handle, "waiting_for_progress")
        await handle.signal(GoalRunWorkflow.pause)
        await _wait_phase(handle, "paused")
        await handle.signal(GoalRunWorkflow.resume)
        assert await handle.result(follow_runs=True) == "succeeded"

    assert _calls[run_id]["prepare"] == 1
    assert _calls[run_id]["execute"] == 2
    assert _calls[run_id]["evaluate"] == 2
