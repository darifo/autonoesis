"""SLO instrumentation, error budgets, and metric reporting.

Provides the metrics pipeline for:
- Outcome success rate
- Action success/failure/unknown rates
- Approval latency
- Rollback frequency
- Error budget consumption tracking
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from enum import StrEnum


class SLI(StrEnum):
    """Service Level Indicators tracked by the platform."""

    OUTCOME_SUCCESS_RATE = "outcome_success_rate"
    ACTION_SUCCESS_RATE = "action_success_rate"
    ACTION_UNKNOWN_RATE = "action_unknown_rate"
    APPROVAL_LATENCY_P50 = "approval_latency_p50"
    APPROVAL_LATENCY_P95 = "approval_latency_p95"
    ROLLBACK_RATE = "rollback_rate"
    DUPLICATE_SIDE_EFFECT_RATE = "duplicate_side_effect_rate"


@dataclass(frozen=True, slots=True)
class SLOTarget:
    """Target value and window for a single SLI."""

    sli: SLI
    target: float  # e.g. 0.995 for 99.5%
    window: timedelta = timedelta(days=30)
    operator: str = "gte"  # gte = must be >= target, lte = must be <= target


@dataclass(frozen=True, slots=True)
class SLOMeasurement:
    """A single measurement point for an SLI."""

    sli: SLI
    value: float
    window_start: datetime
    window_end: datetime
    sample_count: int = 0
    recorded_at: datetime = field(default_factory=lambda: datetime.now(UTC))


@dataclass(frozen=True, slots=True)
class ErrorBudget:
    """Remaining error budget for an SLO."""

    sli: SLI
    total_budget: float  # e.g. 0.005 for 0.5% allowed errors
    consumed: float = 0.0
    remaining: float = 0.0
    exhausted: bool = False


class SLORegistry:
    """Tracks SLI measurements and computes error budgets."""

    def __init__(self, targets: tuple[SLOTarget, ...] = ()) -> None:
        self._targets = {t.sli: t for t in targets}
        self._measurements: dict[SLI, list[SLOMeasurement]] = {s: [] for s in SLI}

    async def record(self, measurement: SLOMeasurement) -> None:
        self._measurements[measurement.sli].append(measurement)

    async def compute_budget(self, sli: SLI, now: datetime | None = None) -> ErrorBudget:
        """Compute the sample-weighted error budget for one SLI.

        Each measurement contributes proportionally to its `sample_count`
        (docs/slo/error-budget-policy.md: budget = (1-SLO) x valid samples).
        `gte` targets treat shortfalls below the target as consumption; `lte`
        targets treat excess above it as consumption. Unweighted averages are
        never used, and an unmeasured SLI reports a full budget rather than a
        fabricated value.
        """
        now = now or datetime.now(UTC)
        target = self._targets.get(sli)
        if target is None:
            return ErrorBudget(
                sli=sli,
                total_budget=0.0,
                remaining=0.0,
                exhausted=True,
            )

        window_start = now - target.window
        recent = [m for m in self._measurements[sli] if m.window_start >= window_start]

        if not recent:
            return ErrorBudget(
                sli=sli,
                total_budget=1.0 - target.target,
                remaining=1.0 - target.target,
            )

        total_samples = sum(max(m.sample_count, 0) for m in recent)
        if total_samples == 0:
            # No weighted evidence: fall back to a full budget, never a guess.
            return ErrorBudget(
                sli=sli,
                total_budget=1.0 - target.target,
                remaining=1.0 - target.target,
            )
        weighted_value = sum(m.value * max(m.sample_count, 0) for m in recent) / total_samples
        total_budget = 1.0 - target.target
        if target.operator == "gte":
            shortfall = max(0.0, target.target - weighted_value)
        else:
            shortfall = max(0.0, weighted_value - target.target)
        consumed = min(shortfall, 1.0)
        remaining = max(0.0, total_budget - consumed)

        return ErrorBudget(
            sli=sli,
            total_budget=total_budget,
            consumed=consumed,
            remaining=remaining,
            exhausted=remaining <= 0,
        )

    async def all_budgets(self) -> tuple[ErrorBudget, ...]:
        results = []
        for sli in self._targets:
            results.append(await self.compute_budget(sli))
        return tuple(results)


# ── Aggregation helpers ──────────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class QuantileReport:
    """Statistical summary of a metric across multiple Trials."""

    metric: str
    count: int
    min: float
    max: float
    mean: float
    median: float
    p90: float
    p95: float
    p99: float


class QuantileCalculator:
    """Computes quantile distributions for evaluation metrics."""

    @staticmethod
    def compute(values: tuple[float, ...], metric: str = "score") -> QuantileReport:
        if not values:
            return QuantileReport(
                metric=metric,
                count=0,
                min=0,
                max=0,
                mean=0,
                median=0,
                p90=0,
                p95=0,
                p99=0,
            )
        sorted_vals = sorted(values)
        n = len(sorted_vals)

        def pct(p: float) -> float:
            idx = int(n * p / 100)
            return sorted_vals[min(idx, n - 1)]

        return QuantileReport(
            metric=metric,
            count=n,
            min=sorted_vals[0],
            max=sorted_vals[-1],
            mean=sum(sorted_vals) / n,
            median=pct(50),
            p90=pct(90),
            p95=pct(95),
            p99=pct(99),
        )


__all__ = [
    "SLI",
    "ErrorBudget",
    "QuantileCalculator",
    "QuantileReport",
    "SLOMeasurement",
    "SLORegistry",
    "SLOTarget",
]
