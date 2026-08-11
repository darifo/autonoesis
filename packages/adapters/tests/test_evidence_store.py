"""Tests for immutable tenant-prefixed Evidence storage and admission policy."""

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from uuid import uuid4

import pytest
from autonoesis_adapters.evidence_store import InMemoryObjectStore, MinioEvidenceStore
from autonoesis_application import (
    EvidenceAdmissionPolicy,
    EvidenceAdmissionRejected,
    EvidenceArtifactDescriptor,
)
from autonoesis_domain import DataClassification


def descriptor(
    store: MinioEvidenceStore,
    content: bytes,
    *,
    retained_until: datetime | None = None,
) -> EvidenceArtifactDescriptor:
    return store.describe(
        uuid4(),
        uuid4(),
        sha256(content).hexdigest(),
        DataClassification.INTERNAL,
        len(content),
        retained_until or datetime.now(UTC) + timedelta(days=30),
    )


@pytest.mark.asyncio
async def test_store_retrieve_and_tenant_prefix() -> None:
    store = MinioEvidenceStore(InMemoryObjectStore())
    item = descriptor(store, b"hello world")
    stored = await store.store(item, b"hello world", "text/plain")

    assert await store.retrieve_verified(stored) == b"hello world"
    assert f"tenants/{item.tenant_id}/evidence/{item.evidence_id}/" in stored.artifact_uri
    assert stored.version_id is not None


@pytest.mark.asyncio
async def test_retry_same_content_reuses_object_version() -> None:
    store = MinioEvidenceStore(InMemoryObjectStore())
    item = descriptor(store, b"same content")

    first = await store.store(item, b"same content", "application/octet-stream")
    second = await store.store(item, b"same content", "application/octet-stream")
    assert second.version_id == first.version_id


@pytest.mark.asyncio
async def test_descriptor_mismatch_is_rejected_before_storage() -> None:
    store = MinioEvidenceStore(InMemoryObjectStore())
    item = descriptor(store, b"expected")

    with pytest.raises(ValueError, match="immutable descriptor"):
        await store.store(item, b"modified", "application/octet-stream")


@pytest.mark.asyncio
async def test_tampering_is_detected_on_retrieval() -> None:
    raw = InMemoryObjectStore()
    store = MinioEvidenceStore(raw)
    item = await store.store(descriptor(store, b"original"), b"original", "text/plain")
    bucket, key = store._location(item.artifact_uri)
    assert item.version_id is not None
    raw.tamper(bucket, key, item.version_id, b"modified")

    with pytest.raises(ValueError, match="digest verification failed"):
        await store.retrieve_verified(item)


@pytest.mark.asyncio
async def test_object_retention_blocks_delete_then_emits_proof() -> None:
    raw = InMemoryObjectStore()
    store = MinioEvidenceStore(raw)
    locked = await store.store(descriptor(store, b"locked"), b"locked", "text/plain")
    with pytest.raises(PermissionError, match="retention"):
        await store.delete(locked)

    expired = descriptor(
        store,
        b"expired",
        retained_until=datetime.now(UTC) - timedelta(seconds=1),
    )
    expired = await store.store(expired, b"expired", "text/plain")
    receipt = await store.delete(expired)
    assert len(receipt.proof_digest) == 64
    with pytest.raises(LookupError, match="missing"):
        await store.retrieve_verified(expired)


@pytest.mark.asyncio
async def test_unsupported_artifact_uri_is_rejected() -> None:
    store = MinioEvidenceStore(InMemoryObjectStore())
    item = replace(descriptor(store, b"content"), artifact_uri="https://example.test/object")
    with pytest.raises(ValueError, match="unsupported Evidence artifact URI"):
        await store.retrieve_verified(item)


def test_admission_classifies_pii_and_rejects_secrets_before_write() -> None:
    policy = EvidenceAdmissionPolicy()
    assert (
        policy.admit(
            b"alice@example.com",
            DataClassification.INTERNAL,
            DataClassification.CONFIDENTIAL,
            30,
        )
        is DataClassification.CONFIDENTIAL
    )
    with pytest.raises(EvidenceAdmissionRejected, match="detected secret"):
        policy.admit(
            b"api_key=secret-value",
            DataClassification.INTERNAL,
            DataClassification.RESTRICTED,
            30,
        )


def test_admission_enforces_goal_classification_and_retention() -> None:
    policy = EvidenceAdmissionPolicy()
    with pytest.raises(EvidenceAdmissionRejected, match="classification exceeds"):
        policy.admit(
            b"alice@example.com",
            DataClassification.INTERNAL,
            DataClassification.INTERNAL,
            30,
        )
    with pytest.raises(EvidenceAdmissionRejected, match="retention"):
        policy.admit(
            b"ordinary",
            DataClassification.INTERNAL,
            DataClassification.INTERNAL,
            0,
        )
