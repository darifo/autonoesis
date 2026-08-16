"""PostgreSQL component test: real subject execution to confident promotion."""

import os
from typing import Any
from uuid import UUID, uuid4

import pytest
from autonoesis_adapters import (
    HarnessCandidateEvaluator,
    InProcessSubjectRuntime,
    PostgreSQLPlatformStore,
)
from autonoesis_application import (
    CandidateLifecycleService,
    IdentityContext,
    ProposeImprovement,
    RegisterCandidate,
)
from autonoesis_domain import EvaluationCase, EvaluationSuite, TrialStatus
from autonoesis_evaluation import RepeatedTrialPolicy
from autonoesis_worker.activities import build_activity_dependencies, evaluate_candidate
from autonoesis_worker.contracts import EvaluateCandidateInput
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

pytestmark = pytest.mark.skipif(
    not os.getenv("AUTONOESIS_TEST_DATABASE_URL"),
    reason="requires an explicitly configured PostgreSQL component endpoint",
)


async def provision_tenant(tenant_id: UUID) -> None:
    engine = create_async_engine(os.environ["AUTONOESIS_TEST_ADMIN_DATABASE_URL"])
    try:
        async with engine.begin() as connection:
            await connection.execute(
                text(
                    """INSERT INTO tenants (id, name, created_at)
                    VALUES (:tenant_id, :name, CURRENT_TIMESTAMP)
                    ON CONFLICT (id) DO NOTHING"""
                ),
                {"tenant_id": str(tenant_id), "name": f"eval-{tenant_id}"},
            )
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_real_subject_reaches_confident_promotion_through_persisted_evidence() -> None:
    tenant_id = uuid4()
    await provision_tenant(tenant_id)
    store = PostgreSQLPlatformStore.from_url(os.environ["AUTONOESIS_TEST_DATABASE_URL"])
    evolution = CandidateLifecycleService(store)
    try:
        generator = IdentityContext(tenant_id, uuid4(), uuid4(), frozenset({"candidate_generator"}))
        proposal = await evolution.propose_improvement(
            generator,
            ProposeImprovement(
                target="agent_instruction",
                target_version_id=uuid4(),
                evidence_refs=("evidence://observation/1",),
                diagnosis="recovery condition missing",
                proposed_change="add recovery condition",
                validation_suite_id="recovery-suite",
                rollback_plan="restore baseline",
            ),
        )
        candidate = await evolution.register_candidate(
            generator,
            RegisterCandidate(
                proposal_id=proposal.proposal_id,
                baseline_version_id=uuid4(),
                artifact_ref="pack://recovery-agent/v2",
                artifact_digest="e" * 64,
                suite_id="recovery-suite",
                suite_version="1",
            ),
        )
        await store.add_suite(
            tenant_id,
            EvaluationSuite(
                suite_id="recovery-suite",
                version="1",
                pass_threshold=1.0,
                cases=(
                    EvaluationCase(
                        case_id="normal-recovery",
                        input_payload={"equipment_id": "E-1"},
                        expected_outcome={"decision": "verified"},
                        tags=("normal",),
                        weight=1.0,
                        gating=True,
                    ),
                ),
            ),
        )

        runtime = InProcessSubjectRuntime()

        async def recovery_subject(
            input_payload: dict[str, Any], random_seed: int
        ) -> dict[str, Any]:
            # Real executed subject logic: deterministic decision derived from input.
            return {"decision": "verified" if input_payload.get("equipment_id") else "clarify"}

        runtime.register("pack://recovery-agent/v2", recovery_subject)
        evaluator = HarnessCandidateEvaluator(store, runtime)
        policy = RepeatedTrialPolicy(pass_threshold=0.8, min_valid_trials=10)

        advanced = await evaluate_candidate(
            EvaluateCandidateInput(str(tenant_id), str(candidate.candidate_id)),
            build_activity_dependencies(
                store,
                evolution,
                candidate_evaluator=evaluator,
                evaluation_policy=policy,
            ),
        )
        assert advanced is True

        persisted = await store.get_candidate(tenant_id, candidate.candidate_id)
        assert persisted.status.value == "awaiting_approval"
        trials = await store.list_trials_for_candidate(tenant_id, candidate.candidate_id)
        assert len(trials) >= policy.min_valid_trials
        assert all(trial.candidate_id == candidate.candidate_id for trial in trials)
        assert all(trial.subject_version_id == candidate.candidate_id for trial in trials)
        assert all(trial.status is TrialStatus.PASSED for trial in trials)
        assert all(trial.random_seed is not None for trial in trials)
        records = await store.list_evaluation_records(tenant_id, candidate.candidate_id)
        assert records[-1].decision == "met"
        assert records[-1].assessment["lower_bound"] >= 0.8

        # Tenant isolation: another tenant cannot resolve the same suite.
        other_tenant = uuid4()
        await provision_tenant(other_tenant)
        with pytest.raises(Exception, match="not found"):
            await store.get_suite(other_tenant, "recovery-suite", "1")
    finally:
        await store.close()
