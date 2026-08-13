"""Environment facts, projections, refresh, and simulation for Autonoesis."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum

from autonoesis_domain import EnvironmentFact


class ProjectionStatus(StrEnum):
    FRESH = "fresh"
    STALE = "stale"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class FactProjection:
    """A derived/predicted fact based on existing observations."""

    projected_fact: EnvironmentFact
    confidence: float
    status: ProjectionStatus = ProjectionStatus.FRESH
    based_on_fact_ids: tuple[str, ...] = ()


class EnvironmentRefresher:
    """Refreshes environment facts by re-querying external systems.

    Facts past their valid_until timestamp are marked stale and should
    be refreshed before use in planning.
    """

    @staticmethod
    async def refresh(
        facts: tuple[EnvironmentFact, ...],
        now: datetime | None = None,
    ) -> tuple[tuple[EnvironmentFact, ...], tuple[EnvironmentFact, ...]]:
        """Split facts into fresh and stale groups.

        Returns (fresh_facts, stale_facts).
        """
        now = now or datetime.now(UTC)
        fresh: list[EnvironmentFact] = []
        stale: list[EnvironmentFact] = []
        for fact in facts:
            if fact.valid_until is not None and now > fact.valid_until:
                stale.append(fact)
            else:
                fresh.append(fact)
        return tuple(fresh), tuple(stale)


class EnvironmentProjector:
    """Projects future environment state from current facts.

    Used for simulation and what-if planning.
    """

    @staticmethod
    async def project(
        facts: tuple[EnvironmentFact, ...],
        horizon_seconds: float = 3600,
    ) -> tuple[FactProjection, ...]:
        """Extrapolate facts *horizon_seconds* into the future.

        A real implementation would use time-series models or rule-based
        projection based on fact type and observed trends.
        """
        projections: list[FactProjection] = []
        for fact in facts:
            projected_valid_until = (
                fact.observed_at + (fact.valid_until - fact.observed_at)
                if fact.valid_until
                else fact.observed_at
            )
            projected = EnvironmentFact(
                tenant_id=fact.tenant_id,
                fact_id=fact.fact_id,
                source=fact.source,
                source_authority=fact.source_authority,
                subject=fact.subject,
                value=fact.value,
                observed_at=datetime.now(UTC),
                valid_until=projected_valid_until,
                trust=fact.trust,
                classification=fact.classification,
                freshness_policy=fact.freshness_policy,
                allowed_roles=fact.allowed_roles,
                allowed_purposes=fact.allowed_purposes,
                visible_fields=fact.visible_fields,
            )
            projections.append(
                FactProjection(
                    projected_fact=projected,
                    confidence=0.8,
                    status=ProjectionStatus.FRESH,
                    based_on_fact_ids=(fact.fact_id,),
                )
            )
        return tuple(projections)


__all__ = [
    "EnvironmentProjector",
    "EnvironmentRefresher",
    "FactProjection",
    "ProjectionStatus",
]
