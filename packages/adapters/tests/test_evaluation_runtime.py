"""Tests for pack-declared and registered Subject Runtimes."""

from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest
from autonoesis_adapters import (
    HarnessCandidateEvaluator,
    InMemoryPlatformStore,
    InProcessSubjectRuntime,
    PackSubjectRuntime,
)
from autonoesis_capability import parse_manifest

SUBJECT_MODULE = """
def subject(input_payload, random_seed):
    return {"decision": "verified" if input_payload.get("ok") else "clarify"}


async def asleep(input_payload, random_seed):
    return {"decision": "async"}
"""


def _manifest(pack_id: str, evaluation_subject: str | None) -> Any:
    raw: dict[str, Any] = {
        "api_version": "autonoesis/v1alpha1",
        "pack_id": pack_id,
        "version": "1.0.0",
        "python_entry_point": f"{pack_id.replace('-', '_')}.plugin:create",
        "goal_types": [
            {
                "goal_type": f"{pack_id}.run",
                "input_schema": {"type": "object"},
                "agent": "agent",
                "evaluation_suite": "suite",
                "default_policy": "policy",
                "default_budget": 10,
            }
        ],
        "skills": [],
        "tools": [],
        "policies": [],
        "evaluation_suites": ["suite"],
    }
    if evaluation_subject is not None:
        raw["evaluation_subject"] = evaluation_subject
    return parse_manifest(raw)


@pytest.fixture
def subject_module(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    module_root = tmp_path / "fakesubject"
    module_root.mkdir()
    (module_root / "__init__.py").write_text("", encoding="utf-8")
    (module_root / "plugin.py").write_text(SUBJECT_MODULE, encoding="utf-8")
    monkeypatch.syspath_prepend(str(tmp_path))


@pytest.mark.asyncio
async def test_pack_runtime_executes_declared_subject(subject_module: None) -> None:
    store = InMemoryPlatformStore()
    tenant_id = uuid4()
    await store.add_capability_pack(
        tenant_id, _manifest("fakesubject", "fakesubject.plugin:subject")
    )
    runtime = PackSubjectRuntime(store)
    result = await runtime.execute_artifact(
        "pack://fakesubject/1.0.0", tenant_id, uuid4(), {"ok": True}, 7
    )
    assert result.output_payload == {"decision": "verified"}
    assert result.executor_id == "pack-subject-runtime@1"


@pytest.mark.asyncio
async def test_pack_runtime_supports_async_subjects(subject_module: None) -> None:
    store = InMemoryPlatformStore()
    tenant_id = uuid4()
    await store.add_capability_pack(
        tenant_id, _manifest("fakesubject", "fakesubject.plugin:asleep")
    )
    runtime = PackSubjectRuntime(store)
    result = await runtime.execute_artifact("pack://fakesubject/1.0.0", tenant_id, uuid4(), {}, 1)
    assert result.output_payload == {"decision": "async"}


@pytest.mark.asyncio
async def test_pack_runtime_fails_closed_without_registered_pack() -> None:
    runtime = PackSubjectRuntime(InMemoryPlatformStore())
    with pytest.raises(RuntimeError, match="not registered"):
        await runtime.execute_artifact("pack://fakesubject/1.0.0", uuid4(), uuid4(), {}, 1)


@pytest.mark.asyncio
async def test_pack_runtime_fails_closed_without_declared_subject() -> None:
    store = InMemoryPlatformStore()
    tenant_id = uuid4()
    await store.add_capability_pack(tenant_id, _manifest("fakesubject", None))
    runtime = PackSubjectRuntime(store)
    with pytest.raises(RuntimeError, match="declares no evaluation subject"):
        await runtime.execute_artifact("pack://fakesubject/1.0.0", tenant_id, uuid4(), {}, 1)


@pytest.mark.asyncio
async def test_pack_runtime_rejects_malformed_artifact_references() -> None:
    runtime = PackSubjectRuntime(InMemoryPlatformStore())
    with pytest.raises(RuntimeError, match="malformed"):
        await runtime.execute_artifact("artifact://agent/v2", uuid4(), uuid4(), {}, 1)


@pytest.mark.asyncio
async def test_registered_runtime_rejects_unknown_artifacts() -> None:
    runtime = InProcessSubjectRuntime()
    with pytest.raises(RuntimeError, match="no subject runtime registered"):
        await runtime.execute_artifact("artifact://agent/v2", uuid4(), uuid4(), {}, 1)


@pytest.mark.asyncio
async def test_harness_evaluator_runs_registered_subject_to_a_trial() -> None:
    from autonoesis_application import (
        CandidateLifecycleService,
        IdentityContext,
        ProposeImprovement,
        RegisterCandidate,
    )
    from autonoesis_domain import TrialStatus

    store = InMemoryPlatformStore()
    tenant_id = uuid4()
    service = CandidateLifecycleService(store)
    generator = IdentityContext(tenant_id, uuid4(), uuid4(), frozenset({"candidate_generator"}))
    proposal = await service.propose_improvement(
        generator,
        ProposeImprovement(
            target="agent_instruction",
            target_version_id=uuid4(),
            evidence_refs=("evidence://observation/1",),
            diagnosis="d",
            proposed_change="c",
            validation_suite_id="suite-1",
            rollback_plan="r",
        ),
    )
    candidate = await service.register_candidate(
        generator,
        RegisterCandidate(
            proposal_id=proposal.proposal_id,
            baseline_version_id=uuid4(),
            artifact_ref="artifact://agent/v2",
            artifact_digest="a" * 64,
            suite_id="suite-1",
            suite_version="1",
        ),
    )
    from autonoesis_domain import EvaluationCase, EvaluationSuite

    await store.add_suite(
        tenant_id,
        EvaluationSuite(
            suite_id="suite-1",
            version="1",
            pass_threshold=1.0,
            cases=(EvaluationCase("c1", {"ok": True}, {"decision": "verified"}, ()),),
        ),
    )
    runtime = InProcessSubjectRuntime()

    async def subject(input_payload: dict[str, Any], random_seed: int) -> dict[str, Any]:
        return {"decision": "verified"}

    runtime.register("artifact://agent/v2", subject)
    evaluator = HarnessCandidateEvaluator(store, runtime)
    trial = await evaluator.evaluate(tenant_id, candidate.candidate_id)
    assert trial.status is TrialStatus.PASSED
    assert trial.subject_version_id == candidate.candidate_id
    assert trial.suite_id == "suite-1"
