"""Aggregate-oriented persistence ports for authoritative business facts."""

from typing import Protocol
from uuid import UUID

from autonoesis_domain import (
    Action,
    ApprovalRequest,
    BudgetAmount,
    Evidence,
    Outcome,
    Plan,
    Task,
    Trial,
)

from autonoesis_application.platform import AuditEvent


class ExecutionRepository(Protocol):
    async def add_plan(self, plan: Plan) -> None: ...

    async def get_plan(self, tenant_id: UUID, plan_id: UUID) -> Plan: ...

    async def save_task(self, task: Task, expected_version: int) -> None: ...

    async def add_action(self, action: Action) -> None: ...

    async def get_action(self, tenant_id: UUID, action_id: UUID) -> Action: ...

    async def save_action(self, action: Action, expected_version: int) -> None: ...


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

    async def add_outcome(self, item: Outcome) -> None: ...

    async def get_outcome(self, tenant_id: UUID, outcome_id: UUID) -> Outcome: ...


class EvaluationRepository(Protocol):
    async def add_trial(self, trial: Trial) -> None: ...

    async def list_trials(self, tenant_id: UUID) -> tuple[Trial, ...]: ...


class AuditRepository(Protocol):
    async def list_audit_events(self, tenant_id: UUID) -> tuple[AuditEvent, ...]: ...
