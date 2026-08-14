# mypy: ignore-errors
"""Tests for evolution package — replay, deployment, finops, slo, trials."""

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from autonoesis_domain import EvaluationCase, EvaluationSuite
from autonoesis_evolution import (
    SLI,
    BudgetEnforcer,
    CostCategory,
    CostEntry,
    CostTracker,
    DeploymentPipeline,
    DeploymentStage,
    GuardrailThreshold,
    QuantileCalculator,
    ReplayEngine,
    ReplayStatus,
    SimulationEngine,
    SimulationInput,
    SimulationScenario,
    SLOMeasurement,
    SLORegistry,
    SLOTarget,
    TrafficSplit,
    TrialBatchConfig,
    TrialRunner,
)


class TestReplayEngine:
    @pytest.mark.asyncio
    async def test_record_creates_trace(self) -> None:
        from autonoesis_domain import Run

        engine = ReplayEngine()
        run = Run(tenant_id=uuid4(), goal_id=uuid4(), agent_version_id=uuid4())
        trace = await engine.record(run, None, None, (), ())
        assert trace.run_id == run.run_id

    @pytest.mark.asyncio
    async def test_replay_fails_without_plan(self) -> None:
        from autonoesis_domain import Run

        engine = ReplayEngine()
        run = Run(tenant_id=uuid4(), goal_id=uuid4(), agent_version_id=uuid4())
        trace = await engine.record(run, None, None, (), ())
        result = await engine.replay(trace)
        assert result.status == ReplayStatus.FAILED


class TestSimulationEngine:
    @pytest.mark.asyncio
    async def test_simulate_baseline(self) -> None:
        from autonoesis_domain import Plan, Task

        engine = SimulationEngine()
        tid = uuid4()
        rid = uuid4()
        task = Task(tenant_id=tid, run_id=rid, name="t1", completion_criterion="done")
        plan = Plan(tenant_id=tid, goal_id=uuid4(), run_id=rid, tasks=(task,))
        result = await engine.simulate(plan, None, SimulationInput())
        assert result.scenario == SimulationScenario.BASELINE

    @pytest.mark.asyncio
    async def test_simulate_adversarial_flags_risk(self) -> None:
        from autonoesis_domain import Plan, Task

        engine = SimulationEngine()
        tid = uuid4()
        rid = uuid4()
        task = Task(tenant_id=tid, run_id=rid, name="t1", completion_criterion="done")
        plan = Plan(tenant_id=tid, goal_id=uuid4(), run_id=rid, tasks=(task,))
        result = await engine.simulate(
            plan,
            None,
            SimulationInput(scenario=SimulationScenario.ADVERSARIAL),
        )
        assert "adversarial_input" in result.risk_flags


class TestDeploymentPipeline:
    @pytest.mark.asyncio
    async def test_shadow_to_canary_to_stable(self) -> None:
        pipeline = DeploymentPipeline()
        cid = uuid4()

        shadow = await pipeline.promote_to_shadow(cid)
        assert shadow.stage == DeploymentStage.SHADOW

        canary = await pipeline.promote_to_canary(shadow.deployment_id, TrafficSplit.CANARY_10)
        assert canary.stage == DeploymentStage.CANARY
        assert canary.split == TrafficSplit.CANARY_10

        stable = await pipeline.promote_to_stable(canary.deployment_id)
        assert stable.stage == DeploymentStage.STABLE

    @pytest.mark.asyncio
    async def test_guardrail_breach_triggers_rollback(self) -> None:
        pipeline = DeploymentPipeline(
            guardrails=(
                GuardrailThreshold(
                    metric="error_rate",
                    operator="gt",
                    value=0.05,
                    consecutive_breaches=1,
                ),
            ),
        )
        cid = uuid4()
        rec = await pipeline.promote_to_shadow(cid)

        rolled = await pipeline.auto_rollback_if_breached(
            rec.deployment_id,
            {"error_rate": 0.10},
        )
        assert rolled is not None
        assert rolled.stage == DeploymentStage.ROLLED_BACK

    @pytest.mark.asyncio
    async def test_guardrail_pass_no_rollback(self) -> None:
        pipeline = DeploymentPipeline(
            guardrails=(GuardrailThreshold(metric="error_rate", operator="gt", value=0.05),),
        )
        cid = uuid4()
        rec = await pipeline.promote_to_shadow(cid)

        rolled = await pipeline.auto_rollback_if_breached(
            rec.deployment_id,
            {"error_rate": 0.01},
        )
        assert rolled is None


