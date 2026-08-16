"""Tests for evaluation package."""

from typing import Any
from uuid import UUID, uuid4

import pytest
from autonoesis_domain import (
    CaseVisibility,
    EvaluationCase,
    EvaluationSuite,
    GraderResult,
    TrialStatus,
)
from autonoesis_evaluation import (
    DeterministicGrader,
    EvaluationHarness,
    EvaluationSuiteCatalog,
    Grader,
    SubjectExecutionResult,
    SuiteAccessContext,
    SuiteAccessRole,
    ThresholdGrader,
)


class RecordingExecutor:
    def __init__(
        self,
        output: dict[str, Any] | None = None,
        executor_id: str = "subject-runtime",
    ) -> None:
        self.output = output or {}
        self.executor_id = executor_id
        self.calls: list[tuple[UUID, dict[str, Any], int]] = []

    async def execute(
        self,
        subject_version_id: UUID,
        input_payload: dict[str, Any],
        random_seed: int,
    ) -> SubjectExecutionResult:
        self.calls.append((subject_version_id, input_payload, random_seed))
        return SubjectExecutionResult(
            subject_version_id=subject_version_id,
            output_payload=self.output,
            executor_id=self.executor_id,
            evidence_refs=("evidence://execution/1",),
            environment_ref="environment://fixture/1",
            model_ref="model://fixed/1",
            tool_refs=("tool://read/1",),
            cost_microunits=17,
        )


class FailingExecutor(RecordingExecutor):
    async def execute(
        self,
        subject_version_id: UUID,
        input_payload: dict[str, Any],
        random_seed: int,
    ) -> SubjectExecutionResult:
        raise ConnectionError("runtime unavailable")


class UnknownGrader(Grader):
    async def grade(self, case: EvaluationCase, actual_output: dict[str, Any]) -> GraderResult:
        return GraderResult(
            trial_id=uuid4(),
            grader_id="unknown",
            grader_version="1",
            score=None,
            passed=None,
            rationale="grader dependency unavailable",
            evidence_refs=(),
        )


