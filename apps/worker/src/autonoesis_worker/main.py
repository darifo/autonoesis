"""Temporal worker process assembly."""

import argparse
import asyncio
import os
from collections.abc import Awaitable, Callable
from typing import Any

from temporalio.client import Client
from temporalio.worker import Worker

from autonoesis_worker.workflows import CandidateLifecycleWorkflow, GoalRunWorkflow


async def _placeholder_activity(command: object) -> str:
    raise RuntimeError(f"application activity is not configured for {type(command).__name__}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Autonoesis durable execution worker")
    parser.add_argument("--check", action="store_true", help="validate workflow registration")
    return parser


async def run_worker() -> None:
    target = os.getenv("AUTONOESIS_TEMPORAL_TARGET", "localhost:7233")
    namespace = os.getenv("AUTONOESIS_TEMPORAL_NAMESPACE", "default")
    task_queue = os.getenv("AUTONOESIS_TEMPORAL_TASK_QUEUE", "autonoesis")
    client = await Client.connect(target, namespace=namespace)
    activity_names = (
        "prepare_run",
        "cancel_run",
        "reject_run",
        "execute_run",
        "evaluate_run",
        "evaluate_candidate",
        "promote_candidate",
    )
    activities: list[Callable[..., Awaitable[Any]]] = []
    for name in activity_names:

        async def activity(command: object, activity_name: str = name) -> str:
            _ = activity_name
            return await _placeholder_activity(command)

        activity.__name__ = name
        activities.append(activity)
    worker = Worker(
        client,
        task_queue=task_queue,
        workflows=[GoalRunWorkflow, CandidateLifecycleWorkflow],
        activities=activities,
    )
    await worker.run()


def main() -> int:
    args = build_parser().parse_args()
    if args.check:
        print("autonoesis-worker workflows: GoalRunWorkflow, CandidateLifecycleWorkflow")
        return 0
    asyncio.run(run_worker())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
