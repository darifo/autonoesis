"""Trusted Evidence artifact, readback, retention, and recovery contracts."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from hashlib import sha256
from typing import ClassVar, Protocol
from uuid import UUID

from autonoesis_domain import (
    DataClassification,
    Evidence,
    OutcomeStatus,
    SubjectRef,
    SuccessCriterion,
)


class EvidenceAdmissionRejected(ValueError):
    """Evidence content violates classification, secret, size, or retention policy."""


class EvidenceCaptureStatus(StrEnum):
    PENDING = "pending"
    COMMITTED = "committed"
    FAILED = "failed"


class EvidenceDeletionStatus(StrEnum):
    REQUESTED = "requested"
    RETENTION_BLOCKED = "retention_blocked"
    DELETED = "deleted"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class EvidenceArtifactDescriptor:
    tenant_id: UUID
    evidence_id: UUID
    artifact_uri: str
    content_digest: str
    classification: DataClassification
    size_bytes: int
    retained_until: datetime
    version_id: str | None = None


@dataclass(frozen=True, slots=True)
class AuthoritativeObservation:
    source: str
    source_identity: str
    reference: str
    observed_state: str
    content: bytes
    criterion_met: bool | None
    captured_at: datetime
    valid_until: datetime

    def __post_init__(self) -> None:
        if any(
            not value.strip()
            for value in (self.source, self.source_identity, self.reference, self.observed_state)
        ):
            raise ValueError("authoritative observation identity and state must not be empty")
        if self.captured_at.tzinfo is None or self.valid_until.tzinfo is None:
            raise ValueError("authoritative observation timestamps must be timezone-aware")
        if self.valid_until < self.captured_at:
            raise ValueError("authoritative observation validity cannot precede capture")

    @property
    def content_digest(self) -> str:
        return sha256(self.content).hexdigest()


@dataclass(frozen=True, slots=True)
class OutcomeVerificationDecision:
    status: OutcomeStatus
    verifier_version: str
    verified_at: datetime


@dataclass(frozen=True, slots=True)
class EvidenceCaptureSaga:
    tenant_id: UUID
    evidence_id: UUID
    run_id: UUID
    action_id: UUID
    criterion_id: str
    source: str
    artifact_uri: str
    expected_digest: str
    definition: dict[str, object]
    status: EvidenceCaptureStatus = EvidenceCaptureStatus.PENDING
    failure_reason: str | None = None


@dataclass(frozen=True, slots=True)
class EvidenceDeletionRecord:
    tenant_id: UUID
    evidence_id: UUID
    artifact_uri: str
    requested_by: UUID
    reason: str
    requested_at: datetime
    status: EvidenceDeletionStatus = EvidenceDeletionStatus.REQUESTED
    deleted_at: datetime | None = None
    provider_version_id: str | None = None
    proof_digest: str | None = None
    failure_reason: str | None = None


@dataclass(frozen=True, slots=True)
class ArtifactDeletionReceipt:
    deleted_at: datetime
    provider_version_id: str | None
    proof_digest: str


class EvidenceArtifactStore(Protocol):
    def describe(
        self,
        tenant_id: UUID,
        evidence_id: UUID,
        content_digest: str,
        classification: DataClassification,
        size_bytes: int,
        retained_until: datetime,
    ) -> EvidenceArtifactDescriptor: ...

    async def store(
        self, descriptor: EvidenceArtifactDescriptor, content: bytes, content_type: str
    ) -> EvidenceArtifactDescriptor: ...

    async def retrieve_verified(self, descriptor: EvidenceArtifactDescriptor) -> bytes: ...

    async def delete(self, descriptor: EvidenceArtifactDescriptor) -> ArtifactDeletionReceipt: ...


class AuthoritativeReadback(Protocol):
    async def observe(
        self,
        source: str,
        tenant_id: UUID,
        subject_refs: tuple[SubjectRef, ...],
        criterion: SuccessCriterion,
    ) -> AuthoritativeObservation: ...


class EvidenceRecoveryRepository(Protocol):
    async def start_evidence_capture(self, saga: EvidenceCaptureSaga) -> None: ...

    async def get_evidence_capture(
        self, tenant_id: UUID, evidence_id: UUID
    ) -> EvidenceCaptureSaga: ...

    async def complete_evidence_capture(self, tenant_id: UUID, evidence_id: UUID) -> None: ...

    async def record_evidence_deletion(self, record: EvidenceDeletionRecord) -> None: ...

    async def get_evidence_deletion(
        self, tenant_id: UUID, evidence_id: UUID
    ) -> EvidenceDeletionRecord: ...


@dataclass(frozen=True, slots=True)
class EvidenceAdmissionPolicy:
    maximum_bytes: int = 10 * 1024 * 1024
    reject_detected_secrets: bool = True

    _PII_PATTERNS = (
        re.compile(r"\b\d{3}-\d{2}-\d{4}\b"),
        re.compile(r"\b\d{13,19}\b"),
        re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b"),
    )
    _SECRET_PATTERNS = (
        re.compile(r"(?i)(api[_-]?key|secret|token|password|credential)\s*[:=]\s*\S+"),
        re.compile(r"-----BEGIN (RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    )
    _RANK: ClassVar[dict[DataClassification, int]] = {
        DataClassification.PUBLIC: 0,
        DataClassification.INTERNAL: 1,
        DataClassification.CONFIDENTIAL: 2,
        DataClassification.RESTRICTED: 3,
    }

    def admit(
        self,
        content: bytes,
        declared: DataClassification,
        maximum: DataClassification,
        retention_days: int,
    ) -> DataClassification:
        if not content:
            raise EvidenceAdmissionRejected("evidence content must not be empty")
        if len(content) > self.maximum_bytes:
            raise EvidenceAdmissionRejected("evidence content exceeds the configured size limit")
        if retention_days <= 0:
            raise EvidenceAdmissionRejected("evidence retention must be positive")
        text = content.decode("utf-8", errors="replace")
        if any(pattern.search(text) for pattern in self._SECRET_PATTERNS):
            if self.reject_detected_secrets:
                raise EvidenceAdmissionRejected("evidence content contains a detected secret")
            detected = DataClassification.RESTRICTED
        elif any(pattern.search(text) for pattern in self._PII_PATTERNS):
            detected = DataClassification.CONFIDENTIAL
        else:
            detected = DataClassification.INTERNAL
        effective = max((declared, detected), key=self._RANK.__getitem__)
        if self._RANK[effective] > self._RANK[maximum]:
            raise EvidenceAdmissionRejected("evidence classification exceeds the Goal data policy")
        return effective


class TrustedOutcomeVerifier:
    """Re-read authority and verify immutable artifact bytes before deciding an Outcome."""

    def __init__(
        self,
        readback: AuthoritativeReadback,
        artifacts: EvidenceArtifactStore,
        *,
        verifier_version: str = "trusted-readback@1",
    ) -> None:
        self._readback = readback
        self._artifacts = artifacts
        self._version = verifier_version

    async def verify(
        self,
        tenant_id: UUID,
        subjects: tuple[SubjectRef, ...],
        criterion: SuccessCriterion,
        evidence: tuple[Evidence, ...],
        now: datetime,
    ) -> OutcomeVerificationDecision:
        candidates = tuple(
            item
            for item in evidence
            if item.capture_method.value == "authoritative_readback"
            and item.valid_from <= now <= item.valid_until
            and item.integrity.value == "verified"
        )
        if not candidates:
            return OutcomeVerificationDecision(OutcomeStatus.UNKNOWN, self._version, now)
        for item in candidates:
            descriptor = EvidenceArtifactDescriptor(
                item.tenant_id,
                item.evidence_id,
                item.reference,
                item.content_digest,
                item.classification,
                0,
                item.retained_until or item.valid_until,
                item.artifact_version_id,
            )
            try:
                content = await self._artifacts.retrieve_verified(descriptor)
                observation = await self._readback.observe(
                    item.source, tenant_id, subjects, criterion
                )
            except (LookupError, ValueError):
                continue
            if (
                sha256(content).hexdigest() != item.content_digest
                or observation.content_digest != item.content_digest
                or observation.source_identity != item.source_identity
                or observation.reference != item.source_reference
                or observation.observed_state != item.observed_state
                or (item.subject_refs and item.subject_refs != subjects)
            ):
                continue
            status = (
                OutcomeStatus.VERIFIED
                if observation.criterion_met is True
                else OutcomeStatus.NOT_MET
                if observation.criterion_met is False
                else OutcomeStatus.UNKNOWN
            )
            return OutcomeVerificationDecision(status, self._version, now)
        return OutcomeVerificationDecision(OutcomeStatus.UNKNOWN, self._version, now)