class TestCostTracker:
    @pytest.mark.asyncio
    async def test_record_and_summarize(self) -> None:
        tracker = CostTracker()
        gid = uuid4()
        rid = uuid4()

        await tracker.record(CostEntry(category=CostCategory.MODEL_TOKEN, amount=0.05, run_id=rid))
        await tracker.record(
            CostEntry(category=CostCategory.TOOL_EXECUTION, amount=0.10, run_id=rid)
        )
        await tracker.link_run_to_goal(gid, rid)

        summary = await tracker.summarize_goal(gid)
        assert summary.total_cost == pytest.approx(0.15)
        assert summary.model_tokens > 0

    @pytest.mark.asyncio
    async def test_budget_enforcement(self) -> None:
        tracker = CostTracker()
        enforcer = BudgetEnforcer(tracker)
        gid = uuid4()
        rid = uuid4()

        await tracker.record(CostEntry(category=CostCategory.MODEL_TOKEN, amount=0.95, run_id=rid))
        await tracker.link_run_to_goal(gid, rid)

        ok, _ = await enforcer.check_action(gid, 0.10, 1.0)
        assert not ok  # 0.95 spent + 0.10 estimated > 1.0

        ok, _ = await enforcer.check_action(gid, 0.01, 1.0)
        assert ok  # 0.95 + 0.01 <= 1.0


class TestSLO:
    @pytest.mark.asyncio
    async def test_record_and_compute_budget(self) -> None:
        registry = SLORegistry(
            targets=(SLOTarget(sli=SLI.OUTCOME_SUCCESS_RATE, target=0.95),),
        )
        now = datetime.now(UTC)
        await registry.record(
            SLOMeasurement(
                sli=SLI.OUTCOME_SUCCESS_RATE,
                value=0.92,
                window_start=now - timedelta(days=1),
                window_end=now,
            )
        )
        budget = await registry.compute_budget(SLI.OUTCOME_SUCCESS_RATE, now)
        assert budget.total_budget == pytest.approx(0.05)
        assert budget.consumed > 0

    @pytest.mark.asyncio
    async def test_empty_registry_full_budget(self) -> None:
        registry = SLORegistry(
            targets=(SLOTarget(sli=SLI.ACTION_SUCCESS_RATE, target=0.99),),
        )
        budget = await registry.compute_budget(SLI.ACTION_SUCCESS_RATE)
        assert budget.remaining == pytest.approx(0.01)
        assert not budget.exhausted


class TestQuantile:
    def test_quantiles_from_values(self) -> None:
        values = (0.5, 0.6, 0.7, 0.8, 0.9, 1.0)
        report = QuantileCalculator.compute(values, "score")
        assert report.count == 6
        assert report.min == 0.5
        assert report.max == 1.0
        assert report.median == 0.75 or report.median == 0.8  # depends on interpolation

    def test_empty_values(self) -> None:
        report = QuantileCalculator.compute((), "score")
        assert report.count == 0


class TestTrialRunner:
    @pytest.mark.asyncio
    async def test_run_batch(self) -> None:
        suite = EvaluationSuite(
            suite_id="s1",
            version="1",
            pass_threshold=0.5,
            cases=(EvaluationCase(case_id="c1", input_payload={}, expected_outcome={}, tags=()),),
        )
        config = TrialBatchConfig(
            suite=suite,
            subject_version_id=uuid4(),
            tenant_id=uuid4(),
            repeat_count=3,
        )
        runner = TrialRunner()
        result = await runner.run_batch(config)
        assert result.total == 3
        assert result.passed == 0
        assert result.failed == 0
        assert result.invalid == 3
        assert all(
            trial.failure_reason == "trial harness is not configured" for trial in result.trials
        )