class FailingGrader(Grader):
    async def grade(self, case: EvaluationCase, actual_output: dict[str, Any]) -> GraderResult:
        raise TimeoutError("grader unavailable")


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
        subject_version_id = uuid4()
        executor = RecordingExecutor({"answer": 42})
        suite = EvaluationSuite(
            suite_id="s1",
            version="1",
            pass_threshold=0.5,
            cases=(
                EvaluationCase(
                    case_id="c1",
                    input_payload={"question": "meaning"},
                    expected_outcome={"answer": 42},
                    tags=(),
                ),
            ),
        )
        harness = EvaluationHarness(
            subject_executor=executor,
            graders={"deterministic": DeterministicGrader()},
        )
        trial = await harness.run_suite(
            suite=suite,
            subject_version_id=subject_version_id,
            tenant_id=uuid4(),
            random_seed=41,
        )
        assert trial.status == TrialStatus.PASSED
        assert executor.calls == [(subject_version_id, {"question": "meaning"}, 41)]
        assert trial.case_results[0].subject_executed
        assert trial.case_results[0].output_payload == {"answer": 42}
        assert trial.case_results[0].evidence_refs == ("evidence://execution/1",)
        assert trial.case_results[0].executor_id == "subject-runtime"
        assert trial.case_results[0].grader_results[0].trial_id == trial.trial_id
        assert trial.total_cost_microunits == 17

    @pytest.mark.asyncio
    async def test_missing_subject_executor_is_invalid_not_passed(self) -> None:
        suite = EvaluationSuite("s1", "1", (EvaluationCase("c1", {}, {}, ()),), 1.0)
        trial = await EvaluationHarness(graders={"deterministic": DeterministicGrader()}).run_suite(
            suite, uuid4(), uuid4()
        )
        assert trial.status is TrialStatus.INVALID
        assert trial.failure_reason == "subject executor is not configured"

    @pytest.mark.asyncio
    async def test_infrastructure_failure_is_invalid_not_failed(self) -> None:
        suite = EvaluationSuite("s1", "1", (EvaluationCase("c1", {}, {}, ()),), 1.0)
        trial = await EvaluationHarness(
            subject_executor=FailingExecutor(),
            graders={"deterministic": DeterministicGrader()},
        ).run_suite(suite, uuid4(), uuid4())
        assert trial.status is TrialStatus.INVALID
        assert "ConnectionError" in (trial.failure_reason or "")
        assert not trial.case_results[0].subject_executed

    @pytest.mark.asyncio
    async def test_unknown_grade_cannot_be_counted_as_green(self) -> None:
        suite = EvaluationSuite("s1", "1", (EvaluationCase("c1", {}, {}, ()),), 1.0)
        trial = await EvaluationHarness(
            subject_executor=RecordingExecutor(), graders={"unknown": UnknownGrader()}
        ).run_suite(suite, uuid4(), uuid4())
        assert trial.status is TrialStatus.INVALID
        assert "grader returned unknown" in (trial.failure_reason or "")

    @pytest.mark.asyncio
    async def test_grader_infrastructure_failure_is_invalid(self) -> None:
        suite = EvaluationSuite("s1", "1", (EvaluationCase("c1", {}, {}, ()),), 1.0)
        trial = await EvaluationHarness(
            subject_executor=RecordingExecutor(), graders={"failing": FailingGrader()}
        ).run_suite(suite, uuid4(), uuid4())
        assert trial.status is TrialStatus.INVALID
        assert "TimeoutError" in (trial.failure_reason or "")
        assert trial.case_results[0].subject_executed

    @pytest.mark.asyncio
    async def test_subject_executor_cannot_grade_its_own_output(self) -> None:
        suite = EvaluationSuite("s1", "1", (EvaluationCase("c1", {}, {}, ()),), 1.0)
        trial = await EvaluationHarness(
            subject_executor=RecordingExecutor(executor_id="deterministic"),
            graders={"deterministic": DeterministicGrader()},
        ).run_suite(suite, uuid4(), uuid4())
        assert trial.status is TrialStatus.INVALID
        assert "share identity" in (trial.failure_reason or "")

    @pytest.mark.asyncio
    async def test_gating_case_failure_overrides_weighted_pass_rate(self) -> None:
        suite = EvaluationSuite(
            "s1",
            "1",
            (
                EvaluationCase("normal", {}, {"answer": 42}, (), weight=100),
                EvaluationCase(
                    "security",
                    {},
                    {"access": "denied"},
                    (),
                    weight=1,
                    gating=True,
                ),
            ),
            0.8,
        )
        trial = await EvaluationHarness(
            subject_executor=RecordingExecutor({"answer": 42, "access": "allowed"}),
            graders={"deterministic": DeterministicGrader()},
        ).run_suite(suite, uuid4(), uuid4())
        assert trial.status is TrialStatus.FAILED

    @pytest.mark.asyncio
    async def test_protected_suite_requires_catalog_authorization(self) -> None:
        suite = EvaluationSuite(
            "hidden",
            "1",
            (
                EvaluationCase(
                    "secret",
                    {"hidden": True},
                    {"answer": 42},
                    (),
                    CaseVisibility.HIDDEN,
                ),
            ),
            1.0,
        )
        executor = RecordingExecutor({"answer": 42})
        harness = EvaluationHarness(
            subject_executor=executor,
            graders={"deterministic": DeterministicGrader()},
        )

        denied = await harness.run_suite(suite, uuid4(), uuid4())
        assert denied.status is TrialStatus.INVALID
        assert not executor.calls

        authorized = EvaluationSuiteCatalog((suite,)).load_for_harness(
            "hidden",
            "1",
            SuiteAccessContext(uuid4(), frozenset({SuiteAccessRole.EVALUATION_HARNESS})),
        )
        allowed = await harness.run_suite(authorized, uuid4(), uuid4())
        assert allowed.status is TrialStatus.PASSED
