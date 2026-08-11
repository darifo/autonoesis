"""Negative-path tests for trusted Outcome and audit verification."""

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from urllib.parse import urlparse
from uuid import UUID, uuid4

import pytest
from autonoesis_adapters import InMemoryObjectStore, MinioEvidenceStore
from autonoesis_application import (
    ArtifactDeletionReceipt,
    AuditEvent,
    AuthoritativeObservation,
    EvidenceArtifactDescriptor,
    TrustedOutcomeVerifier,
    verify_audit_chain,
)
from autonoesis_domain import (
    DataClassification,
    Evidence,
    EvidenceCaptureMethod,
    EvidenceIntegrity,
    OutcomeStatus,
    SubjectRef,
    SuccessCriterion,
)


class Readback:
    def __init__(self, content: bytes, identity: str = "records-authority@1") -> None:
        self.content = content
        self.identity = identity

    async def observe(
        self,
        source: str,
        tenant_id: UUID,
        subject_refs: tuple[SubjectRef, ...],
        criterion: SuccessCriterion,
    ) -> AuthoritativeObservation:
        _ = (tenant_id, subject_refs, criterion)
        now = datetime.now(UTC)
        return AuthoritativeObservation(
            source,
            self.identity,
            "records://42",
            self.content.decode(),
            self.content,
            True,
            now,
            now + timedelta(minutes=5),
        )


class DescriptorRecordingStore:
    def __init__(self, inner: MinioEvidenceStore) -> None:
        self.inner = inner
        self.retrieved: EvidenceArtifactDescriptor | None = None

    def describe(
        self,
        tenant_id: UUID,
        evidence_id: UUID,
        content_digest: str,
        classification: DataClassification,
        size_bytes: int,
        retained_until: datetime,
    ) -> EvidenceArtifactDescriptor:
        return self.inner.describe(
            tenant_id,
            evidence_id,
            content_digest,
            classification,
            size_bytes,
            retained_until,
        )

    async def store(
        self, descriptor: EvidenceArtifactDescriptor, content: bytes, content_type: str
    ) -> EvidenceArtifactDescriptor:
        return await self.inner.store(descriptor, content, content_type)

    async def retrieve_verified(self, descriptor: EvidenceArtifactDescriptor) -> bytes:
        self.retrieved = descriptor
        return await self.inner.retrieve_verified(descriptor)

    async def delete(self, descriptor: EvidenceArtifactDescriptor) -> ArtifactDeletionReceipt:
        return await self.inner.delete(descriptor)


async def stored_evidence(
    raw: InMemoryObjectStore,
    *,
    valid_until: datetime | None = None,
) -> tuple[MinioEvidenceStore, Evidence]:
    store = MinioEvidenceStore(raw)
    tenant_id, evidence_id, run_id, action_id = uuid4(), uuid4(), uuid4(), uuid4()
    content = b'{"status":"delivered"}'
    captured_at = datetime.now(UTC) - timedelta(seconds=1)
    descriptor = store.describe(
        tenant_id,
        evidence_id,
        sha256(content).hexdigest(),
        DataClassification.INTERNAL,
        len(content),
        datetime.now(UTC) + timedelta(days=30),
    )
    descriptor = await store.store(descriptor, content, "application/json")
    return store, Evidence(
        tenant_id,
        run_id,
        action_id,
        "records",
        "records-authority@1",
        EvidenceCaptureMethod.AUTHORITATIVE_READBACK,
        descriptor.artifact_uri,
        content.decode(),
        descriptor.content_digest,
        DataClassification.INTERNAL,
        captured_at,
        valid_until or datetime.now(UTC) + timedelta(minutes=5),
        EvidenceIntegrity.VERIFIED,
        source_reference="records://42",
        subject_refs=(SubjectRef("records", "record", "42"),),
        retained_until=descriptor.retained_until,
        artifact_version_id=descriptor.version_id,
        evidence_id=evidence_id,
        captured_at=captured_at,
    )


@pytest.mark.asyncio
async def test_verified_outcome_requires_current_authority_and_immutable_bytes() -> None:
    raw = InMemoryObjectStore()
    store, evidence = await stored_evidence(raw)
    criterion = SuccessCriterion("delivered", "record delivered", "authoritative-readback")
    recording = DescriptorRecordingStore(store)
    verifier = TrustedOutcomeVerifier(Readback(b'{"status":"delivered"}'), recording)

    decision = await verifier.verify(
        evidence.tenant_id,
        evidence.subject_refs,
        criterion,
        (evidence,),
        datetime.now(UTC),
    )
    assert decision.status is OutcomeStatus.VERIFIED
    assert recording.retrieved is not None
    assert recording.retrieved.version_id == evidence.artifact_version_id
    assert recording.retrieved.retained_until == evidence.retained_until

    parsed = urlparse(evidence.reference)
    assert evidence.artifact_version_id is not None
    raw.tamper(
        parsed.netloc,
        parsed.path.lstrip("/"),
        evidence.artifact_version_id,
        b"modified",
    )
    tampered = await verifier.verify(
        evidence.tenant_id,
        evidence.subject_refs,
        criterion,
        (evidence,),
        datetime.now(UTC),
    )
    assert tampered.status is OutcomeStatus.UNKNOWN


@pytest.mark.asyncio
async def test_stale_or_untrusted_evidence_cannot_verify() -> None:
    raw = InMemoryObjectStore()
    store, evidence = await stored_evidence(
        raw, valid_until=datetime.now(UTC) - timedelta(milliseconds=1)
    )
    criterion = SuccessCriterion("delivered", "record delivered", "authoritative-readback")
    stale = await TrustedOutcomeVerifier(Readback(b'{"status":"delivered"}'), store).verify(
        evidence.tenant_id,
        evidence.subject_refs,
        criterion,
        (evidence,),
        datetime.now(UTC),
    )
    assert stale.status is OutcomeStatus.UNKNOWN

    current_store, current = await stored_evidence(InMemoryObjectStore())
    untrusted = await TrustedOutcomeVerifier(
        Readback(b'{"status":"delivered"}', "attacker"), current_store
    ).verify(
        current.tenant_id,
        current.subject_refs,
        criterion,
        (current,),
        datetime.now(UTC),
    )
    assert untrusted.status is OutcomeStatus.UNKNOWN


def test_audit_chain_detects_detail_tampering() -> None:
    tenant_id = uuid4()
    first = AuditEvent(
        tenant_id,
        uuid4(),
        uuid4(),
        "action.authorized",
        "action",
        str(uuid4()),
        uuid4(),
        {"policy": "policy@1", "approval": str(uuid4())},
    ).chained(1, "0" * 64, datetime.now(UTC))
    second = AuditEvent(
        tenant_id,
        uuid4(),
        uuid4(),
        "outcome.verified",
        "outcome",
        str(uuid4()),
        uuid4(),
        {"evidence": [str(uuid4())]},
    ).chained(2, first.event_digest or "", datetime.now(UTC))

    assert verify_audit_chain((first, second))
    assert not verify_audit_chain((first, replace(second, details={"evidence": []})))
