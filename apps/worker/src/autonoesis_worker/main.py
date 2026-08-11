"""Temporal worker process assembly with real activity implementations."""

import argparse
import asyncio
import os

from autonoesis_adapters import PostgreSQLPlatformStore
from autonoesis_application import CandidateLifecycleService
from temporalio import activity
from temporalio.client import Client
from temporalio.worker import UnsandboxedWorkflowRunner, Worker

from autonoesis_worker.activities import (
    CancelRunInput,
    EvaluateCandidateInput,
    EvaluateRunInput,
    ExecuteRunInput,
    PrepareRunInput,
    PromoteCandidateInput,
    RejectRunInput,
    cancel_run,
    evaluate_candidate,
    evaluate_run,
    execute_run,
    prepare_run,
    promote_candidate,
    reject_run,
)
from autonoesis_worker.workflows import (
    CandidateLifecycleWorkflow,
    GoalRunWorkflow,
)

_process_store: PostgreSQLPlatformStore | None = None


def _get_store() -> PostgreSQLPlatformStore:
    global _process_store
    if _process_store is None:
        database_url = os.environ["AUTONOESIS_DATABASE_URL"]
        _process_store = PostgreSQLPlatformStore.from_url(database_url)
    return _process_store


@activity.defn(name="prepare_run")
async def _prepare(input: PrepareRunInput) -> str:
    return await prepare_run(input, _get_store())


@activity.defn(name="cancel_run")
async def _cancel(input: CancelRunInput) -> str:
    return await cancel_run(input, _get_store())


@activity.defn(name="reject_run")
async def _reject(input: RejectRunInput) -> str:
    return await reject_run(input, _get_store())


@activity.defn(name="execute_run")
async def _execute(input: ExecuteRunInput) -> str:
    return await execute_run(input, _get_store())


@activity.defn(name="evaluate_run")
async def _evaluate(input: EvaluateRunInput) -> str:
    return await evaluate_run(input, _get_store())


@activity.defn(name="evaluate_candidate")
async def _evaluate_candidate(input: EvaluateCandidateInput) -> bool:
    store = _get_store()
    evolution = CandidateLifecycleService(store)
    return await evaluate_candidate(input, store, evolution)


@activity.defn(name="promote_candidate")
async def _promote(input: PromoteCandidateInput) -> str:
    store = _get_store()
    evolution = CandidateLifecycleService(store)
    return await promote_candidate(input, store, evolution)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Autonoesis durable execution worker")
    parser.add_argument("--check", action="store_true", help="validate workflow registration")
    return parser


async def run_worker() -> None:
    target = os.getenv("AUTONOESIS_TEMPORAL_TARGET", "localhost:7233")
    namespace = os.getenv("AUTONOESIS_TEMPORAL_NAMESPACE", "default")
    task_queue = os.getenv("AUTONOESIS_TEMPORAL_TASK_QUEUE", "autonoesis")
    client = await Client.connect(target, namespace=namespace)

    worker = Worker(
        client,
        task_queue=task_queue,
        workflows=[GoalRunWorkflow, CandidateLifecycleWorkflow],
        workflow_runner=UnsandboxedWorkflowRunner(),
        activities=[
            _prepare,
            _cancel,
            _reject,
            _execute,
            _evaluate,
            _evaluate_candidate,
            _promote,
        ],
    )
    try:
        await worker.run()
    finally:
        if _process_store is not None:
            await _process_store.close()


def main() -> int:
    args = build_parser().parse_args()
    if args.check:
        print("autonoesis-worker workflows: GoalRunWorkflow, CandidateLifecycleWorkflow")
        return 0
    asyncio.run(run_worker())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
