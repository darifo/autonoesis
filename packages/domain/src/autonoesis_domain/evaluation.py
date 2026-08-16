"""Repeatable evaluation assets and independent grading results."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Any
from uuid import UUID, uuid4


class TrialStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    PASSED = "passed"
    FAILED = "failed"
    INVALID = "invalid"


class GraderStatus(StrEnum):
    PASS = "pass"
    FAIL = "fail"
    UNKNOWN = "unknown"
    INVALID = "invalid"


class GraderKind(StrEnum):
    DETERMINISTIC = "deterministic"
    OUTCOME = "outcome"
    TRAJECTORY = "trajectory"
    LLM = "llm"
    HUMAN = "human"


class CaseVisibility(StrEnum):
    PUBLIC = "public"
    HIDDEN = "hidden"
    PRODUCTION_REPLAY = "production_replay"


@dataclass(frozen=True, slots=True)
class EvaluationCase:
    case_id: str
    input_payload: dict[str, Any]
    expected_outcome: dict[str, Any]
    tags: tuple[str, ...]
    visibility: CaseVisibility = CaseVisibility.PUBLIC
    weight: float = 1.0
    gating: bool = False

    def __post_init__(self) -> None:
        if not self.case_id or self.weight <= 0:
            raise ValueError("evaluation case requires an id and positive weight")


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
    random_seed: int | None = None
    case_results: tuple[TrialCaseResult, ...] = ()
    total_cost_microunits: int = 0
    failure_reason: str | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None

    def __post_init__(self) -> None:
        if self.total_cost_microunits < 0:
            raise ValueError("trial cost cannot be negative")
        if self.status in {TrialStatus.PASSED, TrialStatus.FAILED} and (
            not self.case_results
            or any(not result.subject_executed for result in self.case_results)
        ):
            raise ValueError("a completed trial requires executed subject results")
        if any(
            grade.trial_id != self.trial_id
            for result in self.case_results
            for grade in result.grader_results
        ):
            raise ValueError("grader result must belong to its containing trial")
        if self.status is TrialStatus.INVALID and not self.failure_reason:
            raise ValueError("an invalid trial requires a failure reason")


@dataclass(frozen=True, slots=True)
class TrialCaseResult:
    case_id: str
    input_payload: dict[str, Any]
    output_payload: dict[str, Any] | None
    subject_executed: bool
    grader_results: tuple[GraderResult, ...] = ()
    evidence_refs: tuple[str, ...] = ()
    executor_id: str | None = None
    environment_ref: str | None = None
    model_ref: str | None = None
    tool_refs: tuple[str, ...] = ()
    random_seed: int | None = None
    cost_microunits: int = 0
    failure_reason: str | None = None

    def __post_init__(self) -> None:
        if self.cost_microunits < 0:
            raise ValueError("case cost cannot be negative")
        if self.subject_executed and (
            self.output_payload is None
            or not self.executor_id
            or not self.evidence_refs
            or not self.environment_ref
        ):
            raise ValueError(
                "executed subject requires output, executor, evidence, and environment"
            )
        if not self.subject_executed and not self.failure_reason:
            raise ValueError("unexecuted subject requires a failure reason")


@dataclass(frozen=True, slots=True)
class GraderResult:
    trial_id: UUID
    grader_id: str
    grader_version: str
    score: float | None
    passed: bool | None
    rationale: str
    evidence_refs: tuple[str, ...]
    status: GraderStatus | None = None
    kind: GraderKind = GraderKind.DETERMINISTIC

    def __post_init__(self) -> None:
        if self.score is not None and not 0 <= self.score <= 1:
            raise ValueError("grader score must be between zero and one")
        if self.score is None and self.passed is not None:
            raise ValueError("unknown score must have an unknown pass result")
        inferred = (
            GraderStatus.PASS
            if self.passed is True
            else GraderStatus.FAIL
            if self.passed is False
            else GraderStatus.UNKNOWN
        )
        if self.status is None:
            object.__setattr__(self, "status", inferred)
        elif self.status in {GraderStatus.PASS, GraderStatus.FAIL} and self.status is not inferred:
            raise ValueError("grader status conflicts with pass result")
        elif self.status is GraderStatus.INVALID and self.passed is not None:
            raise ValueError("invalid grader result cannot have a pass result")
