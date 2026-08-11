"""Real MinIO component test for encryption, versioning, retention, and tenant keys."""

import asyncio
import os
from contextlib import suppress
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from urllib.parse import urlparse
from uuid import uuid4

import boto3
import pytest
from autonoesis_adapters import Boto3ObjectStore, MinioEvidenceStore
from autonoesis_domain import DataClassification
from botocore.exceptions import ClientError

pytestmark = pytest.mark.skipif(
    not os.getenv("AUTONOESIS_TEST_MINIO_URL"),
    reason="requires an explicitly configured MinIO component endpoint",
)


@pytest.mark.asyncio
async def test_minio_artifact_is_encrypted_versioned_locked_and_digest_verified() -> None:
    endpoint = os.environ["AUTONOESIS_TEST_MINIO_URL"]
    access_key = os.getenv("AUTONOESIS_TEST_MINIO_ACCESS_KEY", "autonoesis")
    secret_key = os.getenv("AUTONOESIS_TEST_MINIO_SECRET_KEY", "autonoesis-test-only")
    client = boto3.client(
        "s3",
        endpoint_url=endpoint,
        aws_access_key_id=access_key,
        aws_secret_access_key=secret_key,
        region_name="us-east-1",
    )
    bucket = f"autonoesis-evidence-{uuid4()}"
    client.create_bucket(Bucket=bucket, ObjectLockEnabledForBucket=True)
    store = MinioEvidenceStore(Boto3ObjectStore(client), bucket)
    tenant_id, evidence_id = uuid4(), uuid4()
    content = b'{"status":"delivered"}'
    retained_until = datetime.now(UTC) + timedelta(seconds=3)
    descriptor = store.describe(
        tenant_id,
        evidence_id,
        sha256(content).hexdigest(),
        DataClassification.INTERNAL,
        len(content),
        retained_until,
    )
    try:
        stored = await store.store(descriptor, content, "application/json")
        assert stored.version_id
        assert await store.retrieve_verified(stored) == content

        parsed = urlparse(stored.artifact_uri)
        assert parsed.path.startswith(f"/tenants/{tenant_id}/evidence/{evidence_id}/")
        head = client.head_object(
            Bucket=bucket,
            Key=parsed.path.lstrip("/"),
            VersionId=stored.version_id,
        )
        assert head["ServerSideEncryption"] == "AES256"
        assert head["ObjectLockMode"] == "COMPLIANCE"
        assert head["Metadata"]["tenant-id"] == str(tenant_id)
        assert head["Metadata"]["sha256"] == stored.content_digest
        with pytest.raises(PermissionError, match="retention"):
            await store.delete(stored)

        await asyncio.sleep(3.1)
        receipt = await store.delete(stored)
        assert receipt.provider_version_id == stored.version_id
        assert len(receipt.proof_digest) == 64
    finally:
        # The CI/local MinIO container is ephemeral. Best-effort cleanup succeeds after retention.
        versions = client.list_object_versions(Bucket=bucket)
        for version in versions.get("Versions", []):
            with suppress(ClientError):
                client.delete_object(
                    Bucket=bucket,
                    Key=version["Key"],
                    VersionId=version["VersionId"],
                )
        with suppress(ClientError):
            client.delete_bucket(Bucket=bucket)
