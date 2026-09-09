"""Configure evidence object-store retention (P2-02).

Enables bucket versioning and a lifecycle rule expiring noncurrent versions
after a retention window, and reports Object-Lock configuration. Evidence
buckets must be versioned with COMPLIANCE-mode locks applied at write time
(the trusted evidence chain already does); this tool enforces the bucket-side
baseline so no unversioned bucket can quietly accumulate authoritative
evidence.
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any

import boto3


def configure(
    endpoint_url: str, bucket: str, access_key: str, secret_key: str, noncurrent_days: int
) -> dict[str, Any]:
    client = boto3.client(
        "s3",
        endpoint_url=endpoint_url,
        aws_access_key_id=access_key,
        aws_secret_access_key=secret_key,
        region_name="us-east-1",
    )
    client.put_bucket_versioning(Bucket=bucket, VersioningConfiguration={"Status": "Enabled"})
    lifecycle = {
        "Rules": [
            {
                "ID": "expire-noncurrent-evidence",
                "Filter": {},
                "Status": "Enabled",
                "NoncurrentVersionExpiration": {"NoncurrentDays": noncurrent_days},
            }
        ]
    }
    client.put_bucket_lifecycle_configuration(Bucket=bucket, LifecycleConfiguration=lifecycle)
    versioning = client.get_bucket_versioning(Bucket=bucket)
    try:
        lock = client.get_object_lock_configuration(Bucket=bucket)["ObjectLockConfiguration"]
    except client.exceptions.ClientError:
        lock = {"ObjectLockEnabled": "Disabled"}
    report = {
        "bucket": bucket,
        "versioning": versioning.get("Status"),
        "lifecycle_noncurrent_days": noncurrent_days,
        "object_lock": lock.get("ObjectLockEnabled", "Disabled"),
    }
    if report["versioning"] != "Enabled":
        print(json.dumps(report), file=sys.stderr)
        raise SystemExit("FAIL: bucket versioning could not be enabled")
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--endpoint", required=True)
    parser.add_argument("--bucket", required=True)
    parser.add_argument("--access-key", default="autonoesis")
    parser.add_argument("--secret-key", default="autonoesis-local-only")
    parser.add_argument("--noncurrent-days", type=int, default=90)
    args = parser.parse_args()
    report = configure(
        args.endpoint, args.bucket, args.access_key, args.secret_key, args.noncurrent_days
    )
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
