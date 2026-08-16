"""Views that keep hidden and production-replay Cases away from Candidate generators."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from uuid import UUID

from autonoesis_domain import CaseVisibility, EvaluationSuite


class SuiteAccessRole(StrEnum):
    CANDIDATE_GENERATOR = "candidate_generator"
    EVALUATION_HARNESS = "evaluation_harness"


@dataclass(frozen=True, slots=True)
class SuiteAccessContext:
    principal_id: UUID
    roles: frozenset[SuiteAccessRole]


@dataclass(frozen=True, slots=True)
class PublicCaseDescriptor:
    case_id: str
    tags: tuple[str, ...]
    weight: float
    gating: bool


@dataclass(frozen=True, slots=True)
class GeneratorSuiteView:
    suite_id: str
    version: str
    pass_threshold: float
    public_cases: tuple[PublicCaseDescriptor, ...]
    protected_case_count: int


@dataclass(frozen=True, slots=True)
class HarnessSuite:
    suite: EvaluationSuite
    loaded_by: UUID


class EvaluationSuiteCatalog:
    def __init__(self, suites: tuple[EvaluationSuite, ...]) -> None:
        self._suites = {(suite.suite_id, suite.version): suite for suite in suites}
        if len(self._suites) != len(suites):
            raise ValueError("evaluation suites require unique id and version")

    def describe_for_generator(self, suite_id: str, version: str) -> GeneratorSuiteView:
        suite = self._get(suite_id, version)
        public_cases = tuple(
            PublicCaseDescriptor(case.case_id, case.tags, case.weight, case.gating)
            for case in suite.cases
            if case.visibility is CaseVisibility.PUBLIC
        )
        return GeneratorSuiteView(
            suite_id=suite.suite_id,
            version=suite.version,
            pass_threshold=suite.pass_threshold,
            public_cases=public_cases,
            protected_case_count=len(suite.cases) - len(public_cases),
        )

    def load_for_harness(
        self,
        suite_id: str,
        version: str,
        access: SuiteAccessContext,
    ) -> HarnessSuite:
        if SuiteAccessRole.CANDIDATE_GENERATOR in access.roles:
            raise PermissionError("candidate generator cannot read protected evaluation cases")
        if SuiteAccessRole.EVALUATION_HARNESS not in access.roles:
            raise PermissionError("evaluation harness role is required")
        return HarnessSuite(self._get(suite_id, version), access.principal_id)

    def _get(self, suite_id: str, version: str) -> EvaluationSuite:
        try:
            return self._suites[(suite_id, version)]
        except KeyError as exc:
            raise KeyError(f"evaluation suite not found: {suite_id}@{version}") from exc


__all__ = [
    "EvaluationSuiteCatalog",
    "GeneratorSuiteView",
    "HarnessSuite",
    "PublicCaseDescriptor",
    "SuiteAccessContext",
    "SuiteAccessRole",
]
