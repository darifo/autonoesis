"""Tests for outcome, LLM, and human grader backends."""

from typing import Any, ClassVar
from uuid import uuid4

import pytest
from autonoesis_adapters import (
    HumanGraderBackend,
    InMemoryPlatformStore,
    LlmGraderBackend,
    OutcomeGraderBackend,
)
from autonoesis_capability import parse_manifest
from autonoesis_domain import (
    CandidateVersion,
    EvaluationCase,
    EvaluationSuite,
    GraderKind,
    GraderStatus,
)
from autonoesis_evaluation import SubjectExecutionResult


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


class TestModelGatewayJudge:
    @pytest.mark.asyncio
    async def test_judge_prompt_demands_strict_verdict_and_passes_through_output(self) -> None:
        from autonoesis_adapters.graders import ModelGatewayJudge

        class RecordingAdapter:
            provider = "fake"

            def __init__(self) -> None:
                self.seen_model = ""
                self.seen_request: Any = None

            async def generate(self, model: str, request: Any) -> Any:
                self.seen_model = model
                self.seen_request = request
                from autonoesis_runtime import ModelResponse, ModelUsage

                return ModelResponse(
                    provider=self.provider,
                    model=model,
                    output_text='{"passed": true, "rationale": "ok"}',
                    usage=ModelUsage(input_tokens=1, output_tokens=1, cost_units=0),
                    route_reason="test",
                )

        adapter = RecordingAdapter()
        judge = ModelGatewayJudge(adapter, model="judge-model", rubric="rubric-1")
        raw = await judge.judge(_case(), {"decision": "approved"})
        assert raw == '{"passed": true, "rationale": "ok"}'
        assert adapter.seen_model == "judge-model"
        assert "one JSON object" in adapter.seen_request.instruction
        assert "rubric-1" in adapter.seen_request.input_text
        assert "expected_outcome" in adapter.seen_request.input_text

    @pytest.mark.asyncio
    async def test_harness_appends_llm_stage_after_deterministic(self) -> None:
        from autonoesis_adapters import HarnessCandidateEvaluator, InMemoryPlatformStore
        from autonoesis_adapters.graders import ModelGatewayJudge
        from autonoesis_domain import TrialStatus

        store = InMemoryPlatformStore()
        tenant = uuid4()
        manifest = parse_manifest(
            {
                "api_version": "autonoesis/v1alpha1",
                "pack_id": "judge-pack",
                "version": "1.0.0",
                "python_entry_point": "judge_pack.plugin:create",
                "goal_types": [
                    {
                        "goal_type": "judge-pack.run",
                        "input_schema": {"type": "object"},
                        "agent": "a",
                        "evaluation_suite": "judge-suite",
                        "default_policy": "p",
                        "default_budget": 1,
                    }
                ],
                "skills": [],
                "tools": [],
                "policies": ["p"],
                "evaluation_suites": ["judge-suite"],
            }
        )
        await store.add_capability_pack(tenant, manifest)
        await store.add_suite(
            tenant,
            EvaluationSuite(
                suite_id="judge-suite",
                version="1",
                pass_threshold=1.0,
                cases=(EvaluationCase("c1", {}, {"decision": "approved"}, ()),),
            ),
        )
        candidate = CandidateVersion(
            tenant_id=tenant,
            proposal_id=uuid4(),
            baseline_version_id=uuid4(),
            artifact_ref="pack://judge-pack/1.0.0",
            artifact_digest="d" * 64,
            suite_id="judge-suite",
            suite_version="1",
            generator_id="generator-1",
        )
        await store.add_candidate(candidate)

        class SubjectRuntime:
            async def execute_artifact(
                self,
                artifact_ref: Any,
                tenant_id: Any,
                subject_version_id: Any,
                payload: Any,
                seed: Any,
            ) -> Any:
                _ = artifact_ref, tenant_id, payload, seed
                return SubjectExecutionResult(
                    subject_version_id=subject_version_id,
                    output_payload={"decision": "approved"},
                    executor_id="test",
                    evidence_refs=("subject://judge-pack/c1",),
                    environment_ref="runtime://test/1",
                )

        class _Usage:
            pass

        class VerdictAdapter:
            provider = "fake"
            request: ClassVar[dict[str, Any]] = {}

            async def generate(self, model: str, request: Any) -> Any:
                from autonoesis_runtime import ModelResponse, ModelUsage

                return ModelResponse(
                    provider=self.provider,
                    model=model,
                    output_text='{"passed": true, "rationale": "aligned"}',
                    usage=ModelUsage(input_tokens=1, output_tokens=1, cost_units=0),
                    route_reason="test",
                )

        evaluator = HarnessCandidateEvaluator(
            store,
            SubjectRuntime(),
            llm_judge=ModelGatewayJudge(VerdictAdapter(), model="judge", rubric="r1"),
        )
        trial = await evaluator.evaluate(tenant, candidate.candidate_id)
        assert trial.status is TrialStatus.PASSED
        # Both grader kinds ran and recorded results.
        kinds = {result.kind for result in trial.case_results[0].grader_results}
        assert kinds == {GraderKind.DETERMINISTIC, GraderKind.LLM}


