"""Aggregate-oriented persistence and transaction ports for Application use cases."""

from contextlib import AbstractAsyncContextManager
from typing import Protocol
from uuid import UUID

from autonoesis_domain import (
    Action,
    ActionAttempt,
    ApprovalRequest,
    BudgetAmount,
    ContextSnapshot,
    Evidence,
    GoalContract,
    Outcome,
    Plan,
    Run,
    Task,
    Trial,
)

from autonoesis_application.platform import AuditEvent
from autonoesis_application.verification import (
    EvidenceCaptureSaga,
    EvidenceDeletionRecord,
)


class ExecutionRepository(Protocol):
    def transaction(self) -> AbstractAsyncContextManager[None]: ...

    async def record_audit(self, audit: AuditEvent) -> None: ...

    async def get_idempotency(
        self, tenant_id: UUID, key: str, request_digest: str | None = None
    ) -> UUID | None: ...

    async def put_idempotency(
        self,
        tenant_id: UUID,
        key: str,
        external_id: UUID,
        request_digest: str | None = None,
    ) -> None: ...

    async def add_goal(self, goal: GoalContract, audit: AuditEvent) -> None: ...

    async def get_goal(self, tenant_id: UUID, goal_id: UUID) -> GoalContract: ...

    async def save_goal(
        self, goal: GoalContract, expected_version: int, audit: AuditEvent
    ) -> None: ...

    async def add_run(self, run: Run, audit: AuditEvent) -> None: ...

    async def get_run(self, tenant_id: UUID, run_id: UUID) -> Run: ...

    async def save_run(
        self, run: Run, expected_version: int, audit: AuditEvent | None = None
    ) -> None: ...

    async def list_runs(self, tenant_id: UUID, goal_id: UUID | None = None) -> tuple[Run, ...]: ...

    async def add_context_snapshot(self, snapshot: ContextSnapshot) -> None: ...

    async def get_context_snapshot(self, tenant_id: UUID, run_id: UUID) -> ContextSnapshot: ...

    async def add_plan(self, plan: Plan) -> None: ...

    async def get_plan(self, tenant_id: UUID, plan_id: UUID) -> Plan: ...

    async def get_task(self, tenant_id: UUID, task_id: UUID) -> Task: ...

    async def list_tasks(self, tenant_id: UUID, run_id: UUID) -> tuple[Task, ...]: ...

    async def save_task(self, task: Task, expected_version: int) -> None: ...

    async def add_action(self, action: Action) -> None: ...

    async def get_action(self, tenant_id: UUID, action_id: UUID) -> Action: ...

    async def save_action(self, action: Action, expected_version: int) -> None: ...

    async def list_actions(self, tenant_id: UUID, run_id: UUID) -> tuple[Action, ...]: ...

    async def add_action_attempt(self, attempt: ActionAttempt) -> None: ...

    async def list_action_attempts(
        self, tenant_id: UUID, action_id: UUID
    ) -> tuple[ActionAttempt, ...]: ...


class GovernanceRepository(Protocol):
    async def add_approval(self, approval: ApprovalRequest) -> None: ...

    async def get_approval(self, tenant_id: UUID, approval_id: UUID) -> ApprovalRequest: ...

    async def save_approval(self, approval: ApprovalRequest, expected_version: int) -> None: ...

    async def record_budget_entry(
        self,
        tenant_id: UUID,
        run_id: UUID,
        category: str,
        amount: BudgetAmount,
        reference: str,
    ) -> UUID: ...


class VerificationRepository(Protocol):
    async def add_evidence(self, item: Evidence) -> None: ...

    async def get_evidence(self, tenant_id: UUID, evidence_id: UUID) -> Evidence: ...

    async def list_evidence(self, tenant_id: UUID) -> tuple[Evidence, ...]: ...

    async def add_outcome(self, item: Outcome) -> None: ...

    async def get_outcome(self, tenant_id: UUID, outcome_id: UUID) -> Outcome: ...

    async def list_outcomes(self, tenant_id: UUID, run_id: UUID) -> tuple[Outcome, ...]: ...

    async def start_evidence_capture(self, saga: EvidenceCaptureSaga) -> None: ...

    async def get_evidence_capture(
        self, tenant_id: UUID, evidence_id: UUID
    ) -> EvidenceCaptureSaga: ...

    async def complete_evidence_capture(self, tenant_id: UUID, evidence_id: UUID) -> None: ...

    async def record_evidence_deletion(self, record: EvidenceDeletionRecord) -> None: ...

    async def get_evidence_deletion(
        self, tenant_id: UUID, evidence_id: UUID
    ) -> EvidenceDeletionRecord: ...


class EvaluationRepository(Protocol):
    async def add_trial(self, trial: Trial) -> None: ...

    async def list_trials(self, tenant_id: UUID) -> tuple[Trial, ...]: ...


class AuditRepository(Protocol):
    async def list_audit_events(self, tenant_id: UUID) -> tuple[AuditEvent, ...]: ...


class ApplicationRepository(
    ExecutionRepository,
    GovernanceRepository,
    VerificationRepository,
    Protocol,
):
    """Complete transaction-scoped port required by vertical execution use cases."""
