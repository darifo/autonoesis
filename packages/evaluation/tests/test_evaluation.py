"""Tests for evaluation package."""

from uuid import uuid4

import pytest
from autonoesis_domain import EvaluationCase, EvaluationSuite, TrialStatus
from autonoesis_evaluation import DeterministicGrader, EvaluationHarness, ThresholdGrader


class TestDeterministicGrader:
    @pytest.mark.asyncio
    async def test_pass_on_exact_match(self) -> None:
        case = EvaluationCase(
            case_id="c1",
            input_payload={"q": "test"},
            expected_outcome={"answer": 42},
            tags=(),
        )
        grader = DeterministicGrader()
        result = await grader.grade(case, {"answer": 42})
        assert result.passed

    @pytest.mark.asyncio
    async def test_fail_on_mismatch(self) -> None:
        case = EvaluationCase(
            case_id="c1",
            input_payload={"q": "test"},
            expected_outcome={"answer": 42},
            tags=(),
        )
        grader = DeterministicGrader()
        result = await grader.grade(case, {"answer": 99})
        assert not result.passed


class TestThresholdGrader:
    @pytest.mark.asyncio
    async def test_pass_above_threshold(self) -> None:
        case = EvaluationCase(
            case_id="c1",
            input_payload={},
            expected_outcome={"threshold": 0.8},
            tags=(),
        )
        grader = ThresholdGrader()
        result = await grader.grade(case, {"score": 0.9})
        assert result.passed

    @pytest.mark.asyncio
    async def test_fail_below_threshold(self) -> None:
        case = EvaluationCase(
            case_id="c1",
            input_payload={},
            expected_outcome={"threshold": 0.8},
            tags=(),
        )
        grader = ThresholdGrader()
        result = await grader.grade(case, {"score": 0.5})
        assert not result.passed


class TestEvaluationHarness:
    @pytest.mark.asyncio
    async def test_runs_suite(self) -> None:
        suite = EvaluationSuite(
            suite_id="s1",
            version="1",
            pass_threshold=0.5,
            cases=(
                EvaluationCase(
                    case_id="c1",
                    input_payload={},
                    expected_outcome={},
                    tags=(),
                ),
            ),
        )
        harness = EvaluationHarness(graders={"deterministic": DeterministicGrader()})
        trial = await harness.run_suite(
            suite=suite,
            subject_version_id=uuid4(),
            tenant_id=uuid4(),
        )
        assert trial.status == TrialStatus.PASSED
