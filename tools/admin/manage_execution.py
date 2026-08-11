"""Invoke operational execution transitions through the shared Application use cases."""

import argparse
import asyncio
import os
from hashlib import sha256
from uuid import UUID, uuid4

from autonoesis_adapters import PostgreSQLPlatformStore
from autonoesis_application import (
    ActivateGoal,
    CancelRun,
    CommandContext,
    FailRun,
    GoalExecutionApplication,
    IdentityContext,
    TakeOverRun,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "operation", choices=("activate-goal", "cancel-run", "fail-run", "take-over-run")
    )
    parser.add_argument("--tenant-id", type=UUID, required=True)
    parser.add_argument("--actor-id", type=UUID, required=True)
    parser.add_argument("--object-id", type=UUID, required=True)
    parser.add_argument("--reason", required=True)
    parser.add_argument("--idempotency-key", required=True)
    parser.add_argument("--correlation-id", type=UUID, default=None)
    return parser


async def run(args: argparse.Namespace) -> str:
    store = PostgreSQLPlatformStore.from_url(os.environ["AUTONOESIS_DATABASE_URL"])
    correlation_id = args.correlation_id or uuid4()
    context = CommandContext(
        IdentityContext(
            args.tenant_id,
            args.actor_id,
            args.actor_id,
            frozenset({"platform_admin"}),
        ),
        correlation_id,
        correlation_id,
        args.idempotency_key,
        sha256(f"{args.operation}\n{args.object_id}\n{args.reason}".encode()).hexdigest(),
    )
    application = GoalExecutionApplication(store.repository, store)
    try:
        if args.operation == "activate-goal":
            result = await application.activate_goal(
                context, ActivateGoal(args.object_id, args.reason)
            )
            return f"goal {result.goal_id}: {result.status.value}"
        if args.operation == "cancel-run":
            result = await application.cancel_run(context, CancelRun(args.object_id, args.reason))
        elif args.operation == "fail-run":
            result = await application.fail_run(context, FailRun(args.object_id, args.reason))
        else:
            result = await application.take_over_run(
                context, TakeOverRun(args.object_id, args.reason)
            )
        return f"run {result.run_id}: {result.status.value}"
    finally:
        await store.close()


def main() -> int:
    print(asyncio.run(run(build_parser().parse_args())))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
