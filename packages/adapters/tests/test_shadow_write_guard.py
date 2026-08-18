"""Tests for shadow-deployment write suppression."""

from typing import Any
from uuid import UUID, uuid4

import pytest
from autonoesis_adapters import InMemoryPlatformStore, SqlShadowWriteGuard
from autonoesis_application import CandidateLifecycleService, IdentityContext
from autonoesis_domain import (
    JsonObject,
    RiskLevel,
    Run,
    RunStatus,
)

_WRITE_ACTION_KWARGS = {
    "tool_name": "records",
    "tool_version": "1",
    "operation": "create",
    "resource_scope": "tenant/records",
    "parameters": JsonObject.from_value({"equipment_id": "E-1"}),
    "risk_level": RiskLevel.L2_REVERSIBLE_WRITE,
    "idempotency_key": "write-1",
    "expected_effect": "create a record",
}


async def _approved_candidate(store: Any, tenant_id: UUID) -> UUID:
    from autonoesis_application import (
        ProposeImprovement,
        RegisterCandidate,
    )
    from autonoesis_domain import (
        EvaluationCase,
        EvaluationSuite,
        Trial,
        TrialCaseResult,
        TrialStatus,
    )
    from autonoesis_evaluation import RepeatedTrialPolicy

    evolution = CandidateLifecycleService(store)
    generator = IdentityContext(tenant_id, uuid4(), uuid4(), frozenset({"candidate_generator"}))
    proposal = await evolution.propose_improvement(
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
    candidate = await evolution.register_candidate(
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
    await store.add_suite(
        tenant_id,
        EvaluationSuite(
            suite_id="suite-1",
            version="1",
            pass_threshold=1.0,
            cases=(EvaluationCase("c1", {}, {"answer": 42}, ()),),
        ),
    )
    await evolution.submit_for_evaluation(tenant_id, candidate.candidate_id)
    for _ in range(16):
        await store.add_trial(
            Trial(
                tenant_id=tenant_id,
                suite_id="suite-1",
                suite_version="1",
                subject_version_id=candidate.candidate_id,
                harness_version="2",
                status=TrialStatus.PASSED,
                case_results=(
                    TrialCaseResult(
                        case_id="c1",
                        input_payload={},
                        output_payload={"answer": 42},
                        subject_executed=True,
                        executor_id="subject-runtime",
                        evidence_refs=("evidence://execution/1",),
                        environment_ref="environment://fixture/1",
                    ),
                ),
                candidate_id=candidate.candidate_id,
            )
        )
    grader = IdentityContext(tenant_id, uuid4(), uuid4(), frozenset({"grader"}))
    await evolution.complete_evaluation(
        grader, candidate.candidate_id, RepeatedTrialPolicy(pass_threshold=0.8)
    )
    approver = IdentityContext(tenant_id, uuid4(), uuid4(), frozenset({"approver"}))
    await evolution.decide(approver, candidate.candidate_id, True, "approve")
    return candidate.candidate_id


def _run(tenant_id: UUID, deployment_id: UUID | None) -> Run:
    return Run(
        tenant_id=tenant_id,
        goal_id=uuid4(),
        agent_version_id=uuid4(),
        status=RunStatus.RUNNING,
        deployment_id=deployment_id,
    )


@pytest.mark.asyncio
async def test_shadow_write_is_refused() -> None:
    store = InMemoryPlatformStore()
    tenant_id = uuid4()
    evolution = CandidateLifecycleService(store)
    candidate_id = await _approved_candidate(store, tenant_id)
    executor = IdentityContext(tenant_id, uuid4(), uuid4(), frozenset({"release_executor"}))
    deployment = await evolution.begin_shadow(executor, candidate_id)
    run = _run(tenant_id, deployment.deployment_id)
    store.runs[run.run_id] = run

    guard = SqlShadowWriteGuard(store)
    with pytest.raises(PermissionError, match="shadow deployment"):
        await guard.assert_writable(tenant_id, run.run_id)


@pytest.mark.asyncio
async def test_read_action_and_non_shadow_deployments_pass() -> None:
    store = InMemoryPlatformStore()
    tenant_id = uuid4()
    evolution = CandidateLifecycleService(store)
    candidate_id = await _approved_candidate(store, tenant_id)
    executor = IdentityContext(tenant_id, uuid4(), uuid4(), frozenset({"release_executor"}))
    deployment = await evolution.begin_shadow(executor, candidate_id)
    canary = await evolution.promote_to_canary(executor, deployment.deployment_id)

    guard = SqlShadowWriteGuard(store)
    # Run not bound to any deployment passes.
    unbound = _run(tenant_id, None)
    store.runs[unbound.run_id] = unbound
    await guard.assert_writable(tenant_id, unbound.run_id)
    # Run bound to a canary deployment passes (real traffic may write).
    canary_run = _run(tenant_id, canary.deployment_id)
    store.runs[canary_run.run_id] = canary_run
    await guard.assert_writable(tenant_id, canary_run.run_id)


@pytest.mark.asyncio
async def test_run_persists_deployment_link_round_trip() -> None:
    from autonoesis_adapters.persistence_codec import run_from_row, run_payload

    tenant_id = uuid4()
    deployment_id = uuid4()
    run = _run(tenant_id, deployment_id)
    payload = run_payload(run)
    assert payload["deployment_id"] == str(deployment_id)
    row = {
        "id": str(run.run_id),
        "tenant_id": str(tenant_id),
        "goal_id": str(run.goal_id),
        "agent_version_id": str(run.agent_version_id),
        "status": run.status.value,
        "optimistic_version": run.optimistic_version,
        "created_at": run.created_at,
        "definition": payload,
    }
    restored = run_from_row(row)
    assert restored.deployment_id == deployment_id
