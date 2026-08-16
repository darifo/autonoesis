"""Governance tests for ordered Graders and protected evaluation data."""

from dataclasses import asdict
from typing import Any
from uuid import uuid4

import pytest
from autonoesis_domain import (
    CaseVisibility,
    EvaluationCase,
    EvaluationSuite,
    GraderKind,
    GraderStatus,
)
from autonoesis_evaluation import (
    EvaluationSuiteCatalog,
    GraderAssessment,
    GraderPipeline,
    GraderStage,
    IndependentGrader,
    SuiteAccessContext,
    SuiteAccessRole,
)


class RecordingBackend:
    def __init__(
        self,
        name: str,
        calls: list[str],
        status: GraderStatus = GraderStatus.PASS,
    ) -> None:
        self.name = name
        self.calls = calls
        self.status = status

    async def evaluate(
        self, case: EvaluationCase, actual_output: dict[str, Any]
    ) -> GraderAssessment:
        self.calls.append(self.name)
        return GraderAssessment(
            status=self.status,
            score=1.0 if self.status is GraderStatus.PASS else 0.0,
            rationale=self.name,
            evidence_refs=(f"evidence://grader/{self.name}",),
        )


def _case() -> EvaluationCase:
    return EvaluationCase("case", {}, {}, ())


def _stage(
    kind: GraderKind,
    calls: list[str],
    *,
    identity: str | None = None,
    status: GraderStatus = GraderStatus.PASS,
) -> GraderStage:
    return GraderStage(
        kind,
        IndependentGrader(
            kind,
            identity or f"{kind.value}-principal",
            "1",
            RecordingBackend(kind.value, calls, status),
        ),
    )


@pytest.mark.asyncio
async def test_pipeline_runs_all_grader_kinds_in_governance_order() -> None:
    calls: list[str] = []
    kinds = tuple(GraderKind)
    pipeline = GraderPipeline(tuple(_stage(kind, calls) for kind in kinds))

    results = await pipeline.grade(_case(), {"answer": 42})

    assert calls == [kind.value for kind in kinds]
    assert tuple(result.kind for result in results) == kinds
    assert all(result.status is GraderStatus.PASS for result in results)


@pytest.mark.asyncio
async def test_pipeline_stops_before_lower_priority_graders_after_failure() -> None:
    calls: list[str] = []
    pipeline = GraderPipeline(
        (
            _stage(GraderKind.DETERMINISTIC, calls),
            _stage(GraderKind.OUTCOME, calls, status=GraderStatus.FAIL),
            _stage(GraderKind.TRAJECTORY, calls),
        )
    )

    results = await pipeline.grade(_case(), {})

    assert calls == ["deterministic", "outcome"]
    assert results[-1].status is GraderStatus.FAIL


@pytest.mark.asyncio
async def test_pipeline_rejects_reused_grader_identity() -> None:
    calls: list[str] = []
    pipeline = GraderPipeline(
        (
            _stage(GraderKind.DETERMINISTIC, calls, identity="same-principal"),
            _stage(GraderKind.OUTCOME, calls, identity="same-principal"),
        )
    )
    with pytest.raises(PermissionError, match="identities must be distinct"):
        await pipeline.grade(_case(), {})


def test_generator_view_contains_no_hidden_or_replay_payload() -> None:
    suite = EvaluationSuite(
        "release-gate",
        "1",
        (
            EvaluationCase("public", {"visible": True}, {}, ("public",)),
            EvaluationCase(
                "hidden-secret",
                {"secret_prompt": "do not leak"},
                {"answer": "hidden"},
                ("security",),
                CaseVisibility.HIDDEN,
            ),
            EvaluationCase(
                "customer-replay",
                {"customer_data": "restricted"},
                {"answer": "private"},
                ("replay",),
                CaseVisibility.PRODUCTION_REPLAY,
            ),
        ),
        0.8,
    )
    catalog = EvaluationSuiteCatalog((suite,))

    view = catalog.describe_for_generator("release-gate", "1")
    serialized = repr(asdict(view))

    assert tuple(case.case_id for case in view.public_cases) == ("public",)
    assert view.protected_case_count == 2
    assert "secret_prompt" not in serialized
    assert "customer_data" not in serialized
    assert "hidden-secret" not in serialized
    assert "customer-replay" not in serialized


def test_generator_role_cannot_load_harness_suite_even_when_role_is_combined() -> None:
    suite = EvaluationSuite("s", "1", (_case(),), 1.0)
    catalog = EvaluationSuiteCatalog((suite,))
    access = SuiteAccessContext(
        uuid4(),
        frozenset({SuiteAccessRole.CANDIDATE_GENERATOR, SuiteAccessRole.EVALUATION_HARNESS}),
    )
    with pytest.raises(PermissionError, match="generator cannot read"):
        catalog.load_for_harness("s", "1", access)


def test_harness_role_can_load_exact_suite_version() -> None:
    suite = EvaluationSuite("s", "7", (_case(),), 1.0)
    catalog = EvaluationSuiteCatalog((suite,))
    loaded = catalog.load_for_harness(
        "s",
        "7",
        SuiteAccessContext(uuid4(), frozenset({SuiteAccessRole.EVALUATION_HARNESS})),
    )
    assert loaded.suite is suite
