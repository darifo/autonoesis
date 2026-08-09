"""Hybrid store: PostgreSQL authority plus process-local capability registry."""

from uuid import UUID

from autonoesis_application import AuditEvent
from autonoesis_domain import GoalContract, Run
from sqlalchemy.ext.asyncio import AsyncEngine

from autonoesis_adapters.memory import InMemoryPlatformStore
from autonoesis_adapters.persistence import SqlAlchemyPlatformRepository, create_repository


class PostgreSQLPlatformStore(InMemoryPlatformStore):
    def __init__(self, engine: AsyncEngine, repository: SqlAlchemyPlatformRepository) -> None:
        super().__init__()
        self.engine = engine
        self.repository = repository

    @classmethod
    def from_url(cls, database_url: str) -> "PostgreSQLPlatformStore":
        engine, repository = create_repository(database_url)
        return cls(engine, repository)

    async def close(self) -> None:
        await self.engine.dispose()

    async def add_goal(self, goal: GoalContract, audit: AuditEvent) -> None:
        await self.repository.add_goal(goal, audit)
        self.audits.append(audit)

    async def get_goal(self, tenant_id: UUID, goal_id: UUID) -> GoalContract:
        return await self.repository.get_goal(tenant_id, goal_id)

    async def list_goals(self, tenant_id: UUID) -> tuple[GoalContract, ...]:
        return await self.repository.list_goals(tenant_id)

    async def add_run(self, run: Run, audit: AuditEvent) -> None:
        await self.repository.add_run(run, audit)
        self.audits.append(audit)

    async def get_run(self, tenant_id: UUID, run_id: UUID) -> Run:
        return await self.repository.get_run(tenant_id, run_id)

    async def save_run(self, run: Run, expected_version: int) -> None:
        await self.repository.save_run(run, expected_version)

    async def list_runs(self, tenant_id: UUID, goal_id: UUID | None = None) -> tuple[Run, ...]:
        return await self.repository.list_runs(tenant_id, goal_id)
