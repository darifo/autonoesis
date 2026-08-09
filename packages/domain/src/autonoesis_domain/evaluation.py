"""Repeatable evaluation assets and independent grading results."""

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any
from uuid import UUID, uuid4


class TrialStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    PASSED = "passed"
    FAILED = "failed"
    INVALID = "invalid"


@dataclass(frozen=True, slots=True)
class EvaluationCase:
    case_id: str
    input_payload: dict[str, Any]
    expected_outcome: dict[str, Any]
    tags: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class EvaluationSuite:
    suite_id: str
    version: str
    cases: tuple[EvaluationCase, ...]
    pass_threshold: float

    def __post_init__(self) -> None:
        if not self.cases or not 0 <= self.pass_threshold <= 1:
            raise ValueError("evaluation suite requires cases and a valid threshold")


@dataclass(frozen=True, slots=True)
class Trial:
    tenant_id: UUID
    suite_id: str
    suite_version: str
    subject_version_id: UUID
    harness_version: str
    trial_id: UUID = field(default_factory=uuid4)
    status: TrialStatus = TrialStatus.PENDING


@dataclass(frozen=True, slots=True)
class GraderResult:
    trial_id: UUID
    grader_id: str
    grader_version: str
    score: float | None
    passed: bool | None
    rationale: str
    evidence_refs: tuple[str, ...]

    def __post_init__(self) -> None:
        if self.score is not None and not 0 <= self.score <= 1:
            raise ValueError("grader score must be between zero and one")
        if self.score is None and self.passed is not None:
            raise ValueError("unknown score must have an unknown pass result")
