"""MinIO-backed evidence store with content-addressing and classification."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from typing import Protocol

from autonoesis_contracts import DataClassification


class ObjectStorePort(Protocol):
    """Abstract object store for evidence artifacts.

    Kept as a Protocol so that tests can substitute an in-memory fake.
    """

    async def put(self, bucket: str, key: str, data: bytes, content_type: str) -> None:
        """Store *data* under *key* in *bucket*."""

    async def get(self, bucket: str, key: str) -> bytes | None:
        """Retrieve the object or ``None`` if not found."""

    async def delete(self, bucket: str, key: str) -> None:
        """Remove the object."""


@dataclass(frozen=True, slots=True)
class EvidenceArtifact:
    """Result of storing evidence in the object store."""

    artifact_uri: str
    content_digest: str
    size_bytes: int
    classification: DataClassification


class MinioEvidenceStore:
    """Stores evidence artifacts in a MinIO-compatible object store.

    Objects are content-addressed by SHA-256 digest.  This prevents
    duplicate storage and makes tampering detectable.
    """

    # Patterns that trigger higher classification tiers.
    _PII_PATTERNS = (
        re.compile(r"\b\d{3}-\d{2}-\d{4}\b"),  # SSN-like
        re.compile(r"\b\d{13,19}\b"),  # credit-card-like
        re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b"),  # email
    )

    _SECRET_PATTERNS = (
        re.compile(r"(?i)(api[_-]?key|secret|token|password|credential)\s*[:=]\s*\S+"),
        re.compile(r"-----BEGIN (RSA |EC )?PRIVATE KEY-----"),
    )

    def __init__(
        self,
        store: ObjectStorePort,
        bucket: str = "autonoesis-evidence",
    ) -> None:
        self._store = store
        self._bucket = bucket

    # ── public API ──────────────────────────────────────────────────────

    async def store(
        self,
        evidence_id: str,
        content: bytes | str,
        content_type: str = "application/octet-stream",
    ) -> EvidenceArtifact:
        """Persist *content* and return its artifact metadata.

        The object key is the SHA-256 digest of the content so identical
        evidence is stored only once.
        """
        data = content.encode("utf-8") if isinstance(content, str) else content
        digest = hashlib.sha256(data).hexdigest()
        key = f"evidence/{evidence_id}/{digest}"

        await self._store.put(self._bucket, key, data, content_type)

        return EvidenceArtifact(
            artifact_uri=f"minio://{self._bucket}/{key}",
            content_digest=digest,
            size_bytes=len(data),
            classification=self.classify(data),
        )

    async def retrieve(self, artifact_uri: str) -> bytes | None:
        """Retrieve content by its ``minio://`` artifact URI."""
        key = self._key_from_uri(artifact_uri)
        return await self._store.get(self._bucket, key)

    async def delete(self, artifact_uri: str) -> None:
        """Remove an artifact from the object store."""
        key = self._key_from_uri(artifact_uri)
        await self._store.delete(self._bucket, key)

    # ── classification ──────────────────────────────────────────────────

    @classmethod
    def classify(cls, data: bytes) -> DataClassification:
        """Determine the minimum data classification for *data*."""
        try:
            text = data.decode("utf-8", errors="replace")
        except Exception:
            return DataClassification.INTERNAL

        for pattern in cls._SECRET_PATTERNS:
            if pattern.search(text):
                return DataClassification.RESTRICTED

        for pattern in cls._PII_PATTERNS:
            if pattern.search(text):
                return DataClassification.CONFIDENTIAL

        return DataClassification.INTERNAL

    # ── helpers ─────────────────────────────────────────────────────────

    @staticmethod
    def _key_from_uri(uri: str) -> str:
        prefix = "minio://"
        if not uri.startswith(prefix):
            raise ValueError(f"unsupported artifact URI scheme: {uri}")
        parts = uri[len(prefix) :].split("/", 1)
        if len(parts) != 2:
            raise ValueError(f"invalid artifact URI: {uri}")
        return parts[1]


# ── In-memory fake for tests ────────────────────────────────────────────────


class InMemoryObjectStore:
    """Thread-unsafe in-memory object store for testing."""

    def __init__(self) -> None:
        self._objects: dict[str, bytes] = {}

    async def put(self, bucket: str, key: str, data: bytes, content_type: str) -> None:
        self._objects[f"{bucket}/{key}"] = data

    async def get(self, bucket: str, key: str) -> bytes | None:
        return self._objects.get(f"{bucket}/{key}")

    async def delete(self, bucket: str, key: str) -> None:
        self._objects.pop(f"{bucket}/{key}", None)
