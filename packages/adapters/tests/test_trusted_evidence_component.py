"""PostgreSQL + MinIO component proof for Evidence, Outcome, Audit, and tombstones."""

import asyncio
import os
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import boto3
import pytest
from autonoesis_adapters import Boto3ObjectStore, MinioEvidenceStore, PostgreSQLPlatformStore
from autonoesis_application import (
    AuditEvent,
    AuthoritativeObservation,
    CaptureAuthoritativeEvidence,
    CommandContext,
    EvidenceArtifactDescriptor,
    GoalExecutionApplication,
    IdentityContext,
    RequestEvidenceDeletion,
    VerifyOutcome,
    verify_audit_chain,
)
from autonoesis_domain import (
    Action,
    ActionStatus,
    BudgetAmount,
    DataClassification,
    GoalContract,
    JsonObject,
    OutcomeStatus,
    Plan,
    RiskLevel,
    RiskTier,
    Run,
    SubjectRef,
    SuccessCriterion,
    Task,
)
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

pytestmark = pytest.mark.skipif(
    not all(
        os.getenv(name)
        for name in (
            "AUTONOESIS_TEST_DATABASE_URL",
            "AUTONOESIS_TEST_ADMIN_DATABASE_URL",
            "AUTONOESIS_TEST_MINIO_URL",
        )
    ),
    reason="requires explicitly configured PostgreSQL and MinIO components",
)


class StableReadback:
    async def observe(
        self,
        source: str,
        tenant_id: UUID,
        subject_refs: tuple[SubjectRef, ...],
        criterion: SuccessCriterion,
    ) -> AuthoritativeObservation:
        _ = (tenant_id, subject_refs, criterion)
        now = datetime.now(UTC)
        content = b'{"status":"delivered"}'
        return AuthoritativeObservation(
            source,
            "records-authority@1",
            "records://42",
            content.decode(),
            content,
            True,
            now,
            now + timedelta(minutes=5),
        )


async def provision_tenant(tenant_id: UUID) -> None:
    engine = create_async_engine(os.environ["AUTONOESIS_TEST_ADMIN_DATABASE_URL"])
    try:
        async with engine.begin() as connection:
            await connection.execute(
                text(
                    "INSERT INTO tenants (id, name, created_at) "
                    "VALUES (:id, :name, CURRENT_TIMESTAMP)"
                ),
                {"id": str(tenant_id), "name": f"evidence-{tenant_id}"},
            )
    finally:
        await engine.dispose()


def context(identity: IdentityContext, key: str) -> CommandContext:
    correlation = uuid4()
    from hashlib import sha256

    return CommandContext(
        identity,
        correlation,
        correlation,
        key,
        sha256(key.encode()).hexdigest(),
    )


