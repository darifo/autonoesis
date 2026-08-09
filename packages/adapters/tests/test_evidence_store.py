# mypy: disable_error_code = no-untyped-def
"""Tests for MinioEvidenceStore."""

import pytest
from autonoesis_adapters.evidence_store import (
    InMemoryObjectStore,
    MinioEvidenceStore,
)
from autonoesis_contracts import DataClassification


@pytest.fixture
def store() -> MinioEvidenceStore:
    return MinioEvidenceStore(InMemoryObjectStore())


class TestMinioEvidenceStore:
    @pytest.mark.asyncio
    async def test_store_and_retrieve(self, store) -> None:
        artifact = await store.store("ev-1", "hello world", "text/plain")

        retrieved = await store.retrieve(artifact.artifact_uri)
        assert retrieved == b"hello world"

    @pytest.mark.asyncio
    async def test_content_addressing_deduplicates(self, store) -> None:
        a1 = await store.store("ev-1", "same content")
        a2 = await store.store("ev-2", "same content")

        # Same digest — content-addressed storage
        assert a1.content_digest == a2.content_digest
        assert a1.size_bytes == a2.size_bytes

    @pytest.mark.asyncio
    async def test_different_content_different_digest(self, store) -> None:
        a1 = await store.store("ev-1", "content A")
        a2 = await store.store("ev-2", "content B")

        assert a1.content_digest != a2.content_digest

    @pytest.mark.asyncio
    async def test_delete(self, store) -> None:
        artifact = await store.store("ev-1", "to be deleted")
        await store.delete(artifact.artifact_uri)

        retrieved = await store.retrieve(artifact.artifact_uri)
        assert retrieved is None

    @pytest.mark.asyncio
    async def test_retrieve_missing(self, store) -> None:
        result = await store.retrieve("minio://autonoesis-evidence/nonexistent/key")
        assert result is None

    @pytest.mark.asyncio
    async def test_classify_internal(self, store) -> None:
        artifact = await store.store("ev-1", "routine operation log")
        assert artifact.classification == DataClassification.INTERNAL

    @pytest.mark.asyncio
    async def test_classify_confidential_with_email(self, store) -> None:
        artifact = await store.store("ev-1", "user: alice@example.com completed task")
        assert artifact.classification == DataClassification.CONFIDENTIAL

    @pytest.mark.asyncio
    async def test_classify_confidential_with_ssn(self, store) -> None:
        artifact = await store.store("ev-1", "subject: 123-45-6789 approved")
        assert artifact.classification == DataClassification.CONFIDENTIAL

    @pytest.mark.asyncio
    async def test_classify_restricted_with_secret(self, store) -> None:
        artifact = await store.store("ev-1", "config: api_key=sk-abc123")
        assert artifact.classification == DataClassification.RESTRICTED

    @pytest.mark.asyncio
    async def test_classify_restricted_with_private_key(self, store) -> None:
        artifact = await store.store("ev-1", "-----BEGIN RSA PRIVATE KEY-----\nMIIEpAIBAAKCAQEA...")
        assert artifact.classification == DataClassification.RESTRICTED

    @pytest.mark.asyncio
    async def test_artifact_uri_format(self, store) -> None:
        artifact = await store.store("ev-42", b"\x00\x01\x02", "application/octet-stream")

        assert artifact.artifact_uri.startswith("minio://autonoesis-evidence/evidence/ev-42/")
        assert artifact.content_digest == artifact.artifact_uri.split("/")[-1]
        assert artifact.size_bytes == 3

    @pytest.mark.asyncio
    async def test_unsupported_uri_scheme_raises(self, store) -> None:
        with pytest.raises(ValueError, match="unsupported artifact URI scheme"):
            await store.retrieve("s3://bucket/key")

    @pytest.mark.asyncio
    async def test_invalid_uri_raises(self, store) -> None:
        with pytest.raises(ValueError, match="invalid artifact URI"):
            await store.retrieve("minio://bucket")  # no key part
