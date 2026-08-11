"""Deterministic durable workflows; all business facts are reloaded by Activities."""

from datetime import timedelta

from temporalio import workflow
from temporalio.common import RetryPolicy

from autonoesis_worker.contracts import (
    ApprovalLookupInput,
    ApprovalState,
    CancelRunInput,
    CandidateLifecycleInput,
    EvaluateCandidateInput,
    EvaluateRunInput,
    ExecuteRunInput,
    GoalRunInput,
    PrepareRunInput,
    PromoteCandidateInput,
    RejectRunInput,
    TakeOverRunInput,
)

_CONTROL_RETRY = RetryPolicy(maximum_attempts=3)
_READ_RETRY = RetryPolicy(maximum_attempts=3)
_WRITE_NO_RETRY = RetryPolicy(maximum_attempts=1)


@workflow.defn
class GoalRunWorkflow:
    """Orchestrate immutable IDs while PostgreSQL retains all business authority."""

    def __init__(self) -> None:
        self._approval_id: str | None = None
        self._cancel_reason: str | None = None
        self._takeover_reason: str | None = None
        self._paused = False
        self._resume_generation = 0
        self._phase = "pending"

    @workflow.signal
    async def approval_decided(self, approval_id: str) -> None:
        if approval_id:
            self._approval_id = approval_id

    @workflow.signal
    async def cancel(self, reason: str = "cancelled_by_user") -> None:
        self._cancel_reason = reason or "cancelled_by_user"

    @workflow.signal
    async def pause(self) -> None:
        self._paused = True

    @workflow.signal
    async def resume(self) -> None:
        self._paused = False
        self._resume_generation += 1

    @workflow.signal
    async def take_over(self, reason: str = "manual_takeover") -> None:
        self._takeover_reason = reason or "manual_takeover"

    @workflow.query
    def current_phase(self) -> str:
        return self._phase

    @workflow.run
    async def run(self, command: GoalRunInput) -> str:
        # Retained as a durable marker for future compatible changes to approval semantics.
        workflow.patched("p0-06-approval-id-signal")
        identity = PrepareRunInput(command.tenant_id, command.goal_id, command.run_id)
        if command.continuation_count == 0:
            self._phase = "planning"
            await workflow.execute_activity(
                "prepare_run",
                identity,
                result_type=str,
                start_to_close_timeout=timedelta(minutes=2),
                heartbeat_timeout=timedelta(seconds=30),
                retry_policy=_CONTROL_RETRY,
            )
        terminal = await self._apply_control(command)
        if terminal is not None:
            return terminal

        if command.requires_approval:
            terminal = await self._await_authoritative_approval(command)
            if terminal is not None:
                return terminal

        self._phase = "executing"
        await workflow.execute_activity(
            "execute_run",
            ExecuteRunInput(command.tenant_id, command.goal_id, command.run_id),
            result_type=str,
            start_to_close_timeout=timedelta(minutes=30),
            heartbeat_timeout=timedelta(seconds=30),
            retry_policy=_WRITE_NO_RETRY,
        )
        # Cancellation, pause, or takeover received while the non-retryable write Activity was
        # running takes effect before any later phase. The external call is never blindly repeated.
        terminal = await self._apply_control(command)
        if terminal is not None:
            return terminal

        self._phase = "evaluating"
        result: str = await workflow.execute_activity(
            "evaluate_run",
            EvaluateRunInput(command.tenant_id, command.goal_id, command.run_id),
            result_type=str,
            start_to_close_timeout=timedelta(minutes=10),
            heartbeat_timeout=timedelta(seconds=30),
            retry_policy=RetryPolicy(maximum_attempts=2),
        )
        if result in {"succeeded", "failed", "cancelled"}:
            self._phase = result
            return result

        self._phase = "waiting_for_progress"
        observed_generation = self._resume_generation
        try:
            await workflow.wait_condition(
                lambda: (
                    self._resume_generation > observed_generation
                    or self._cancel_reason is not None
                    or self._takeover_reason is not None
                    or self._paused
                ),
                timeout=self._remaining(command),
                timeout_summary="goal business deadline",
            )
        except TimeoutError:
            return await self._expire(command)
        terminal = await self._apply_control(command)
        if terminal is not None:
            return terminal
        if command.continuation_count >= command.max_continuations:
            return await self._reject(command, "continue_as_new_limit_exhausted")
        # Continue-as-New bounds history after every externally driven progress cycle. The server
        # suggestion is also consulted so future thresholds can become more conservative.
        _ = workflow.info().is_continue_as_new_suggested()
        workflow.continue_as_new(command.continued())

    async def _await_authoritative_approval(self, command: GoalRunInput) -> str | None:
        self._phase = "awaiting_approval"
        while True:
            try:
                await workflow.wait_condition(
                    lambda: (
                        self._approval_id is not None
                        or self._cancel_reason is not None
                        or self._takeover_reason is not None
                        or self._paused
                    ),
                    timeout=self._remaining(command),
                    timeout_summary="approval business deadline",
                )
            except TimeoutError:
                return await self._expire(command)
            terminal = await self._apply_control(command)
            if terminal is not None:
                return terminal
            assert self._approval_id is not None
            approval_id = self._approval_id
            self._approval_id = None
            state: ApprovalState = await workflow.execute_activity(
                "load_approval",
                ApprovalLookupInput(command.tenant_id, command.run_id, approval_id),
                result_type=ApprovalState,
                start_to_close_timeout=timedelta(minutes=1),
                heartbeat_timeout=timedelta(seconds=20),
                retry_policy=_READ_RETRY,
            )
            if state.status == "approved":
                return None
            if state.status in {"rejected", "expired"}:
                return await self._reject(command, f"approval_{state.status}")
            # Pending or an unrelated state is not authority to continue; wait for another signal.

    async def _apply_control(self, command: GoalRunInput) -> str | None:
        if self._cancel_reason is not None:
            self._phase = "cancelling"
            await workflow.execute_activity(
                "cancel_run",
                CancelRunInput(
                    command.tenant_id,
                    command.goal_id,
                    command.run_id,
                    self._cancel_reason,
                ),
                result_type=str,
                start_to_close_timeout=timedelta(minutes=1),
                retry_policy=_CONTROL_RETRY,
            )
            self._phase = "cancelled"
            return self._phase
        if self._takeover_reason is not None:
            self._phase = "taking_over"
            await workflow.execute_activity(
                "take_over_run",
                TakeOverRunInput(
                    command.tenant_id,
                    command.goal_id,
                    command.run_id,
                    self._takeover_reason,
                ),
                result_type=str,
                start_to_close_timeout=timedelta(minutes=1),
                retry_policy=_CONTROL_RETRY,
            )
            self._phase = "taken_over"
            return self._phase
        while self._paused:
            self._phase = "paused"
            try:
                await workflow.wait_condition(
                    lambda: not self._paused or self._terminal_control_requested(),
                    timeout=self._remaining(command),
                    timeout_summary="paused business deadline",
                )
            except TimeoutError:
                return await self._expire(command)
            if self._terminal_control_requested():
                return await self._apply_control(command)
        return None

    def _terminal_control_requested(self) -> bool:
        return self._cancel_reason is not None or self._takeover_reason is not None

    async def _expire(self, command: GoalRunInput) -> str:
        return await self._reject(command, "goal_business_deadline_expired")

    async def _reject(self, command: GoalRunInput, reason: str) -> str:
        self._phase = "rejecting"
        await workflow.execute_activity(
            "reject_run",
            RejectRunInput(command.tenant_id, command.goal_id, command.run_id, reason),
            result_type=str,
            start_to_close_timeout=timedelta(minutes=1),
            retry_policy=_CONTROL_RETRY,
        )
        self._phase = "rejected"
        return self._phase

    @staticmethod
    def _remaining(command: GoalRunInput) -> timedelta:
        seconds = command.deadline_epoch_seconds - workflow.now().timestamp()
        return timedelta(seconds=max(seconds, 0.001))