@pytest.mark.asyncio
async def test_trusted_chain_survives_independent_store_and_retains_deletion_tombstone() -> None:
    tenant_id, actor_id, agent_id = uuid4(), uuid4(), uuid4()
    await provision_tenant(tenant_id)
    first = PostgreSQLPlatformStore.from_url(os.environ["AUTONOESIS_TEST_DATABASE_URL"])
    second = PostgreSQLPlatformStore.from_url(os.environ["AUTONOESIS_TEST_DATABASE_URL"])
    client = boto3.client(
        "s3",
        endpoint_url=os.environ["AUTONOESIS_TEST_MINIO_URL"],
        aws_access_key_id=os.getenv("AUTONOESIS_TEST_MINIO_ACCESS_KEY", "autonoesis"),
        aws_secret_access_key=os.getenv("AUTONOESIS_TEST_MINIO_SECRET_KEY", "autonoesis-test-only"),
        region_name="us-east-1",
    )
    bucket = f"autonoesis-evidence-{uuid4()}"
    client.create_bucket(Bucket=bucket, ObjectLockEnabledForBucket=True)
    artifacts = MinioEvidenceStore(Boto3ObjectStore(client), bucket)
    identity = IdentityContext(
        tenant_id,
        actor_id,
        actor_id,
        frozenset({"operator", "tenant_admin"}),
        "evidence-agent",
    )
    try:
        goal = GoalContract(
            tenant_id,
            "evidence.verify",
            "verify delivered record",
            "authoritative state is delivered",
            (SubjectRef("records", "record", "42"),),
            (SuccessCriterion("delivered", "record delivered", "authoritative-readback"),),
            (),
            actor_id,
            RiskTier.MEDIUM,
            BudgetAmount(100),
            datetime.now(UTC) + timedelta(hours=1),
            JsonObject.from_value({}),
        )
        await first.add_goal(
            goal,
            AuditEvent(
                tenant_id,
                actor_id,
                actor_id,
                "goal.created",
                "goal",
                str(goal.goal_id),
                uuid4(),
                {},
            ),
        )
        run = Run(tenant_id, goal.goal_id, agent_id)
        await first.add_run(
            run,
            AuditEvent(
                tenant_id,
                actor_id,
                actor_id,
                "run.requested",
                "run",
                str(run.run_id),
                uuid4(),
                {},
            ),
        )
        task = Task(
            tenant_id,
            run.run_id,
            "deliver",
            "readback is delivered",
            risk_level=RiskLevel.L2_REVERSIBLE_WRITE,
            evidence_requirements=("authoritative-readback",),
        )
        await first.repository.add_plan(Plan(tenant_id, goal.goal_id, run.run_id, (task,)))
        action = Action(
            tenant_id,
            run.run_id,
            task.task_id,
            "records",
            "1.0.0",
            "update",
            "records/42",
            JsonObject.from_value({"status": "delivered"}),
            RiskLevel.L2_REVERSIBLE_WRITE,
            "evidence-component-action",
            "record becomes delivered",
            DataClassification.INTERNAL,
        )
        action = (
            action.transition_to(ActionStatus.AUTHORIZED)
            .transition_to(ActionStatus.EXECUTING)
            .transition_to(ActionStatus.SUCCEEDED)
        )
        await first.repository.add_action(action)
        application = GoalExecutionApplication(
            first.repository,
            first,
            evidence_artifacts=artifacts,
            authoritative_readback=StableReadback(),
        )
        evidence = await application.capture_authoritative_evidence(
            context(identity, "component-capture"),
            CaptureAuthoritativeEvidence(run.run_id, action.action_id, "delivered", "records"),
        )
        outcome = await application.verify_outcome(
            context(identity, "component-outcome"),
            VerifyOutcome(run.run_id, "delivered", (evidence.evidence_id,)),
        )
        assert outcome.status is OutcomeStatus.VERIFIED
        assert outcome.evidence == (evidence,)

        persisted = await second.repository.get_evidence(tenant_id, evidence.evidence_id)
        saga = await second.repository.get_evidence_capture(tenant_id, evidence.evidence_id)
        assert persisted == evidence
        assert saga.status.value == "committed"

        tombstone = await application.request_evidence_deletion(
            context(identity, "component-delete"),
            RequestEvidenceDeletion(evidence.evidence_id, "data subject request"),
        )
        assert tombstone.status.value == "retention_blocked"
        assert (
            await second.repository.get_evidence_deletion(tenant_id, evidence.evidence_id)
        ) == tombstone
        assert (
            await artifacts.retrieve_verified(
                EvidenceArtifactDescriptor(
                    tenant_id,
                    evidence.evidence_id,
                    evidence.reference,
                    evidence.content_digest,
                    evidence.classification,
                    len(b'{"status":"delivered"}'),
                    evidence.retained_until or evidence.valid_until,
                    evidence.artifact_version_id,
                )
            )
            == b'{"status":"delivered"}'
        )

        audits = await second.list_audit_events(tenant_id)
        assert verify_audit_chain(audits)
        verified_event = next(item for item in audits if item.event_type == "outcome.verified")
        assert verified_event.actor_id == actor_id
        assert verified_event.principal_id == actor_id
        assert verified_event.details["evidence_ids"] == [str(evidence.evidence_id)]
        assert verified_event.audit_ref is not None

        concurrent = tuple(
            AuditEvent(
                tenant_id,
                actor_id,
                actor_id,
                f"audit.concurrent_{index}",
                "run",
                str(run.run_id),
                uuid4(),
                {"index": index},
            )
            for index in range(2)
        )
        await asyncio.gather(
            first.repository.record_audit(concurrent[0]),
            second.repository.record_audit(concurrent[1]),
        )
        after_concurrency = await second.list_audit_events(tenant_id)
        assert verify_audit_chain(after_concurrency)
        assert len({item.sequence for item in after_concurrency}) == len(after_concurrency)
    finally:
        await first.close()
        await second.close()
