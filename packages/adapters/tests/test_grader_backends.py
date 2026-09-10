"""Tests for outcome, LLM, and human grader backends."""

from typing import Any

import pytest
from autonoesis_adapters import (
    HumanGraderBackend,
    LlmGraderBackend,
    OutcomeGraderBackend,
)
from autonoesis_domain import EvaluationCase, GraderStatus


def _case() -> EvaluationCase:
    return EvaluationCase("c1", {}, {"decision": "approved"}, ())


class _Readback:
    def __init__(self, verified: bool) -> None:
        self._verified = verified

    async def verify(self, case: EvaluationCase, actual: dict[str, Any]) -> bool:
        _ = case, actual
        return self._verified


class _Judge:
    def __init__(self, raw: str) -> None:
        self._raw = raw

    async def judge(self, case: EvaluationCase, actual: dict[str, Any]) -> str:
        _ = case, actual
        return self._raw


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "verified,expected", [(True, GraderStatus.PASS), (False, GraderStatus.FAIL)]
)
async def test_outcome_backend_grades_from_authoritative_readback(
    verified: bool, expected: GraderStatus
) -> None:
    assessment = await OutcomeGraderBackend(_Readback(verified)).evaluate(_case(), {})
    assert assessment.status is expected
    assert assessment.score == (1.0 if verified else 0.0)


@pytest.mark.asyncio
async def test_llm_backend_accepts_strict_verdicts_only() -> None:
    good = await LlmGraderBackend(
        _Judge('{"passed": true, "rationale": "matches rubric"}'), "r1"
    ).evaluate(_case(), {})
    assert good.status is GraderStatus.PASS
    assert "rubric r1" in good.rationale

    for raw in ('{"passed": "yes"}', "not json", '{"passed": true, "rationale": ""}', "{}"):
        assessment = await LlmGraderBackend(_Judge(raw), "r1").evaluate(_case(), {})
        assert assessment.status is GraderStatus.UNKNOWN
        assert assessment.score is None


@pytest.mark.asyncio
async def test_human_backend_requires_recorded_decisions_with_rationales() -> None:
    backend = HumanGraderBackend({"c1": (True, "aligned with policy")}, "reviewer-7")
    assessment = await backend.evaluate(_case(), {})
    assert assessment.status is GraderStatus.PASS
    assert "reviewer-7" in assessment.rationale

    missing = HumanGraderBackend({}, "reviewer-7")
    assert (await missing.evaluate(_case(), {})).status is GraderStatus.UNKNOWN

    silent = HumanGraderBackend({"c1": (True, "   ")}, "reviewer-7")
    assert (await silent.evaluate(_case(), {})).status is GraderStatus.UNKNOWN
