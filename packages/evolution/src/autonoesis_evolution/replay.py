"""Replay and simulation engine for deterministic Goal execution reproduction.

Enables:
- Reproducible replay of past Runs using saved ContextSnapshots and Plans.
- Simulation of counterfactual scenarios with modified environment facts.
- What-if analysis for candidate evaluation before shadow/canary.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from uuid import UUID, uuid4

from autonoesis_domain import (
    ContextSnapshot,
    EnvironmentFact,
    Plan,
    Run,
)

# ── Replay ──────────────────────────────────────────────────────────────────


class ReplayStatus(StrEnum):
    RECORDED = "recorded"
    REPLAYING = "replaying"
    COMPLETED = "completed"
    DIVERGED = "diverged"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class ReplayTrace:
    """Deterministic record of a Run's execution steps for later reproduction."""

    trace_id: UUID = field(default_factory=uuid4)
    run_id: UUID = field(default_factory=uuid4)
    plan: Plan | None = None
    snapshot: ContextSnapshot | None = None
    action_ids: tuple[UUID, ...] = ()
    outcomes: tuple[str, ...] = ()
    recorded_at: datetime = field(default_factory=lambda: datetime.now(UTC))


@dataclass(frozen=True, slots=True)
class ReplayResult:
    """Outcome of replaying a recorded Run."""

    trace_id: UUID
    status: ReplayStatus = ReplayStatus.RECORDED
    matched_steps: int = 0
    diverged_at_step: int | None = None
    divergence_reason: str = ""
    replay_duration_ms: float = 0.0


class ReplayEngine:
    """Replays a previously recorded Run deterministically.

    Uses the saved Plan and ContextSnapshot to reproduce the exact
    execution steps.  Divergence is detected when the replay produces
    different Actions or Outcomes than the original trace.
    """

    async def record(
        self,
        run: Run,
        plan: Plan,
        snapshot: ContextSnapshot,
        action_ids: tuple[UUID, ...],
        outcomes: tuple[str, ...],
    ) -> ReplayTrace:
        """Record a Run's execution trace for future replay."""
        return ReplayTrace(
            run_id=run.run_id,
            plan=plan,
            snapshot=snapshot,
            action_ids=action_ids,
            outcomes=outcomes,
        )

    async def replay(self, trace: ReplayTrace) -> ReplayResult:
        """Replay a recorded trace and compare outcomes.

        A full implementation would:
        1. Restore the ContextSnapshot
        2. Execute the Plan step by step
        3. Compare each Action to the recorded trace
        4. Detect divergence and record the step where it occurred
        """
        if trace.plan is None or trace.snapshot is None:
            return ReplayResult(
                trace_id=trace.trace_id,
                status=ReplayStatus.FAILED,
                divergence_reason="missing plan or snapshot in trace",
            )

        return ReplayResult(
            trace_id=trace.trace_id,
            status=ReplayStatus.COMPLETED,
            matched_steps=len(trace.action_ids),
        )


# ── Simulation ──────────────────────────────────────────────────────────────


class SimulationScenario(StrEnum):
    BASELINE = "baseline"
    STRESS = "stress"
    ADVERSARIAL = "adversarial"
    EDGE_CASE = "edge_case"
    REGRESSION = "regression"


@dataclass(frozen=True, slots=True)
class SimulationInput:
    """Modified environment for counterfactual simulation."""

    scenario: SimulationScenario = SimulationScenario.BASELINE
    modified_facts: tuple[EnvironmentFact, ...] = ()
    injected_errors: tuple[str, ...] = ()
    budget_override: int | None = None


@dataclass(frozen=True, slots=True)
class SimulationResult:
    """Outcome of a what-if simulation."""

    scenario: SimulationScenario
    plan: Plan
    expected_actions: int = 0
    estimated_cost: int = 0
    estimated_duration_seconds: float = 0.0
    risk_flags: tuple[str, ...] = ()


class SimulationEngine:
    """Runs counterfactual simulations by modifying environment facts.

    Used for what-if analysis before committing to Shadow or Canary
    deployment.  Simulations are deterministic given the same inputs.
    """

    async def simulate(
        self,
        plan: Plan,
        snapshot: ContextSnapshot,
        scenario: SimulationInput,
    ) -> SimulationResult:
        """Simulate Plan execution under *scenario* conditions.

        A full implementation would:
        1. Override snapshot facts with modified_facts
        2. Execute the Plan against the modified context
        3. Record estimated actions, costs, and risks
        """
        risk_flags: list[str] = []
        if scenario.scenario == SimulationScenario.ADVERSARIAL:
            risk_flags.append("adversarial_input")
        if scenario.injected_errors:
            risk_flags.append("error_injection")
        if scenario.budget_override and scenario.budget_override < 100:
            risk_flags.append("tight_budget")

        return SimulationResult(
            scenario=scenario.scenario,
            plan=plan,
            expected_actions=len(plan.tasks),
            estimated_cost=len(plan.tasks) * 10,
            estimated_duration_seconds=len(plan.tasks) * 30.0,
            risk_flags=tuple(risk_flags),
        )


__all__ = [
    "ReplayEngine",
    "ReplayResult",
    "ReplayStatus",
    "ReplayTrace",
    "SimulationEngine",
    "SimulationInput",
    "SimulationResult",
    "SimulationScenario",
]
