"""Durable Goal and Candidate lifecycle workflows."""

from dataclasses import dataclass
from datetime import timedelta

from temporalio import workflow
from temporalio.common import RetryPolicy


@dataclass(frozen=True, slots=True)
class GoalRunInput:
    tenant_id: str
    goal_id: str
    run_id: str
    requires_approval: bool = False


@dataclass(frozen=True, slots=True)
class CandidateLifecycleInput:
    tenant_id: str
    candidate_id: str


@workflow.defn
class GoalRunWorkflow:
    def __init__(self) -> None:
        self._approval: bool | None = None
        self._cancelled = False
        self._phase = "pending"

    @workflow.signal
    async def approval_decided(self, approved: bool) -> None:
        self._approval = approved

    @workflow.signal
    async def cancel(self) -> None:
        self._cancelled = True

    @workflow.query
    def current_phase(self) -> str:
        return self._phase

    @workflow.run
    async def run(self, command: GoalRunInput) -> str:
        self._phase = "planning"
        await workflow.execute_activity(
            "prepare_run",
            command,
            start_to_close_timeout=timedelta(minutes=2),
            retry_policy=RetryPolicy(maximum_attempts=3),
        )
        if command.requires_approval:
            self._phase = "awaiting_approval"
            await workflow.wait_condition(lambda: self._approval is not None or self._cancelled)
            if self._cancelled:
                await workflow.execute_activity(
                    "cancel_run", command, start_to_close_timeout=timedelta(minutes=1)
                )
                return "cancelled"
            if self._approval is False:
                await workflow.execute_activity(
                    "reject_run", command, start_to_close_timeout=timedelta(minutes=1)
                )
                return "rejected"
        self._phase = "executing"
        # Side-effect activities own idempotency and unknown-outcome reconciliation.
        await workflow.execute_activity(
            "execute_run",
            command,
            start_to_close_timeout=timedelta(minutes=30),
            retry_policy=RetryPolicy(maximum_attempts=1),
        )
        self._phase = "evaluating"
        result: str = await workflow.execute_activity(
            "evaluate_run",
            command,
            start_to_close_timeout=timedelta(minutes=10),
            retry_policy=RetryPolicy(maximum_attempts=2),
        )
        self._phase = result
        return result


@workflow.defn
class CandidateLifecycleWorkflow:
    def __init__(self) -> None:
        self._approval: bool | None = None
        self._phase = "draft"

    @workflow.signal
    async def approval_decided(self, approved: bool) -> None:
        self._approval = approved

    @workflow.query
    def current_phase(self) -> str:
        return self._phase

    @workflow.run
    async def run(self, command: CandidateLifecycleInput) -> str:
        self._phase = "evaluating"
        passed: bool = await workflow.execute_activity(
            "evaluate_candidate",
            command,
            start_to_close_timeout=timedelta(minutes=30),
            retry_policy=RetryPolicy(maximum_attempts=2),
        )
        if not passed:
            self._phase = "rejected"
            return self._phase
        self._phase = "awaiting_approval"
        await workflow.wait_condition(lambda: self._approval is not None)
        if self._approval is False:
            self._phase = "rejected"
            return self._phase
        await workflow.execute_activity(
            "promote_candidate",
            command,
            start_to_close_timeout=timedelta(minutes=2),
            retry_policy=RetryPolicy(maximum_attempts=1),
        )
        self._phase = "stable"
        return self._phase