@workflow.defn
class CandidateLifecycleWorkflow:
    def __init__(self) -> None:
        self._approval_id: str | None = None
        self._phase = "draft"

    @workflow.signal
    async def approval_decided(self, approval_id: str) -> None:
        self._approval_id = approval_id

    @workflow.query
    def current_phase(self) -> str:
        return self._phase

    @workflow.run
    async def run(self, command: CandidateLifecycleInput) -> str:
        self._phase = "evaluating"
        passed: bool = await workflow.execute_activity(
            "evaluate_candidate",
            EvaluateCandidateInput(command.tenant_id, command.candidate_id),
            result_type=bool,
            start_to_close_timeout=timedelta(minutes=30),
            retry_policy=RetryPolicy(maximum_attempts=2),
        )
        if not passed:
            self._phase = "rejected"
            return self._phase
        self._phase = "awaiting_approval"
        await workflow.wait_condition(lambda: self._approval_id is not None)
        await workflow.execute_activity(
            "promote_candidate",
            PromoteCandidateInput(
                command.tenant_id,
                command.candidate_id,
                command.candidate_id,
            ),
            result_type=str,
            start_to_close_timeout=timedelta(minutes=2),
            retry_policy=_WRITE_NO_RETRY,
        )
        self._phase = "stable"
        return self._phase


__all__ = [
    "CandidateLifecycleInput",
    "CandidateLifecycleWorkflow",
    "GoalRunInput",
    "GoalRunWorkflow",
]
