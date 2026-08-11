"""S3/MinIO immutable Evidence artifacts with tenant prefixes and object retention."""

from __future__ import annotations

import asyncio
import base64
from dataclasses import replace
from datetime import UTC, datetime
from hashlib import sha256
from typing import Any, Protocol, cast
from urllib.parse import urlparse
from uuid import UUID

from autonoesis_application import (
    ArtifactDeletionReceipt,
    EvidenceArtifactDescriptor,
)
from autonoesis_domain import DataClassification
from botocore.exceptions import ClientError


class ObjectStorePort(Protocol):
    async def put(
        self,
        bucket: str,
        key: str,
        data: bytes,
        content_type: str,
        metadata: dict[str, str],
        retained_until: datetime,
    ) -> str | None: ...

    async def get(self, bucket: str, key: str, version_id: str | None) -> bytes | None: ...

    async def delete(self, bucket: str, key: str, version_id: str | None) -> str | None: ...


class Boto3ObjectStore:
    """Async facade over a configured boto3 S3 client without leaking provider objects."""

    def __init__(self, client: Any) -> None:
        self._client = client

    async def put(
        self,
        bucket: str,
        key: str,
        data: bytes,
        content_type: str,
        metadata: dict[str, str],
        retained_until: datetime,
    ) -> str | None:
        checksum = base64.b64encode(bytes.fromhex(metadata["sha256"])).decode("ascii")

        def invoke() -> dict[str, Any]:
            try:
                current = cast(dict[str, Any], self._client.head_object(Bucket=bucket, Key=key))
            except ClientError as exc:
                if str(exc.response.get("Error", {}).get("Code")) not in {
                    "404",
                    "NoSuchKey",
                    "NotFound",
                }:
                    raise
            else:
                if current.get("Metadata", {}).get("sha256") != metadata["sha256"]:
                    raise ValueError("content-addressed Evidence key has conflicting metadata")
                if current.get("ServerSideEncryption") != "AES256":
                    raise ValueError("existing Evidence object is not server-side encrypted")
                if current.get("ObjectLockMode") != "COMPLIANCE":
                    raise ValueError("existing Evidence object is not compliance locked")
                return current
            return cast(
                dict[str, Any],
                self._client.put_object(
                    Bucket=bucket,
                    Key=key,
                    Body=data,
                    ContentType=content_type,
                    Metadata=metadata,
                    ChecksumSHA256=checksum,
                    ServerSideEncryption="AES256",
                    ObjectLockMode="COMPLIANCE",
                    ObjectLockRetainUntilDate=retained_until,
                ),
            )

        response = await asyncio.to_thread(invoke)
        version = response.get("VersionId")
        return str(version) if version else None

    async def get(self, bucket: str, key: str, version_id: str | None) -> bytes | None:
        def invoke() -> bytes | None:
            arguments: dict[str, object] = {"Bucket": bucket, "Key": key}
            if version_id:
                arguments["VersionId"] = version_id
            try:
                response = self._client.get_object(**arguments)
            except ClientError as exc:
                if str(exc.response.get("Error", {}).get("Code")) in {
                    "404",
                    "NoSuchKey",
                    "NoSuchVersion",
                    "NotFound",
                }:
                    return None
                raise
            body = response["Body"]
            try:
                return bytes(body.read())
            finally:
                body.close()

        return await asyncio.to_thread(invoke)

    async def delete(self, bucket: str, key: str, version_id: str | None) -> str | None:
        def invoke() -> dict[str, Any]:
            arguments: dict[str, object] = {"Bucket": bucket, "Key": key}
            if version_id:
                arguments["VersionId"] = version_id
            return cast(dict[str, Any], self._client.delete_object(**arguments))

        response = await asyncio.to_thread(invoke)
        version = response.get("VersionId")
        return str(version) if version else version_id