class TestJudgeFactory:
    def test_no_config_yields_no_judge(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from autonoesis_adapters.graders import judge_from_environment

        monkeypatch.delenv("AUTONOESIS_LLM_JUDGE_MODEL", raising=False)
        assert judge_from_environment() is None

    def test_missing_provider_credentials_fail_closed(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from autonoesis_adapters.graders import judge_from_environment

        monkeypatch.setenv("AUTONOESIS_LLM_JUDGE_MODEL", "gpt-judge")
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        for provider in ("openai", "anthropic", "unknown"):
            monkeypatch.setenv("AUTONOESIS_LLM_JUDGE_PROVIDER", provider)
            assert judge_from_environment() is None

    def test_openai_credentials_build_gateway_judge(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from autonoesis_adapters.graders import ModelGatewayJudge, judge_from_environment

        monkeypatch.setenv("AUTONOESIS_LLM_JUDGE_MODEL", "gpt-judge")
        monkeypatch.setenv("AUTONOESIS_LLM_JUDGE_PROVIDER", "openai")
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test-only")
        built = judge_from_environment()
        assert built is not None
        judge, rubric = built
        assert isinstance(judge, ModelGatewayJudge)
        assert rubric == "default-rubric@1"


class TestHumanDecisionWorkflow:
    @pytest.mark.asyncio
    async def test_recorded_decisions_grade_and_absent_stay_unknown(self) -> None:
        from autonoesis_adapters.graders import (
            AuditHumanDecisionSource,
            RecordedHumanGraderBackend,
            record_human_decision,
        )

        store = InMemoryPlatformStore()
        tenant = uuid4()
        await store.record_audit(
            record_human_decision(
                tenant, "c1", passed=True, rationale="aligned", reviewer_principal="rev-1"
            )
        )

        source = AuditHumanDecisionSource(store)
        backend = RecordedHumanGraderBackend(source, tenant)
        graded = await backend.evaluate(_case(), {})
        assert graded.status is GraderStatus.PASS
        assert "rev-1" in graded.rationale

        missing = RecordedHumanGraderBackend(AuditHumanDecisionSource(store), uuid4())
        assert (await missing.evaluate(_case(), {})).status is GraderStatus.UNKNOWN

    @pytest.mark.asyncio
    async def test_latest_decision_wins_and_malformed_records_stay_unknown(self) -> None:
        from autonoesis_adapters.graders import (
            HUMAN_DECISION_EVENT,
            AuditHumanDecisionSource,
        )
        from autonoesis_application import AuditEvent

        store = InMemoryPlatformStore()
        tenant = uuid4()
        for passed, rationale in ((True, "first yes"), (False, "superseded by re-review")):
            await store.record_audit(
                AuditEvent(
                    tenant_id=tenant,
                    actor_id=uuid4(),
                    principal_id=uuid4(),
                    event_type=HUMAN_DECISION_EVENT,
                    object_type="evaluation_case",
                    object_id="c1",
                    correlation_id=uuid4(),
                    details={"passed": passed, "rationale": rationale, "reviewer": "rev"},
                )
            )
        # A malformed record (no reviewer) for another case must not grade.
        await store.record_audit(
            AuditEvent(
                tenant_id=tenant,
                actor_id=uuid4(),
                principal_id=uuid4(),
                event_type=HUMAN_DECISION_EVENT,
                object_type="evaluation_case",
                object_id="c2",
                correlation_id=uuid4(),
                details={"passed": True, "rationale": "anon"},
            )
        )
        source = AuditHumanDecisionSource(store)
        assert await source.decision_for(tenant, "c1") == (
            False,
            "superseded by re-review",
            "rev",
        )
        assert await source.decision_for(tenant, "c2") is None
