"""Industry-neutral platform use cases and persistence ports."""

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol
from uuid import UUID

from autonoesis_capability import GoalTypeManifest, validate_payload
from autonoesis_domain import (
    AgentVersion,
    BudgetAmount,
    BudgetUnit,
    DataClassification,
    DataPolicy,
    ExecutionMode,
    GoalContract,
    GoalStatus,
    JsonObject,
    RiskTier,
    Run,
    RunStatus,
    SubjectRef,
    SuccessCriterion,
)


class RecordNotFound(LookupError):
    """Raised when a tenant-scoped record cannot be found."""


class TenantBoundaryViolation(PermissionError):
    """Raised when data attempts to cross a tenant boundary."""


class ConcurrencyConflict(RuntimeError):
    """Raised when an optimistic version no longer matches."""


@dataclass(frozen=True, slots=True)
class IdentityContext:
    tenant_id: UUID
    actor_id: UUID
    principal_id: UUID
    roles: frozenset[str]
    agent_id: str | None = None


@dataclass(frozen=True, slots=True)
class AuditEvent:
    tenant_id: UUID
    actor_id: UUID
    principal_id: UUID
    event_type: str
    object_type: str
    object_id: str
    correlation_id: UUID
    details: dict[str, Any]


class PlatformRepository(Protocol):
    async def add_goal(self, goal: GoalContract, audit: AuditEvent) -> None: ...

    async def get_goal(self, tenant_id: UUID, goal_id: UUID) -> GoalContract: ...

    async def list_goals(self, tenant_id: UUID) -> tuple[GoalContract, ...]: ...

    async def add_run(self, run: Run, audit: AuditEvent) -> None: ...

    async def get_run(self, tenant_id: UUID, run_id: UUID) -> Run: ...

    async def list_runs(self, tenant_id: UUID, goal_id: UUID | None = None) -> tuple[Run, ...]: ...


class CapabilityCatalog(Protocol):
    async def get_goal_type(self, goal_type: str) -> GoalTypeManifest: ...

    async def get_stable_agent(self, tenant_id: UUID, agent_name: str) -> AgentVersion: ...


@dataclass(frozen=True, slots=True)
class CreateGoal:
    goal_type: str
    statement: str
    desired_outcome: str
    subject_refs: tuple[SubjectRef, ...]
    success_criteria: tuple[SuccessCriterion, ...]
    constraints: tuple[str, ...]
    owner_id: UUID
    risk_tier: RiskTier
    budget_limit: int | None
    deadline: datetime
    input_payload: dict[str, Any]
    correlation_id: UUID
    budget_unit: BudgetUnit = BudgetUnit.COST_UNITS
    delegation_id: UUID | None = None
    maximum_classification: DataClassification = DataClassification.INTERNAL
    allowed_regions: tuple[str, ...] = ()
    retention_days: int = 30
    execution_mode: ExecutionMode = ExecutionMode.SUPERVISED
    max_concurrent_runs: int = 1


class CreateGoalHandler:
    def __init__(self, repository: PlatformRepository, catalog: CapabilityCatalog) -> None:
        self._repository = repository
        self._catalog = catalog

    async def __call__(self, identity: IdentityContext, command: CreateGoal) -> GoalContract:
        goal_type = await self._catalog.get_goal_type(command.goal_type)
        validate_payload(goal_type, command.input_payload)
        goal = GoalContract(
            tenant_id=identity.tenant_id,
            goal_type=command.goal_type,
            statement=command.statement,
            desired_outcome=command.desired_outcome,
            subject_refs=command.subject_refs,
            success_criteria=command.success_criteria,
            constraints=command.constraints,
            owner_id=command.owner_id,
            risk_tier=command.risk_tier,
            budget_limit=BudgetAmount(
                command.budget_limit or goal_type.default_budget, command.budget_unit
            ),
            deadline=command.deadline,
            input_payload=JsonObject.from_value(command.input_payload),
            delegation_id=command.delegation_id,
            data_policy=DataPolicy(
                maximum_classification=command.maximum_classification,
                allowed_regions=command.allowed_regions,
                retention_days=command.retention_days,
            ),
            execution_mode=command.execution_mode,
            max_concurrent_runs=command.max_concurrent_runs,
        ).transition_to(
            GoalStatus.ACTIVE,
            actor_id=identity.actor_id,
            reason="goal accepted by CreateGoal",
        )
        audit = AuditEvent(
            tenant_id=identity.tenant_id,
            actor_id=identity.actor_id,
            principal_id=identity.principal_id,
            event_type="goal.created",
            object_type="goal",
            object_id=str(goal.goal_id),
            correlation_id=command.correlation_id,
            details={"goal_type": goal.goal_type, "version": goal.version},
        )
        await self._repository.add_goal(goal, audit)
        return goal


@dataclass(frozen=True, slots=True)
class StartGoalRun:
    goal_id: UUID
    correlation_id: UUID


class StartGoalRunHandler:
    def __init__(self, repository: PlatformRepository, catalog: CapabilityCatalog) -> None:
        self._repository = repository
        self._catalog = catalog

    async def __call__(self, identity: IdentityContext, command: StartGoalRun) -> Run:
        goal = await self._repository.get_goal(identity.tenant_id, command.goal_id)
        active_runs = await self._repository.list_runs(identity.tenant_id, goal.goal_id)
        goal.assert_run_request_allowed(
            sum(
                run.status
                in {
                    RunStatus.PENDING,
                    RunStatus.RUNNING,
                    RunStatus.BLOCKED,
                    RunStatus.AWAITING_EVIDENCE,
                }
                for run in active_runs
            )
        )
        goal_type = await self._catalog.get_goal_type(goal.goal_type)
        agent = await self._catalog.get_stable_agent(identity.tenant_id, goal_type.agent)
        run = Run(
            tenant_id=identity.tenant_id,
            goal_id=goal.goal_id,
            agent_version_id=agent.agent_version_id,
        )
        audit = AuditEvent(
            tenant_id=identity.tenant_id,
            actor_id=identity.actor_id,
            principal_id=identity.principal_id,
            event_type="run.requested",
            object_type="run",
            object_id=str(run.run_id),
            correlation_id=command.correlation_id,
            details={"goal_id": str(goal.goal_id), "agent_version_id": str(agent.agent_version_id)},
        )
        await self._repository.add_run(run, audit)
        return run
