"""AI FinOps — Per-Goal cost tracking, budget enforcement, and efficiency metrics.

Tracks token usage, tool invocation costs, and sandbox time across the
Goal → Run → Task → Action hierarchy.  Computes cost-per-verified-Goal
as the primary optimization target.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from uuid import UUID, uuid4


class CostCategory(StrEnum):
    MODEL_TOKEN = "model_token"
    TOOL_EXECUTION = "tool_execution"
    SANDBOX_TIME = "sandbox_time"
    APPROVAL_WAIT = "approval_wait"
    RETRY_WASTE = "retry_waste"


@dataclass(frozen=True, slots=True)
class CostEntry:
    """A single cost line item."""

    entry_id: UUID = field(default_factory=uuid4)
    category: CostCategory = CostCategory.MODEL_TOKEN
    amount: float = 0.0
    currency: str = "usd"
    description: str = ""
    run_id: UUID = field(default_factory=uuid4)
    action_id: UUID | None = None
    recorded_at: datetime = field(default_factory=lambda: datetime.now(UTC))


@dataclass(frozen=True, slots=True)
class GoalCostSummary:
    """Total cost breakdown for a single Goal."""

    goal_id: UUID
    total_cost: float = 0.0
    model_tokens: float = 0.0
    tool_executions: float = 0.0
    sandbox_time: float = 0.0
    approval_wait: float = 0.0
    retry_waste: float = 0.0
    run_count: int = 0
    verified_outcome: bool = False
    computed_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    @property
    def cost_per_verified_outcome(self) -> float | None:
        if not self.verified_outcome or self.run_count == 0:
            return None
        return self.total_cost / self.run_count


class CostTracker:
    """Tracks and aggregates costs across the Goal lifecycle.

    Links each Run to its Goal so that cost aggregation is per-Goal.
    """

    def __init__(self) -> None:
        self._entries: list[CostEntry] = []
        self._goal_runs: dict[UUID, set[UUID]] = {}

    async def record(self, entry: CostEntry) -> None:
        self._entries.append(entry)

    async def link_run_to_goal(self, goal_id: UUID, run_id: UUID) -> None:
        """Associate a Run with its parent Goal for cost tracking."""
        self._goal_runs.setdefault(goal_id, set()).add(run_id)

    async def summarize_goal(self, goal_id: UUID) -> GoalCostSummary:
        run_ids = self._goal_runs.get(goal_id, set())
        goal_entries = [e for e in self._entries if e.run_id in run_ids]
        by_cat: dict[CostCategory, float] = {c: 0.0 for c in CostCategory}
        for e in goal_entries:
            by_cat[e.category] += e.amount

        return GoalCostSummary(
            goal_id=goal_id,
            total_cost=sum(by_cat.values()),
            model_tokens=by_cat[CostCategory.MODEL_TOKEN],
            tool_executions=by_cat[CostCategory.TOOL_EXECUTION],
            sandbox_time=by_cat[CostCategory.SANDBOX_TIME],
            approval_wait=by_cat[CostCategory.APPROVAL_WAIT],
            retry_waste=by_cat[CostCategory.RETRY_WASTE],
            run_count=len({e.run_id for e in goal_entries}),
        )

    async def budget_remaining(
        self,
        goal_id: UUID,
        budget_limit: float,
    ) -> tuple[float, bool]:
        summary = await self.summarize_goal(goal_id)
        remaining = budget_limit - summary.total_cost
        return remaining, remaining > 0


class BudgetEnforcer:
    """Enforces budget limits at the Goal, Run, and Action levels."""

    def __init__(self, tracker: CostTracker) -> None:
        self._tracker = tracker

    async def check_action(
        self,
        goal_id: UUID,
        estimated_cost: float,
        budget_limit: float,
    ) -> tuple[bool, str]:
        """Check if an Action can proceed within budget."""
        remaining, ok = await self._tracker.budget_remaining(goal_id, budget_limit)
        if not ok:
            return False, f"budget exhausted: {remaining:.2f} remaining"
        if estimated_cost > remaining:
            return False, f"estimated cost {estimated_cost:.2f} exceeds remaining {remaining:.2f}"
        return True, "ok"


__all__ = [
    "BudgetEnforcer",
    "CostCategory",
    "CostEntry",
    "CostTracker",
    "GoalCostSummary",
]