class MinioEvidenceStore:
    """Provider-neutral Evidence artifact policy over an S3-compatible object store."""

    def __init__(self, store: ObjectStorePort, bucket: str = "autonoesis-evidence") -> None:
        if not bucket.strip():
            raise ValueError("Evidence bucket must not be empty")
        self._store = store
        self._bucket = bucket

    def describe(
        self,
        tenant_id: UUID,
        evidence_id: UUID,
        content_digest: str,
        classification: DataClassification,
        size_bytes: int,
        retained_until: datetime,
    ) -> EvidenceArtifactDescriptor:
        if len(content_digest) != 64:
            raise ValueError("Evidence artifact digest must be SHA-256")
        key = f"tenants/{tenant_id}/evidence/{evidence_id}/{content_digest}"
        return EvidenceArtifactDescriptor(
            tenant_id,
            evidence_id,
            f"s3://{self._bucket}/{key}",
            content_digest,
            classification,
            size_bytes,
            retained_until,
        )

    async def store(
        self,
        descriptor: EvidenceArtifactDescriptor,
        content: bytes,
        content_type: str,
    ) -> EvidenceArtifactDescriptor:
        actual = sha256(content).hexdigest()
        if actual != descriptor.content_digest or len(content) != descriptor.size_bytes:
            raise ValueError("Evidence content does not match its immutable descriptor")
        bucket, key = self._location(descriptor.artifact_uri)
        version = await self._store.put(
            bucket,
            key,
            content,
            content_type,
            {
                "sha256": actual,
                "tenant-id": str(descriptor.tenant_id),
                "evidence-id": str(descriptor.evidence_id),
                "classification": descriptor.classification.value,
            },
            descriptor.retained_until,
        )
        return replace(descriptor, version_id=version)

    async def retrieve_verified(self, descriptor: EvidenceArtifactDescriptor) -> bytes:
        bucket, key = self._location(descriptor.artifact_uri)
        content = await self._store.get(bucket, key, descriptor.version_id)
        if content is None:
            raise LookupError("Evidence artifact is missing")
        if sha256(content).hexdigest() != descriptor.content_digest:
            raise ValueError("Evidence artifact digest verification failed")
        return content

    async def delete(self, descriptor: EvidenceArtifactDescriptor) -> ArtifactDeletionReceipt:
        now = datetime.now(UTC)
        if now < descriptor.retained_until:
            raise PermissionError("Evidence object retention period has not expired")
        bucket, key = self._location(descriptor.artifact_uri)
        version = await self._store.delete(bucket, key, descriptor.version_id)
        proof = sha256(
            (
                f"{descriptor.tenant_id}\n{descriptor.evidence_id}\n"
                f"{descriptor.content_digest}\n{version or ''}\n{now.isoformat()}"
            ).encode()
        ).hexdigest()
        return ArtifactDeletionReceipt(now, version, proof)

    @staticmethod
    def _location(uri: str) -> tuple[str, str]:
        parsed = urlparse(uri)
        if parsed.scheme != "s3" or not parsed.netloc or not parsed.path.strip("/"):
            raise ValueError(f"unsupported Evidence artifact URI: {uri}")
        return parsed.netloc, parsed.path.lstrip("/")


class InMemoryObjectStore:
    """Strict in-memory S3 behavior for unit tests, including retention and versions."""

    def __init__(self) -> None:
        self._objects: dict[tuple[str, str, str], bytes] = {}
        self._latest: dict[tuple[str, str], str] = {}
        self._retention: dict[tuple[str, str, str], datetime] = {}
        self._version = 0

    async def put(
        self,
        bucket: str,
        key: str,
        data: bytes,
        content_type: str,
        metadata: dict[str, str],
        retained_until: datetime,
    ) -> str:
        _ = content_type
        latest = self._latest.get((bucket, key))
        if latest is not None and self._objects[(bucket, key, latest)] == data:
            return latest
        if sha256(data).hexdigest() != metadata["sha256"]:
            raise ValueError("object metadata digest does not match content")
        self._version += 1
        version = str(self._version)
        self._objects[(bucket, key, version)] = bytes(data)
        self._latest[(bucket, key)] = version
        self._retention[(bucket, key, version)] = retained_until
        return version

    async def get(self, bucket: str, key: str, version_id: str | None) -> bytes | None:
        version = version_id or self._latest.get((bucket, key))
        return self._objects.get((bucket, key, version)) if version is not None else None

    async def delete(self, bucket: str, key: str, version_id: str | None) -> str | None:
        version = version_id or self._latest.get((bucket, key))
        if version is None:
            return None
        if datetime.now(UTC) < self._retention[(bucket, key, version)]:
            raise PermissionError("object lock retention has not expired")
        self._objects.pop((bucket, key, version), None)
        self._retention.pop((bucket, key, version), None)
        if self._latest.get((bucket, key)) == version:
            self._latest.pop((bucket, key), None)
        return version

    def tamper(self, bucket: str, key: str, version_id: str, content: bytes) -> None:
        self._objects[(bucket, key, version_id)] = content
