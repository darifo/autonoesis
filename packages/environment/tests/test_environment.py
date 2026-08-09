# mypy: ignore-errors
"""Tests for environment package."""

from datetime import UTC, datetime, timedelta

import pytest
from autonoesis_domain import EnvironmentFact, TrustLevel
from autonoesis_environment import EnvironmentProjector, EnvironmentRefresher, ProjectionStatus


def _fact(**overrides: object) -> EnvironmentFact:
    now = datetime.now(UTC)
    defaults: dict[str, object] = {
        "fact_id": "f1",
        "source": "test",
        "subject": "test",
        "value": {"v": 1},
        "observed_at": now,
        "valid_until": now + timedelta(hours=1),
        "trust": TrustLevel.ADVISORY,
    }
    defaults.update({k: v for k, v in overrides.items() if v is not None})
    return EnvironmentFact(**defaults)


class TestEnvironmentRefresher:
    @pytest.mark.asyncio
    async def test_splits_fresh_and_stale(self) -> None:
        fresh = _fact()
        stale = _fact(
            observed_at=datetime.now(UTC) - timedelta(hours=2),
            valid_until=datetime.now(UTC) - timedelta(hours=1),
        )

        fresh_list, stale_list = await EnvironmentRefresher.refresh((fresh, stale))

        assert len(fresh_list) == 1
        assert len(stale_list) == 1

    @pytest.mark.asyncio
    async def test_all_fresh(self) -> None:
        facts = tuple(_fact() for _ in range(3))
        fresh, stale = await EnvironmentRefresher.refresh(facts)
        assert len(fresh) == 3
        assert len(stale) == 0


class TestEnvironmentProjector:
    @pytest.mark.asyncio
    async def test_projects_facts(self) -> None:
        facts = (_fact(), _fact())
        projections = await EnvironmentProjector.project(facts, horizon_seconds=3600)
        assert len(projections) == 2
        assert all(p.status == ProjectionStatus.FRESH for p in projections)
