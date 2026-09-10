"""Outcome, LLM, and Human grader backends (P1-04 next-level closures).

Each backend keeps the evaluation package's contract: assessments come only
from real evidence — an authoritative outcome readback, a verifiable model
verdict, or a recorded human decision — and every ambiguous input fails to
`unknown` instead of fabricating a pass.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from autonoesis_domain import EvaluationCase, GraderKind, GraderStatus
from autonoesis_evaluation.pipeline import GraderAssessment, GraderBackend


class OutcomeReadback(Protocol):
    """Verify one case's expected outcome against authoritative state."""

    async def verify(self, case: EvaluationCase, actual_output: dict[str, Any]) -> bool: ...


class LlmJudge(Protocol):
    """A model judge returning a strict JSON verdict for one case."""

    async def judge(self, case: EvaluationCase, actual_output: dict[str, Any]) -> str: ...


class OutcomeGraderBackend(GraderBackend):
    """Grade by reading the authoritative external state, never the claim."""

    def __init__(self, readback: OutcomeReadback) -> None:
        self._readback = readback

    async def evaluate(
        self, case: EvaluationCase, actual_output: dict[str, Any]
    ) -> GraderAssessment:
        verified = await self._readback.verify(case, actual_output)
        return GraderAssessment(
            status=GraderStatus.PASS if verified else GraderStatus.FAIL,
            score=1.0 if verified else 0.0,
            rationale=(
                "authoritative readback confirmed the expected outcome"
                if verified
                else "authoritative readback contradicts the expected outcome"
            ),
            evidence_refs=(case.case_id,),
        )


@dataclass(frozen=True, slots=True)
class LlmGraderBackend(GraderBackend):
    """Grade via a model judge; unverifiable or malformed verdicts fail closed."""

    judge: LlmJudge
    rubric_version: str

    async def evaluate(
        self, case: EvaluationCase, actual_output: dict[str, Any]
    ) -> GraderAssessment:
        import json

        raw = await self.judge.judge(case, actual_output)
        try:
            verdict = json.loads(raw)
            passed = verdict["passed"]
            rationale = verdict["rationale"]
        except (json.JSONDecodeError, KeyError, TypeError) as exc:
            return GraderAssessment(
                status=GraderStatus.UNKNOWN,
                score=None,
                rationale=f"llm judge verdict is not a strict verdict object: {exc}",
                evidence_refs=(case.case_id,),
            )
        if not isinstance(passed, bool) or not isinstance(rationale, str) or not rationale:
            return GraderAssessment(
                status=GraderStatus.UNKNOWN,
                score=None,
                rationale="llm judge verdict must carry a boolean passed and rationale",
                evidence_refs=(case.case_id,),
            )
        return GraderAssessment(
            status=GraderStatus.PASS if passed else GraderStatus.FAIL,
            score=1.0 if passed else 0.0,
            rationale=f"[rubric {self.rubric_version}] {rationale}",
            evidence_refs=(case.case_id,),
        )


@dataclass(frozen=True, slots=True)
class HumanGraderBackend(GraderBackend):
    """Grade only from recorded human decisions; absent decisions stay unknown."""

    decisions: dict[str, tuple[bool, str]]
    reviewer_id: str

    async def evaluate(
        self, case: EvaluationCase, actual_output: dict[str, Any]
    ) -> GraderAssessment:
        decision = self.decisions.get(case.case_id)
        if decision is None:
            return GraderAssessment(
                status=GraderStatus.UNKNOWN,
                score=None,
                rationale="no recorded human decision for this case",
                evidence_refs=(case.case_id,),
            )
        passed, rationale = decision
        if not rationale.strip():
            return GraderAssessment(
                status=GraderStatus.UNKNOWN,
                score=None,
                rationale="human decisions require a recorded rationale",
                evidence_refs=(case.case_id,),
            )
        return GraderAssessment(
            status=GraderStatus.PASS if passed else GraderStatus.FAIL,
            score=1.0 if passed else 0.0,
            rationale=f"[reviewer {self.reviewer_id}] {rationale}",
            evidence_refs=(case.case_id, f"human://{self.reviewer_id}/{case.case_id}"),
        )


__all__ = [
    "GraderKind",
    "HumanGraderBackend",
    "LlmGraderBackend",
    "OutcomeGraderBackend",
]
