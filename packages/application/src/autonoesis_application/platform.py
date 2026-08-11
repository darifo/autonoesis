"""Industry-neutral platform use cases and persistence ports."""

from dataclasses import dataclass
from datetime import datetime
from hashlib import sha256
from typing import Any, Protocol, cast
from uuid import UUID

from autonoesis_capability import GoalTypeManifest
from autonoesis_domain import (
    AgentVersion,
    BudgetUnit,
    DataClassification,
    ExecutionMode,
    GoalContract,
    RiskTier,
    Run,
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
    async def get_goal_type(self, tenant_id: UUID, goal_type: str) -> GoalTypeManifest: ...

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
        from autonoesis_application.execution import (
            ActivateGoal,
            CommandContext,
            GoalExecutionApplication,
        )
        from autonoesis_application.repositories import ApplicationRepository

        repository = getattr(self._repository, "repository", self._repository)
        application = GoalExecutionApplication(
            cast(ApplicationRepository, repository), self._catalog
        )
        created = await application.create_goal(
            CommandContext(
                identity,
                command.correlation_id,
                command.correlation_id,
                f"compat-create:{command.correlation_id}",
                sha256(repr(command).encode("utf-8")).hexdigest(),
            ),
            command,
        )
        return await application.activate_goal(
            CommandContext(
                identity,
                command.correlation_id,
                command.correlation_id,
                f"compat-activate:{command.correlation_id}",
                sha256(f"activate\n{created.goal_id}\ncompatibility".encode()).hexdigest(),
            ),
            ActivateGoal(created.goal_id, "compatibility handler activated Goal"),
        )


@dataclass(frozen=True, slots=True)
class StartGoalRun:
    goal_id: UUID
    correlation_id: UUID


class StartGoalRunHandler:
    def __init__(self, repository: PlatformRepository, catalog: CapabilityCatalog) -> None:
        self._repository = repository
        self._catalog = catalog

    async def __call__(self, identity: IdentityContext, command: StartGoalRun) -> Run:
        from autonoesis_application.execution import (
            CommandContext,
            GoalExecutionApplication,
            RequestRun,
        )
        from autonoesis_application.repositories import ApplicationRepository

        repository = getattr(self._repository, "repository", self._repository)
        application = GoalExecutionApplication(
            cast(ApplicationRepository, repository), self._catalog
        )
        return await application.request_run(
            CommandContext(
                identity,
                command.correlation_id,
                command.correlation_id,
                f"compat-request-run:{command.correlation_id}",
                sha256(repr(command).encode("utf-8")).hexdigest(),
            ),
            RequestRun(command.goal_id),
        )
