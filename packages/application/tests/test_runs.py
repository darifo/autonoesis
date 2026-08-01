from uuid import uuid4

import pytest
from autonoesis_application import StartRun, StartRunHandler
from autonoesis_domain import Run, RunStatus


class InMemoryRunRepository:
    def __init__(self) -> None:
        self.items: list[Run] = []

    async def add(self, run: Run) -> None:
        self.items.append(run)


@pytest.mark.asyncio
async def test_start_run_creates_pending_run() -> None:
    repository = InMemoryRunRepository()
    handler = StartRunHandler(repository)

    run = await handler(StartRun(tenant_id=uuid4(), goal_id=uuid4()))

    assert run.status is RunStatus.PENDING
    assert repository.items == [run]
