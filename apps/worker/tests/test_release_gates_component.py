"""PostgreSQL component test for promotion gates, guardrails, and rollback."""

import asyncio
import os
from typing import Any
from uuid import UUID, uuid4

import pytest
from autonoesis_adapters import PostgreSQLPlatformStore
from autonoesis_application import (
    CandidateLifecycleService,
    ExecuteShadowPair,
    IdentityContext,
    PromotionPolicy,
    ProposeImprovement,
    RecordObservation,
    RegisterCandidate,
)
from autonoesis_domain import (
    DeploymentStatus,
    EvaluationCase,
    EvaluationSuite,
    GuardrailOperator,
    ShadowMeasurements,
)
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
                {"tenant_id": str(tenant_id), "name": f"rel-{tenant_id}"},
            )
    finally:
        await engine.dispose()


async def _approved_candidate(store: Any, tenant_id: UUID, index: int) -> UUID:
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
            validation_suite_id=f"suite-{index}",
            rollback_plan="r",
        ),
    )
    candidate = await evolution.register_candidate(
        generator,
        RegisterCandidate(
            proposal_id=proposal.proposal_id,
            baseline_version_id=uuid4(),
            artifact_ref=f"artifact://agent/v{index}",
            artifact_digest="a" * 64,
            suite_id=f"suite-{index}",
            suite_version="1",
        ),
    )
    from autonoesis_domain import Trial, TrialCaseResult, TrialStatus
    from autonoesis_evaluation import RepeatedTrialPolicy

    await store.add_suite(
        tenant_id,
        EvaluationSuite(
            suite_id=f"suite-{index}",
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
                suite_id=f"suite-{index}",
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
    await evolution.decide(approver, candidate.candidate_id, True, "component approval")
    return candidate.candidate_id


class ComponentShadowRuntime:
    async def execute_shadow_subject(self, **command: Any) -> ShadowMeasurements:
        if command["external_effects_enabled"]:
            return ShadowMeasurements(0.8, 120, 30.0, human_corrections=1)
        return ShadowMeasurements(0.9, 100, 25.0)


@pytest.mark.asyncio
async def test_promotion_gate_and_guardrail_isolation() -> None:
    tenant_id = uuid4()
    await provision_tenant(tenant_id)
    store = PostgreSQLPlatformStore.from_url(os.environ["AUTONOESIS_TEST_DATABASE_URL"])
    evolution = CandidateLifecycleService(store)
    executor = IdentityContext(tenant_id, uuid4(), uuid4(), frozenset({"release_executor"}))
    try:
        candidate_id = await _approved_candidate(store, tenant_id, 1)
        deployment = await evolution.begin_shadow(executor, candidate_id)
        comparison = await evolution.execute_shadow_pair(
            executor,
            ExecuteShadowPair(
                deployment.deployment_id,
                "request://component/shadow-1",
                {"prompt": "component"},
            ),
            ComponentShadowRuntime(),
        )
        persisted = await store.list_shadow_comparisons(tenant_id, deployment.deployment_id)
        assert persisted == (comparison,)
        outcome_delta = await store.get_observation(
            tenant_id,
            deployment.deployment_id,
            DeploymentStatus.SHADOW,
            "outcome_score_delta",
        )
        assert outcome_delta is not None and outcome_delta.last_value == pytest.approx(0.1)
        canary = await evolution.promote_to_canary(executor, deployment.deployment_id)

        # Insufficient sample refuses promotion (metric missing blocks, never silent).
        with pytest.raises(ValueError, match="missing evidence"):
            await evolution.release_stable(
                executor,
                canary.deployment_id,
                uuid4(),
                PromotionPolicy(min_samples=2, required_metrics=("outcome_rate",)),
            )

        # Record observations for two deployments and verify four-way isolation.
        candidate_two = await _approved_candidate(store, tenant_id, 2)
        deployment_two = await evolution.begin_shadow(executor, candidate_two)
        canary_two = await evolution.promote_to_canary(executor, deployment_two.deployment_id)

        for _ in range(3):
            await evolution.record_observation(
                executor,
                RecordObservation(
                    canary.deployment_id, DeploymentStatus.CANARY, "outcome_rate", 0.99
                ),
            )
        await evolution.record_observation(
            executor,
            RecordObservation(
                canary_two.deployment_id, DeploymentStatus.CANARY, "outcome_rate", 0.50
            ),
        )

        first_obs = await store.get_observation(
            tenant_id, canary.deployment_id, DeploymentStatus.CANARY, "outcome_rate"
        )
        second_obs = await store.get_observation(
            tenant_id, canary_two.deployment_id, DeploymentStatus.CANARY, "outcome_rate"
        )
        assert first_obs is not None and first_obs.sample_count == 3
        assert second_obs is not None and second_obs.sample_count == 1

        # Guardrail breach rolls back only the target deployment.
        for _ in range(2):
            await evolution.record_observation(
                executor,
                RecordObservation(
                    canary_two.deployment_id,
                    DeploymentStatus.CANARY,
                    "error_rate",
                    0.5,
                    GuardrailOperator.GTE,
                    0.1,
                ),
            )
        rolled_back = await evolution.rollback_if_breached(
            executor, canary_two.deployment_id, DeploymentStatus.CANARY, "error_rate", 2
        )
        assert rolled_back is not None and rolled_back.status.value == "rolled_back"
        first = await store.get_deployment(tenant_id, canary.deployment_id)
        assert first.status is DeploymentStatus.CANARY

        # Now satisfy the gate and promote.
        release = await evolution.release_stable(
            executor,
            canary.deployment_id,
            uuid4(),
            PromotionPolicy(min_samples=2, required_metrics=("outcome_rate",)),
        )
        assert release.stable_version_id is not None
        stable = await store.get_deployment(tenant_id, canary.deployment_id)
        assert stable.status is DeploymentStatus.STABLE
    finally:
        await store.close()


@pytest.mark.asyncio
async def test_concurrent_promotion_only_one_wins_stable_slot() -> None:
    tenant_id = uuid4()
    await provision_tenant(tenant_id)
    store = PostgreSQLPlatformStore.from_url(os.environ["AUTONOESIS_TEST_DATABASE_URL"])
    evolution = CandidateLifecycleService(store)
    executor = IdentityContext(tenant_id, uuid4(), uuid4(), frozenset({"release_executor"}))
    try:
        candidate_id = await _approved_candidate(store, tenant_id, 3)
        deployment = await evolution.begin_shadow(executor, candidate_id)
        canary = await evolution.promote_to_canary(executor, deployment.deployment_id)
        await evolution.record_observation(
            executor,
            RecordObservation(canary.deployment_id, DeploymentStatus.CANARY, "outcome_rate", 1.0),
        )

        second_store = PostgreSQLPlatformStore.from_url(os.environ["AUTONOESIS_TEST_DATABASE_URL"])
        second_evolution = CandidateLifecycleService(second_store)
        try:
            results = await asyncio.gather(
                evolution.release_stable(
                    executor,
                    canary.deployment_id,
                    uuid4(),
                    PromotionPolicy(min_samples=1, required_metrics=("outcome_rate",)),
                ),
                second_evolution.release_stable(
                    executor,
                    canary.deployment_id,
                    uuid4(),
                    PromotionPolicy(min_samples=1, required_metrics=("outcome_rate",)),
                ),
                return_exceptions=True,
            )
            wins = [r for r in results if not isinstance(r, BaseException)]
            assert len(wins) == 1
        finally:
            await second_store.close()
    finally:
        await store.close()
