"""Temporal component test for durable candidate evaluation and promotion."""

import asyncio
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
from autonoesis_worker.activities import (
    build_activity_dependencies,
    evaluate_candidate,
    promote_candidate,
)
from autonoesis_worker.contracts import (
    CandidateLifecycleInput,
    EvaluateCandidateInput,
    PromoteCandidateInput,
)
from autonoesis_worker.workflows import CandidateLifecycleWorkflow
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine
from temporalio import activity
from temporalio.client import Client
from temporalio.worker import Worker

pytestmark = pytest.mark.skipif(
    not (
        os.getenv("AUTONOESIS_TEST_TEMPORAL_TARGET") and os.getenv("AUTONOESIS_TEST_DATABASE_URL")
    ),
    reason="requires explicitly configured Temporal and PostgreSQL component endpoints",
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
                {"tenant_id": str(tenant_id), "name": f"wf-{tenant_id}"},
            )
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_candidate_workflow_evaluates_and_promotes_durably() -> None:
    tenant_id = uuid4()
    await provision_tenant(tenant_id)
    store = PostgreSQLPlatformStore.from_url(os.environ["AUTONOESIS_TEST_DATABASE_URL"])
    evolution = CandidateLifecycleService(store)
    runtime = InProcessSubjectRuntime()

    async def subject(input_payload: dict[str, Any], random_seed: int) -> dict[str, Any]:
        return {"decision": "verified"}

    runtime.register("artifact://recovery/v2", subject)
    policy = RepeatedTrialPolicy(pass_threshold=0.4, min_valid_trials=3)
    dependencies = build_activity_dependencies(
        store,
        evolution,
        candidate_evaluator=HarnessCandidateEvaluator(store, runtime),
        evaluation_policy=policy,
    )

    @activity.defn(name="evaluate_candidate")
    async def temporal_evaluate(input: EvaluateCandidateInput) -> bool:
        return await evaluate_candidate(input, dependencies)

    @activity.defn(name="promote_candidate")
    async def temporal_promote(input: PromoteCandidateInput) -> str:
        return await promote_candidate(input, dependencies)

    generator = IdentityContext(tenant_id, uuid4(), uuid4(), frozenset({"candidate_generator"}))
    proposal = await evolution.propose_improvement(
        generator,
        ProposeImprovement(
            target="agent_instruction",
            target_version_id=uuid4(),
            evidence_refs=("evidence://observation/1",),
            diagnosis="d",
            proposed_change="c",
            validation_suite_id="recovery-suite",
            rollback_plan="r",
        ),
    )
    candidate = await evolution.register_candidate(
        generator,
        RegisterCandidate(
            proposal_id=proposal.proposal_id,
            baseline_version_id=uuid4(),
            artifact_ref="artifact://recovery/v2",
            artifact_digest="f" * 64,
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
            cases=(EvaluationCase("c1", {"q": 1}, {"decision": "verified"}, ()),),
        ),
    )

    client = await Client.connect(os.environ["AUTONOESIS_TEST_TEMPORAL_TARGET"])
    task_queue = f"candidate-lifecycle-{uuid4()}"
    handle = None
    worker = Worker(
        client,
        task_queue=task_queue,
        workflows=[CandidateLifecycleWorkflow],
        activities=[temporal_evaluate, temporal_promote],
    )
    try:
        async with worker:
            handle = await client.start_workflow(
                CandidateLifecycleWorkflow.run,
                CandidateLifecycleInput(str(tenant_id), str(candidate.candidate_id)),
                id=f"candidate-lifecycle-{uuid4()}",
                task_queue=task_queue,
            )
            for _ in range(240):
                if await handle.query("current_phase") == "awaiting_approval":
                    break
                await asyncio.sleep(0.5)
            assert await handle.query("current_phase") == "awaiting_approval"

            approver = IdentityContext(tenant_id, uuid4(), uuid4(), frozenset({"approver"}))
            await evolution.decide(approver, candidate.candidate_id, True, "component approval")
            await handle.signal(CandidateLifecycleWorkflow.approval_decided, "approval-1")
            result = await asyncio.wait_for(handle.result(), timeout=60)
            assert result == "shadow"
    finally:
        await store.close()

    verification_store = PostgreSQLPlatformStore.from_url(
        os.environ["AUTONOESIS_TEST_DATABASE_URL"]
    )
    try:
        persisted = await verification_store.get_candidate(tenant_id, candidate.candidate_id)
        assert persisted.status.value == "approved"
        trials = await verification_store.list_trials_for_candidate(
            tenant_id, candidate.candidate_id
        )
        assert len(trials) >= policy.min_valid_trials
        assert all(trial.status is TrialStatus.PASSED for trial in trials)
        records = await verification_store.list_evaluation_records(
            tenant_id, candidate.candidate_id
        )
        assert records[-1].decision == "met"
    finally:
        await verification_store.close()
