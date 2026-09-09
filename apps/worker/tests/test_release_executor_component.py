"""Temporal component test for the independent Release Executor workflow."""

import asyncio
import os
from uuid import UUID, uuid4

import pytest
from autonoesis_adapters import PostgreSQLPlatformStore
from autonoesis_application import (
    CandidateLifecycleService,
    IdentityContext,
    ProposeImprovement,
    RegisterCandidate,
)
from autonoesis_domain import DeploymentStatus, EvaluationCase, EvaluationSuite, TrafficAllocation
from autonoesis_evaluation import RepeatedTrialPolicy
from autonoesis_worker.activities import build_activity_dependencies, execute_release_command
from autonoesis_worker.contracts import ReleaseCommandInput
from autonoesis_worker.workflows import ReleaseExecutionWorkflow
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
                {"tenant_id": str(tenant_id), "name": f"release-{tenant_id}"},
            )
    finally:
        await engine.dispose()


async def _approved_candidate(
    store: PostgreSQLPlatformStore, evolution: CandidateLifecycleService, tenant_id: UUID
) -> UUID:
    generator = IdentityContext(tenant_id, uuid4(), uuid4(), frozenset({"candidate_generator"}))
    proposal = await evolution.propose_improvement(
        generator,
        ProposeImprovement(
            target="agent_instruction",
            target_version_id=uuid4(),
            evidence_refs=("evidence://observation/1",),
            diagnosis="d",
            proposed_change="c",
            validation_suite_id="release-suite",
            rollback_plan="r",
        ),
    )
    candidate = await evolution.register_candidate(
        generator,
        RegisterCandidate(
            proposal_id=proposal.proposal_id,
            baseline_version_id=uuid4(),
            artifact_ref="artifact://agent/v2",
            artifact_digest="e" * 64,
            suite_id="release-suite",
            suite_version="1",
        ),
    )
    from autonoesis_domain import Trial, TrialCaseResult, TrialStatus

    await evolution.submit_for_evaluation(tenant_id, candidate.candidate_id)
    executed = TrialCaseResult(
        case_id="c1",
        input_payload={},
        output_payload={"decision": "verified"},
        subject_executed=True,
        executor_id="subject-runtime",
        evidence_refs=("evidence://execution/1",),
        environment_ref="environment://fixture/1",
    )
    for _ in range(16):
        await store.add_trial(
            Trial(
                tenant_id=tenant_id,
                suite_id="release-suite",
                suite_version="1",
                subject_version_id=candidate.candidate_id,
                harness_version="2",
                status=TrialStatus.PASSED,
                case_results=(executed,),
                candidate_id=candidate.candidate_id,
            )
        )
    grader = IdentityContext(tenant_id, uuid4(), uuid4(), frozenset({"grader"}))
    await evolution.complete_evaluation(
        grader, candidate.candidate_id, RepeatedTrialPolicy(pass_threshold=0.8)
    )
    await evolution.decide(
        IdentityContext(tenant_id, uuid4(), uuid4(), frozenset({"approver"})),
        candidate.candidate_id,
        True,
        "component approval",
    )
    await store.add_suite(
        tenant_id,
        EvaluationSuite(
            suite_id="release-suite",
            version="1",
            pass_threshold=1.0,
            cases=(EvaluationCase("c1", {}, {"decision": "verified"}, ()),),
        ),
    )
    return candidate.candidate_id


@pytest.mark.asyncio
async def test_release_executor_workflow_binds_canary_rule_durably() -> None:
    tenant_id = uuid4()
    await provision_tenant(tenant_id)
    store = PostgreSQLPlatformStore.from_url(os.environ["AUTONOESIS_TEST_DATABASE_URL"])
    evolution = CandidateLifecycleService(store)
    dependencies = build_activity_dependencies(store, evolution)

    @activity.defn(name="execute_release_command")
    async def temporal_release(input: ReleaseCommandInput) -> str:
        return await execute_release_command(input, dependencies)

    candidate_id = await _approved_candidate(store, evolution, tenant_id)
    executor = IdentityContext(tenant_id, uuid4(), uuid4(), frozenset({"release_executor"}))
    deployment = await evolution.begin_shadow(executor, candidate_id)

    client = await Client.connect(os.environ["AUTONOESIS_TEST_TEMPORAL_TARGET"])
    task_queue = f"release-executor-{uuid4()}"
    worker = Worker(
        client,
        task_queue=task_queue,
        workflows=[ReleaseExecutionWorkflow],
        activities=[temporal_release],
    )
    try:
        async with worker:
            handle = await client.start_workflow(
                ReleaseExecutionWorkflow.run,
                ReleaseCommandInput(
                    str(tenant_id),
                    "enter_canary",
                    deployment_id=str(deployment.deployment_id),
                    candidate_percent=20,
                    salt="component-salt",
                ),
                id=f"release-execution-{uuid4()}",
                task_queue=task_queue,
            )
            result = await asyncio.wait_for(handle.result(), timeout=60)
            assert result == f"canary:{deployment.deployment_id}"
    finally:
        await store.close()

    verification_store = PostgreSQLPlatformStore.from_url(
        os.environ["AUTONOESIS_TEST_DATABASE_URL"]
    )
    try:
        persisted = await verification_store.get_deployment(tenant_id, deployment.deployment_id)
        assert persisted.status is DeploymentStatus.CANARY
        assert persisted.traffic_allocation == TrafficAllocation("component-salt", 20)
        # The persisted rule replays deterministically for audit after reload.
        request_id = uuid4()
        route, allocation = await CandidateLifecycleService(
            verification_store
        ).resolve_request_route(executor, deployment.deployment_id, request_id)
        assert allocation == TrafficAllocation("component-salt", 20)
        assert route is persisted.assign_request(request_id)
    finally:
        await verification_store.close()
