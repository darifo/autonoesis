"""EvaluationCase, Suite, Trial, Harness, and Grader for Autonoesis."""

from __future__ import annotations

from dataclasses import dataclass  # noqa: F401
from typing import Any
from uuid import UUID, uuid4

from autonoesis_domain import (
    EvaluationCase,
    EvaluationSuite,
    GraderResult,
    Trial,
    TrialStatus,
)

# ── Harness ─────────────────────────────────────────────────────────────────


class EvaluationHarness:
    """Runs an EvaluationSuite against a subject version.

    Orchestrates case execution, result collection, and Trial management.
    """

    def __init__(self, graders: dict[str, Grader] | None = None) -> None:
        self._graders = graders or {}

    async def run_suite(
        self,
        suite: EvaluationSuite,
        subject_version_id: UUID,
        tenant_id: UUID,
    ) -> Trial:
        """Execute all cases in *suite* and return a completed Trial."""
        trial = Trial(
            tenant_id=tenant_id,
            suite_id=suite.suite_id,
            suite_version=suite.version,
            subject_version_id=subject_version_id,
            harness_version="1",
            status=TrialStatus.RUNNING,
        )

        results: list[GraderResult] = []
        for case in suite.cases:
            grader = self._graders.get("deterministic", DeterministicGrader())
            result = await grader.grade(case, {})
            results.append(result)
        threshold_met = (
            sum(1 for r in results if r.passed is True) / max(len(results), 1)
            >= suite.pass_threshold
        )

        return Trial(
            tenant_id=trial.tenant_id,
            suite_id=trial.suite_id,
            suite_version=trial.suite_version,
            subject_version_id=trial.subject_version_id,
            harness_version=trial.harness_version,
            status=TrialStatus.PASSED if threshold_met else TrialStatus.FAILED,
        )


# ── Grader ──────────────────────────────────────────────────────────────────


class Grader:
    """Abstract grader that evaluates a single EvaluationCase."""

    async def grade(self, case: EvaluationCase, actual_output: dict[str, Any]) -> GraderResult:
        raise NotImplementedError


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
    "Grader",
    "ThresholdGrader",
]
