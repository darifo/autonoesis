"""Ordered, identity-separated Grader pipeline."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol
from uuid import UUID

from autonoesis_domain import (
    EvaluationCase,
    GraderKind,
    GraderResult,
    GraderStatus,
)


class Grader(Protocol):
    async def grade(self, case: EvaluationCase, actual_output: dict[str, Any]) -> GraderResult: ...


@dataclass(frozen=True, slots=True)
class GraderAssessment:
    status: GraderStatus
    score: float | None
    rationale: str
    evidence_refs: tuple[str, ...]


class GraderBackend(Protocol):
    async def evaluate(
        self, case: EvaluationCase, actual_output: dict[str, Any]
    ) -> GraderAssessment: ...


@dataclass(frozen=True, slots=True)
class IndependentGrader:
    """Binds a separately configured identity and backend to one governance stage."""

    kind: GraderKind
    grader_id: str
    grader_version: str
    backend: GraderBackend

    def __post_init__(self) -> None:
        if not self.grader_id or not self.grader_version:
            raise ValueError("independent grader requires identity and version")

    async def grade(self, case: EvaluationCase, actual_output: dict[str, Any]) -> GraderResult:
        assessment = await self.backend.evaluate(case, actual_output)
        passed = (
            True
            if assessment.status is GraderStatus.PASS
            else False
            if assessment.status is GraderStatus.FAIL
            else None
        )
        return GraderResult(
            trial_id=UUID(int=0),
            grader_id=self.grader_id,
            grader_version=self.grader_version,
            score=assessment.score,
            passed=passed,
            rationale=assessment.rationale,
            evidence_refs=assessment.evidence_refs,
            status=assessment.status,
            kind=self.kind,
        )


_PRIORITY = {
    GraderKind.DETERMINISTIC: 0,
    GraderKind.OUTCOME: 1,
    GraderKind.TRAJECTORY: 2,
    GraderKind.LLM: 3,
    GraderKind.HUMAN: 4,
}


@dataclass(frozen=True, slots=True)
class GraderStage:
    kind: GraderKind
    grader: Grader


@dataclass(frozen=True, slots=True)
class GraderPipeline:
    """Executes Graders in governance order and stops on any non-pass result."""

    stages: tuple[GraderStage, ...]

    def __post_init__(self) -> None:
        if not self.stages:
            raise ValueError("grader pipeline requires at least one stage")
        kinds = tuple(stage.kind for stage in self.stages)
        if len(set(kinds)) != len(kinds):
            raise ValueError("grader pipeline cannot repeat a stage kind")
        if tuple(sorted(kinds, key=_PRIORITY.__getitem__)) != kinds:
            raise ValueError("grader stages must follow governance priority order")

    async def grade(
        self,
        case: EvaluationCase,
        actual_output: dict[str, Any],
    ) -> tuple[GraderResult, ...]:
        results: list[GraderResult] = []
        identities: set[str] = set()
        for stage in self.stages:
            result = await stage.grader.grade(case, actual_output)
            if result.kind is not stage.kind:
                raise ValueError(
                    f"grader {result.grader_id} returned {result.kind.value} "
                    f"for {stage.kind.value} stage"
                )
            if result.grader_id in identities:
                raise PermissionError("grader identities must be distinct across pipeline stages")
            identities.add(result.grader_id)
            results.append(result)
            if result.status is not GraderStatus.PASS:
                break
        return tuple(results)


__all__ = [
    "Grader",
    "GraderAssessment",
    "GraderBackend",
    "GraderPipeline",
    "GraderStage",
    "IndependentGrader",
]
