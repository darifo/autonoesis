"""Real-ledger AI FinOps and audit-event-driven SLO projection.

FinOps distinguishes the cost lifecycle phases required by P1-07: estimate
(before execution), reserve (held funds at the Tool Gateway), settle (final
usage), and retry_waste (work discarded by retries). Everything persists in
the authoritative `budget_ledger` through the platform store, so summaries are
computed from real state rather than in-memory samples.

SLO projection derives measurements from persisted audit events — metrics are
computed from real platform facts, never static sample data.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Any
from uuid import UUID

from autonoesis_domain import BudgetAmount, BudgetUnit
from autonoesis_evolution import (
    SLI,
    SLOMeasurement,
    SLORegistry,
    SLOTarget,
)

AuditEventSource = Callable[[UUID], Awaitable[tuple[Any, ...]]]


class CostPhase(StrEnum):
    """Lifecycle phases of a cost entry in the authoritative ledger."""

    ESTIMATE = "estimate"
    RESERVE = "reserve"
    SETTLE = "settle"
    RETRY_WASTE = "retry_waste"


# Legacy gateway entries recorded before phases existed still count as held funds.
_RESERVE_ALIASES = frozenset({CostPhase.RESERVE.value, "tool_execution"})


class CostPhaseLedger:
    """Phase-aware AI FinOps over the authoritative budget ledger."""

    def __init__(self, store: Any) -> None:
        self._store = store

    async def record(
        self,
        tenant_id: UUID,
        run_id: UUID,
        phase: CostPhase,
        amount: int,
        reference: str,
    ) -> UUID:
        if amount < 0:
            raise ValueError("cost phases record non-negative amounts")
        if not reference.strip():
            raise ValueError("cost entries require an idempotent reference")
        entry_id: UUID = await self._store.record_budget_entry(
            tenant_id,
            run_id,
            phase.value,
            BudgetAmount(amount, BudgetUnit.COST_UNITS),
            reference,
        )
        return entry_id

    async def estimate(self, tenant_id: UUID, run_id: UUID, amount: int, reference: str) -> UUID:
        return await self.record(tenant_id, run_id, CostPhase.ESTIMATE, amount, reference)

    async def reserve(self, tenant_id: UUID, run_id: UUID, amount: int, reference: str) -> UUID:
        return await self.record(tenant_id, run_id, CostPhase.RESERVE, amount, reference)

    async def settle(self, tenant_id: UUID, run_id: UUID, amount: int, reference: str) -> UUID:
        return await self.record(tenant_id, run_id, CostPhase.SETTLE, amount, reference)

    async def retry_waste(self, tenant_id: UUID, run_id: UUID, amount: int, reference: str) -> UUID:
        return await self.record(tenant_id, run_id, CostPhase.RETRY_WASTE, amount, reference)

    async def summarize_run(self, tenant_id: UUID, run_id: UUID) -> dict[str, int]:
        phases: dict[str, int] = {
            CostPhase.ESTIMATE.value: 0,
            CostPhase.RESERVE.value: 0,
            CostPhase.SETTLE.value: 0,
            CostPhase.RETRY_WASTE.value: 0,
        }
        for entry in await self._store.list_budget_entries(tenant_id, run_id):
            category = entry["category"]
            if category in _RESERVE_ALIASES:
                phases[CostPhase.RESERVE.value] += entry["amount"]
            elif category in phases:
                phases[category] += entry["amount"]
        return phases


class AuditEventSloProjector:
    """Project persisted audit events into SLO measurements.

    Only SLIs with a real event mapping are produced: outcome success rate
    (verified vs recorded outcomes), action unknown rate (reconciled vs
    governed executions), and approval p95 latency (requested→decided event
    pairing). SLIs without instrumentation are simply absent — never
    synthesized from sample data.
    """

    def __init__(self, list_events: AuditEventSource) -> None:
        self._list_events = list_events

    async def project(
        self,
        tenant_id: UUID,
        *,
        window: timedelta = timedelta(days=30),
        now: datetime | None = None,
    ) -> SLORegistry:
        now = now or datetime.now(UTC)
        window_start = now - window
        events = [
            event
            for event in await self._list_events(tenant_id)
            if (event.created_at or now) >= window_start
        ]
        registry = SLORegistry(
            targets=(
                SLOTarget(SLI.OUTCOME_SUCCESS_RATE, target=0.95, window=window),
                SLOTarget(SLI.ACTION_UNKNOWN_RATE, target=0.01, window=window, operator="lte"),
                SLOTarget(SLI.APPROVAL_LATENCY_P95, target=5000.0, window=window, operator="lte"),
            )
        )
        recorded = sum(1 for e in events if e.event_type == "outcome.recorded")
        verified = sum(1 for e in events if e.event_type == "outcome.verified")
        governed = sum(1 for e in events if e.event_type == "action.governed_execution_recorded")
        reconciled = sum(1 for e in events if e.event_type == "action.reconciled")

        if recorded > 0:
            await registry.record(
                SLOMeasurement(
                    sli=SLI.OUTCOME_SUCCESS_RATE,
                    value=verified / recorded,
                    window_start=window_start,
                    window_end=now,
                    sample_count=recorded,
                    recorded_at=now,
                )
            )
        if governed > 0:
            await registry.record(
                SLOMeasurement(
                    sli=SLI.ACTION_UNKNOWN_RATE,
                    value=reconciled / governed,
                    window_start=window_start,
                    window_end=now,
                    sample_count=governed,
                    recorded_at=now,
                )
            )
        await self._record_approval_latency(events, registry, window_start, now)
        return registry

    @staticmethod
    async def _record_approval_latency(
        events: list[Any],
        registry: SLORegistry,
        window_start: datetime,
        now: datetime,
    ) -> None:
        """Pair approval requests with their decisions to measure latency.

        Only decided approvals contribute; pending requests are excluded rather
        than counted as zero latency. Decisions without a matching request are
        ignored (they cannot be timed).
        """
        requested: dict[str, datetime] = {}
        latencies_seconds: list[float] = []
        for event in events:
            occurred = event.created_at
            if occurred is None:
                continue
            if event.event_type == "approval.requested":
                requested[str(event.object_id)] = occurred
            elif (
                event.event_type in {"approval.approved", "approval.rejected"}
                and str(event.object_id) in requested
            ):
                started = requested.pop(str(event.object_id))
                latencies_seconds.append(max((occurred - started).total_seconds(), 0.0))
        if latencies_seconds:
            latencies_ms = sorted(value * 1000 for value in latencies_seconds)
            p95 = latencies_ms[min(int(len(latencies_ms) * 0.95), len(latencies_ms) - 1)]
            await registry.record(
                SLOMeasurement(
                    sli=SLI.APPROVAL_LATENCY_P95,
                    value=p95,
                    window_start=window_start,
                    window_end=now,
                    sample_count=len(latencies_ms),
                    recorded_at=now,
                )
            )


__all__ = ["AuditEventSloProjector", "CostPhase", "CostPhaseLedger"]
