"""EvaluationCase, Suite, Trial, Harness, and Grader for Autonoesis."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import UTC, datetime
from typing import Any, Protocol
from uuid import UUID, uuid4

from autonoesis_domain import (
    CaseVisibility,
    EvaluationCase,
    EvaluationSuite,
    GraderKind,
    GraderResult,
    GraderStatus,
    Trial,
    TrialCaseResult,
    TrialStatus,
)

from autonoesis_evaluation.pipeline import (
    Grader,
    GraderAssessment,
    GraderBackend,
    GraderPipeline,
    GraderStage,
    IndependentGrader,
)
from autonoesis_evaluation.suite_access import (
    EvaluationSuiteCatalog,
    GeneratorSuiteView,
    HarnessSuite,
    PublicCaseDescriptor,
    SuiteAccessContext,
    SuiteAccessRole,
)

# ── Harness ─────────────────────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class SubjectExecutionResult:
    """Auditable output produced by executing one fixed subject version."""

    subject_version_id: UUID
    output_payload: dict[str, Any]
    executor_id: str
    evidence_refs: tuple[str, ...]
    environment_ref: str
    model_ref: str | None = None
    tool_refs: tuple[str, ...] = ()
    cost_microunits: int = 0

    def __post_init__(self) -> None:
        if not self.executor_id or not self.evidence_refs or not self.environment_ref:
            raise ValueError("subject execution requires executor, evidence, and environment")
        if self.cost_microunits < 0:
            raise ValueError("subject execution cost cannot be negative")


class SubjectExecutor(Protocol):
    async def execute(
        self,
        subject_version_id: UUID,
        input_payload: dict[str, Any],
        random_seed: int,
    ) -> SubjectExecutionResult: ...


class EvaluationHarness:
    """Runs an EvaluationSuite against a subject version.

    Orchestrates case execution, result collection, and Trial management.
    """

    def __init__(
        self,
        subject_executor: SubjectExecutor | None = None,
        graders: dict[str, Grader] | None = None,
        *,
        grader_pipeline: GraderPipeline | None = None,
        harness_version: str = "2",
    ) -> None:
        self._subject_executor = subject_executor
        self._grader_pipeline: GraderPipeline | None
        if grader_pipeline is not None and graders:
            raise ValueError("configure grader_pipeline or legacy graders, not both")
        if grader_pipeline is not None:
            self._grader_pipeline = grader_pipeline
        elif graders:
            known_kinds = {kind.value: kind for kind in GraderKind}
            self._grader_pipeline = GraderPipeline(
                tuple(
                    GraderStage(known_kinds.get(name, GraderKind.DETERMINISTIC), grader)
                    for name, grader in graders.items()
                )
            )
        else:
            self._grader_pipeline = None
        self._harness_version = harness_version

    async def run_suite(
        self,
        suite: EvaluationSuite | HarnessSuite,
        subject_version_id: UUID,
        tenant_id: UUID,
        *,
        random_seed: int = 0,
    ) -> Trial:
        """Execute the exact subject version and grade only its recorded outputs."""
        started_at = datetime.now(UTC)
        trial_id = uuid4()
        resolved_suite = suite.suite if isinstance(suite, HarnessSuite) else suite
        if not isinstance(suite, HarnessSuite) and any(
            case.visibility is not CaseVisibility.PUBLIC for case in resolved_suite.cases
        ):
            return self._invalid_trial(
                resolved_suite,
                subject_version_id,
                tenant_id,
                random_seed,
                started_at,
                "protected suite must be loaded through the evaluation catalog",
                trial_id=trial_id,
            )
        suite = resolved_suite
        if self._subject_executor is None:
            return self._invalid_trial(
                suite,
                subject_version_id,
                tenant_id,
                random_seed,
                started_at,
                "subject executor is not configured",
                trial_id=trial_id,
            )
        if self._grader_pipeline is None:
            return self._invalid_trial(
                suite,
                subject_version_id,
                tenant_id,
                random_seed,
                started_at,
                "no independent grader is configured",
                trial_id=trial_id,
            )

        case_results: list[TrialCaseResult] = []
        for index, case in enumerate(suite.cases):
            case_seed = random_seed + index
            try:
                execution = await self._subject_executor.execute(
                    subject_version_id,
                    case.input_payload,
                    case_seed,
                )
            except Exception as exc:
                reason = f"subject execution failed: {type(exc).__name__}: {exc}"
                case_results.append(
                    TrialCaseResult(
                        case_id=case.case_id,
                        input_payload=case.input_payload,
                        output_payload=None,
                        subject_executed=False,
                        random_seed=case_seed,
                        failure_reason=reason,
                    )
                )
                return self._invalid_trial(
                    suite,
                    subject_version_id,
                    tenant_id,
                    random_seed,
                    started_at,
                    reason,
                    tuple(case_results),
                    trial_id,
                )
            if execution.subject_version_id != subject_version_id:
                reason = "executor returned output from a different subject version"
                case_results.append(
                    TrialCaseResult(
                        case_id=case.case_id,
                        input_payload=case.input_payload,
                        output_payload=None,
                        subject_executed=False,
                        random_seed=case_seed,
                        failure_reason=reason,
                    )
                )
                return self._invalid_trial(
                    suite,
                    subject_version_id,
                    tenant_id,
                    random_seed,
                    started_at,
                    reason,
                    tuple(case_results),
                    trial_id,
                )

            try:
                grader_results = tuple(
                    replace(grade, trial_id=trial_id)
                    for grade in await self._grader_pipeline.grade(case, execution.output_payload)
                )
            except Exception as exc:
                reason = f"grader execution failed: {type(exc).__name__}: {exc}"
                case_results.append(
                    TrialCaseResult(
                        case_id=case.case_id,
                        input_payload=case.input_payload,
                        output_payload=execution.output_payload,
                        subject_executed=True,
                        evidence_refs=execution.evidence_refs,
                        executor_id=execution.executor_id,
                        environment_ref=execution.environment_ref,
                        model_ref=execution.model_ref,
                        tool_refs=execution.tool_refs,
                        random_seed=case_seed,
                        cost_microunits=execution.cost_microunits,
                        failure_reason=reason,
                    )
                )
                return self._invalid_trial(
                    suite,
                    subject_version_id,
                    tenant_id,
                    random_seed,
                    started_at,
                    reason,
                    tuple(case_results),
                    trial_id,
                )
            case_results.append(
                TrialCaseResult(
                    case_id=case.case_id,
                    input_payload=case.input_payload,
                    output_payload=execution.output_payload,
                    subject_executed=True,
                    grader_results=grader_results,
                    evidence_refs=execution.evidence_refs,
                    executor_id=execution.executor_id,
                    environment_ref=execution.environment_ref,
                    model_ref=execution.model_ref,
                    tool_refs=execution.tool_refs,
                    random_seed=case_seed,
                    cost_microunits=execution.cost_microunits,
                )
            )

        identity_conflict = next(
            (
                grade.grader_id
                for case_result in case_results
                for grade in case_result.grader_results
                if grade.grader_id == case_result.executor_id
            ),
            None,
        )
        if identity_conflict is not None:
            return self._invalid_trial(
                suite,
                subject_version_id,
                tenant_id,
                random_seed,
                started_at,
                f"subject executor and grader share identity: {identity_conflict}",
                tuple(case_results),
                trial_id,
            )

        uncertain = next(
            (
                result
                for case_result in case_results
                for result in case_result.grader_results
                if result.status in {GraderStatus.UNKNOWN, GraderStatus.INVALID}
            ),
            None,
        )
        if uncertain is not None:
            uncertain_status = uncertain.status or GraderStatus.UNKNOWN
            return self._invalid_trial(
                suite,
                subject_version_id,
                tenant_id,
                random_seed,
                started_at,
                f"grader returned {uncertain_status.value}: {uncertain.rationale}",
                tuple(case_results),
                trial_id,
            )

        case_passes = tuple(
            bool(result.grader_results)
            and all(grade.status is GraderStatus.PASS for grade in result.grader_results)
            for result in case_results
        )
        gating_failed = any(
            case.gating and not passed
            for case, passed in zip(suite.cases, case_passes, strict=True)
        )
        total_weight = sum(case.weight for case in suite.cases)
        passed_weight = sum(
            case.weight for case, passed in zip(suite.cases, case_passes, strict=True) if passed
        )
        status = (
            TrialStatus.PASSED
            if not gating_failed and passed_weight / total_weight >= suite.pass_threshold
            else TrialStatus.FAILED
        )
        return Trial(
            tenant_id=tenant_id,
            suite_id=suite.suite_id,
            suite_version=suite.version,
            subject_version_id=subject_version_id,
            harness_version=self._harness_version,
            trial_id=trial_id,
            status=status,
            random_seed=random_seed,
            case_results=tuple(case_results),
            total_cost_microunits=sum(result.cost_microunits for result in case_results),
            started_at=started_at,
            completed_at=datetime.now(UTC),
        )

    def _invalid_trial(
        self,
        suite: EvaluationSuite,
        subject_version_id: UUID,
        tenant_id: UUID,
        random_seed: int,
        started_at: datetime,
        reason: str,
        case_results: tuple[TrialCaseResult, ...] = (),
        trial_id: UUID | None = None,
    ) -> Trial:
        return Trial(
            tenant_id=tenant_id,
            suite_id=suite.suite_id,
            suite_version=suite.version,
            subject_version_id=subject_version_id,
            harness_version=self._harness_version,
            trial_id=trial_id or uuid4(),
            status=TrialStatus.INVALID,
            random_seed=random_seed,
            case_results=case_results,
            total_cost_microunits=sum(result.cost_microunits for result in case_results),
            failure_reason=reason,
            started_at=started_at,
            completed_at=datetime.now(UTC),
        )


class DeterministicGrader(Grader):
    """Grader that checks output against expected values using exact match."""

    async def grade(self, case: EvaluationCase, actual_output: dict[str, Any]) -> GraderResult:
        expected = case.expected_outcome
        passed = True

        for key, expected_value in expected.items():
            actual_value = actual_output.get(key)
            if actual_value != expected_value:
                passed = False
                break

        return GraderResult(
            trial_id=uuid4(),
            grader_id="deterministic",
            grader_version="1",
            score=1.0 if passed else 0.0,
            passed=passed,
            rationale=f"exact match check: {passed}",
            evidence_refs=(case.case_id,),
        )


class ThresholdGrader(Grader):
    """Grader that checks a numeric score against a case-defined threshold."""

    async def grade(self, case: EvaluationCase, actual_output: dict[str, Any]) -> GraderResult:
        score = float(actual_output.get("score", 0))
        threshold = float(case.expected_outcome.get("threshold", 0.8))
        passed = score >= threshold

        return GraderResult(
            trial_id=uuid4(),
            grader_id="threshold",
            grader_version="1",
            score=score,
            passed=passed,
            rationale=f"score {score} >= {threshold}: {passed}",
            evidence_refs=(case.case_id,),
        )


__all__ = [
    "DeterministicGrader",
    "EvaluationHarness",
    "EvaluationSuiteCatalog",
    "GeneratorSuiteView",
    "Grader",
    "GraderAssessment",
    "GraderBackend",
    "GraderPipeline",
    "GraderStage",
    "HarnessSuite",
    "IndependentGrader",
    "PublicCaseDescriptor",
    "SubjectExecutionResult",
    "SubjectExecutor",
    "SuiteAccessContext",
    "SuiteAccessRole",
    "ThresholdGrader",
]
