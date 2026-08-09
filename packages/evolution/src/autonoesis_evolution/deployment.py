"""Shadow, Canary, and auto-rollback deployment pipeline.

Orchestrates the progression:
  Candidate → Shadow (silent) → Canary (traffic %) → Stable (100%)
with automatic rollback on guardrail breach.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from uuid import UUID, uuid4

# ── Deployment stages ────────────────────────────────────────────────────────


class DeploymentStage(StrEnum):
    CANDIDATE = "candidate"
    EVALUATING = "evaluating"
    SHADOW = "shadow"
    CANARY = "canary"
    STABLE = "stable"
    ROLLED_BACK = "rolled_back"
    FAILED = "failed"


class TrafficSplit(StrEnum):
    SHADOW = "shadow"  # 0% live traffic, mirror only
    CANARY_5 = "canary_5"
    CANARY_10 = "canary_10"
    CANARY_25 = "canary_25"
    CANARY_50 = "canary_50"
    STABLE = "stable"  # 100%


# ── Guardrails ───────────────────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class GuardrailThreshold:
    """Metric threshold that triggers automatic rollback when breached."""

    metric: str
    operator: str  # "lt", "gt", "lte", "gte"
    value: float
    window_seconds: int = 300
    consecutive_breaches: int = 2


@dataclass(frozen=True, slots=True)
class GuardrailStatus:
    passed: bool
    breached_metrics: tuple[str, ...] = ()
    current_values: dict[str, float] = field(default_factory=dict)


# ── Observation window ───────────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class ObservationWindow:
    """Time window during which a deployment stage is monitored."""

    stage: DeploymentStage
    started_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    duration: timedelta = timedelta(minutes=30)
    metrics_collected: int = 0

    @property
    def elapsed(self) -> timedelta:
        return datetime.now(UTC) - self.started_at

    @property
    def is_complete(self) -> bool:
        return self.elapsed >= self.duration


# ── Deployment record ────────────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class DeploymentRecord:
    deployment_id: UUID = field(default_factory=uuid4)
    candidate_id: UUID = field(default_factory=uuid4)
    stage: DeploymentStage = DeploymentStage.CANDIDATE
    split: TrafficSplit = TrafficSplit.SHADOW
    started_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    promoted_at: datetime | None = None
    rolled_back_at: datetime | None = None
    rollback_reason: str = ""


# ── Pipeline ─────────────────────────────────────────────────────────────────


class DeploymentPipeline:
    """Manages the full deployment lifecycle: Shadow → Canary → Stable.

    Each stage has an observation window.  Guardrail breaches during
    Shadow/Canary trigger automatic rollback.
    """

    def __init__(
        self,
        guardrails: tuple[GuardrailThreshold, ...] = (),
        shadow_duration: timedelta = timedelta(minutes=15),
        canary_duration: timedelta = timedelta(minutes=30),
    ) -> None:
        self._guardrails = guardrails
        self._shadow_duration = shadow_duration
        self._canary_duration = canary_duration
        self._deployments: dict[UUID, DeploymentRecord] = {}
        self._windows: dict[UUID, ObservationWindow] = {}
        self._breach_counters: dict[str, int] = {}  # metric → consecutive breaches

    async def promote_to_shadow(self, candidate_id: UUID) -> DeploymentRecord:
        """Begin shadow deployment: mirror traffic, no user impact."""
        record = DeploymentRecord(
            candidate_id=candidate_id,
            stage=DeploymentStage.SHADOW,
            split=TrafficSplit.SHADOW,
        )
        self._deployments[record.deployment_id] = record
        self._windows[record.deployment_id] = ObservationWindow(
            stage=DeploymentStage.SHADOW,
            duration=self._shadow_duration,
        )
        return record

    async def promote_to_canary(
        self,
        deployment_id: UUID,
        split: TrafficSplit = TrafficSplit.CANARY_5,
    ) -> DeploymentRecord:
        """Promote from Shadow to Canary with a percentage of live traffic."""
        record = self._deployments[deployment_id]
        record = DeploymentRecord(
            deployment_id=record.deployment_id,
            candidate_id=record.candidate_id,
            stage=DeploymentStage.CANARY,
            split=split,
            started_at=record.started_at,
            promoted_at=datetime.now(UTC),
        )
        self._deployments[deployment_id] = record
        self._windows[deployment_id] = ObservationWindow(
            stage=DeploymentStage.CANARY,
            duration=self._canary_duration,
        )
        return record

    async def promote_to_stable(self, deployment_id: UUID) -> DeploymentRecord:
        """Promote to stable: 100% traffic."""
        record = self._deployments[deployment_id]
        record = DeploymentRecord(
            deployment_id=record.deployment_id,
            candidate_id=record.candidate_id,
            stage=DeploymentStage.STABLE,
            split=TrafficSplit.STABLE,
            started_at=record.started_at,
            promoted_at=datetime.now(UTC),
        )
        self._deployments[deployment_id] = record
        return record

    async def rollback(self, deployment_id: UUID, reason: str) -> DeploymentRecord:
        """Roll back the deployment and record the reason."""
        record = self._deployments[deployment_id]
        record = DeploymentRecord(
            deployment_id=record.deployment_id,
            candidate_id=record.candidate_id,
            stage=DeploymentStage.ROLLED_BACK,
            split=record.split,
            started_at=record.started_at,
            rolled_back_at=datetime.now(UTC),
            rollback_reason=reason,
        )
        self._deployments[deployment_id] = record
        return record

    async def check_guardrails(
        self,
        deployment_id: UUID,
        metrics: dict[str, float],
    ) -> GuardrailStatus:
        """Evaluate all guardrails against current metrics.

        Tracks consecutive breaches; a guardrail only fires when
        ``consecutive_breaches`` is reached.
        """
        breaches: list[str] = []
        for g in self._guardrails:
            value = metrics.get(g.metric)
            if value is None:
                self._breach_counters[g.metric] = 0
                continue
            breached = (
                (g.operator == "lt" and value < g.value)
                or (g.operator == "gt" and value > g.value)
                or (g.operator == "lte" and value <= g.value)
                or (g.operator == "gte" and value >= g.value)
            )
            if breached:
                self._breach_counters[g.metric] = self._breach_counters.get(g.metric, 0) + 1
                if self._breach_counters[g.metric] >= g.consecutive_breaches:
                    breaches.append(g.metric)
            else:
                self._breach_counters[g.metric] = 0

        passed = len(breaches) == 0
        return GuardrailStatus(
            passed=passed,
            breached_metrics=tuple(breaches),
            current_values=metrics,
        )

    async def auto_rollback_if_breached(
        self,
        deployment_id: UUID,
        metrics: dict[str, float],
    ) -> DeploymentRecord | None:
        """Check guardrails and automatically rollback if breached."""
        status = await self.check_guardrails(deployment_id, metrics)
        if not status.passed:
            reason = f"guardrail breach: {', '.join(status.breached_metrics)}"
            return await self.rollback(deployment_id, reason)
        return None

    async def get_deployment(self, deployment_id: UUID) -> DeploymentRecord:
        return self._deployments[deployment_id]

    async def get_window(self, deployment_id: UUID) -> ObservationWindow:
        return self._windows[deployment_id]


__all__ = [
    "DeploymentPipeline",
    "DeploymentRecord",
    "DeploymentStage",
    "GuardrailStatus",
    "GuardrailThreshold",
    "ObservationWindow",
    "TrafficSplit",
]
