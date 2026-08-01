"""Run application use cases."""

from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from autonoesis_domain import Run


class RunRepository(Protocol):
    async def add(self, run: Run) -> None: ...


@dataclass(frozen=True, slots=True)
class StartRun:
    tenant_id: UUID
    goal_id: UUID


class StartRunHandler:
    def __init__(self, runs: RunRepository) -> None:
        self._runs = runs

    async def __call__(self, command: StartRun) -> Run:
        run = Run(tenant_id=command.tenant_id, goal_id=command.goal_id)
        await self._runs.add(run)
        return run
