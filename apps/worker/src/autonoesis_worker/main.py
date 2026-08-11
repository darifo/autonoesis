"""Temporal worker process assembly with real activity implementations."""

import argparse
import asyncio
import os

from autonoesis_adapters import PostgreSQLPlatformStore
from autonoesis_application import CandidateLifecycleService
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from temporalio import activity
from temporalio.client import Client
from temporalio.worker import Worker
from temporalio.worker.workflow_sandbox import SandboxedWorkflowRunner

from autonoesis_worker.activities import (
    ActivityDependencies,
    build_activity_dependencies,
    cancel_run,
    evaluate_candidate,
    evaluate_run,
    execute_run,
    load_approval,
    prepare_run,
    promote_candidate,
    reject_run,
    take_over_run,
)
from autonoesis_worker.contracts import (
    ApprovalLookupInput,
    ApprovalState,
    CancelRunInput,
    EvaluateCandidateInput,
    EvaluateRunInput,
    ExecuteRunInput,
    PrepareRunInput,
    PromoteCandidateInput,
    RejectRunInput,
    TakeOverRunInput,
)
from autonoesis_worker.dispatcher import (
    PostgreSQLRunDispatchStore,
    RunWorkflowDispatcher,
    RunWorkflowReconciler,
    TemporalRunWorkflowControl,
    run_dispatch_and_reconcile_loop,
)
from autonoesis_worker.workflows import (
    CandidateLifecycleWorkflow,
    GoalRunWorkflow,
)

_process_dependencies: ActivityDependencies | None = None


def _get_dependencies() -> ActivityDependencies:
    global _process_dependencies
    if _process_dependencies is None:
        database_url = os.environ["AUTONOESIS_DATABASE_URL"]
        store = PostgreSQLPlatformStore.from_url(database_url)
        _process_dependencies = build_activity_dependencies(store, CandidateLifecycleService(store))
    return _process_dependencies


@activity.defn(name="prepare_run")
async def _prepare(input: PrepareRunInput) -> str:
    return await prepare_run(input, _get_dependencies())


@activity.defn(name="cancel_run")
async def _cancel(input: CancelRunInput) -> str:
    return await cancel_run(input, _get_dependencies())


@activity.defn(name="reject_run")
async def _reject(input: RejectRunInput) -> str:
    return await reject_run(input, _get_dependencies())


@activity.defn(name="take_over_run")
async def _take_over(input: TakeOverRunInput) -> str:
    return await take_over_run(input, _get_dependencies())


@activity.defn(name="load_approval")
async def _load_approval(input: ApprovalLookupInput) -> ApprovalState:
    return await load_approval(input, _get_dependencies())


@activity.defn(name="execute_run")
async def _execute(input: ExecuteRunInput) -> str:
    return await execute_run(input, _get_dependencies())


@activity.defn(name="evaluate_run")
async def _evaluate(input: EvaluateRunInput) -> str:
    return await evaluate_run(input, _get_dependencies())


@activity.defn(name="evaluate_candidate")
async def _evaluate_candidate(input: EvaluateCandidateInput) -> bool:
    return await evaluate_candidate(input, _get_dependencies())


@activity.defn(name="promote_candidate")
async def _promote(input: PromoteCandidateInput) -> str:
    return await promote_candidate(input, _get_dependencies())


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Autonoesis durable execution worker")
    parser.add_argument("--check", action="store_true", help="validate workflow registration")
    return parser


async def run_worker() -> None:
    target = os.getenv("AUTONOESIS_TEMPORAL_TARGET", "localhost:7233")
    namespace = os.getenv("AUTONOESIS_TEMPORAL_NAMESPACE", "default")
    task_queue = os.getenv("AUTONOESIS_TEMPORAL_TASK_QUEUE", "autonoesis")
    client = await Client.connect(target, namespace=namespace)
    dispatch_database_url = os.environ["AUTONOESIS_DISPATCH_DATABASE_URL"]
    dispatch_engine = create_async_engine(dispatch_database_url, pool_pre_ping=True)
    dispatch_store = PostgreSQLRunDispatchStore(
        async_sessionmaker(dispatch_engine, expire_on_commit=False)
    )
    workflow_control = TemporalRunWorkflowControl(client, task_queue)
    dispatcher = RunWorkflowDispatcher(dispatch_store, workflow_control)
    reconciler = RunWorkflowReconciler(dispatch_store, workflow_control)

    worker = Worker(
        client,
        task_queue=task_queue,
        workflows=[GoalRunWorkflow, CandidateLifecycleWorkflow],
        workflow_runner=SandboxedWorkflowRunner(),
        activities=[
            _prepare,
            _cancel,
            _reject,
            _take_over,
            _load_approval,
            _execute,
            _evaluate,
            _evaluate_candidate,
            _promote,
        ],
    )
    try:
        async with asyncio.TaskGroup() as group:
            group.create_task(worker.run())
            group.create_task(run_dispatch_and_reconcile_loop(dispatcher, reconciler))
    finally:
        await dispatch_engine.dispose()
        if _process_dependencies is not None and isinstance(
            _process_dependencies.store, PostgreSQLPlatformStore
        ):
            await _process_dependencies.store.close()


def main() -> int:
    args = build_parser().parse_args()
    if args.check:
        print("autonoesis-worker workflows: GoalRunWorkflow, CandidateLifecycleWorkflow")
        return 0
    asyncio.run(run_worker())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
