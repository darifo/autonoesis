#!/usr/bin/env bash
# Configure evidence bucket replication (P2-02): the source evidence bucket
# (versioned + object-lock) replicates to a lock-enabled replica bucket so
# authoritative evidence survives bucket/zone loss. Requires the MinIO/S3
# `mc` binary (set MC_BIN or rely on PATH).
#
# Usage: configure_object_replication.sh <endpoint> <access-key> <secret-key> <source> <replica>
set -euo pipefail

ENDPOINT="${1:?endpoint}"
ACCESS_KEY="${2:?access key}"
SECRET_KEY="${3:?secret key}"
SOURCE="${4:?source bucket}"
REPLICA="${5:?replica bucket}"
MC_BIN="${MC_BIN:-mc}"

ALIAS=autonoesis-replication-setup
"$MC_BIN" alias set "$ALIAS" "$ENDPOINT" "$ACCESS_KEY" "$SECRET_KEY" >/dev/null

# The replica must be versioned AND object-lock enabled (evidence policy).
if ! "$MC_BIN" ls "$ALIAS" >/dev/null 2>&1; then
  echo "FAIL: cannot reach $ENDPOINT" >&2; exit 1
fi
if ! "$MC_BIN" stat "$ALIAS/$REPLICA" >/dev/null 2>&1; then
  python3 - "$ENDPOINT" "$ACCESS_KEY" "$SECRET_KEY" "$REPLICA" <<'PY'
import sys

import boto3

endpoint, access, secret, bucket = sys.argv[1:5]
client = boto3.client(
    "s3",
    endpoint_url=endpoint,
    aws_access_key_id=access,
    aws_secret_access_key=secret,
    region_name="us-east-1",
)
client.create_bucket(Bucket=bucket, ObjectLockEnabledForBucket=True)
print(f"created object-lock replica bucket {bucket}")
PY
fi
"$MC_BIN" version enable "$ALIAS/$REPLICA" >/dev/null 2>&1 || true

# Replace any dangling rule from a previous partial setup.
"$MC_BIN" replicate rm "$ALIAS/$SOURCE" --all --force >/dev/null 2>&1 || true
"$MC_BIN" replicate add "$ALIAS/$SOURCE" --remote-bucket "$ALIAS/$REPLICA" >/dev/null

# Verify propagation with a probe object.
PROBE="replication-probe/$(uuidgen).json"
python3 - "$ENDPOINT" "$ACCESS_KEY" "$SECRET_KEY" "$SOURCE" "$PROBE" <<'PY'
import sys

import boto3

endpoint, access, secret, bucket, key = sys.argv[1:6]
client = boto3.client(
    "s3",
    endpoint_url=endpoint,
    aws_access_key_id=access,
    aws_secret_access_key=secret,
    region_name="us-east-1",
)
client.put_object(Bucket=bucket, Key=key, Body=b"replication-probe")
PY
for _ in $(seq 1 20); do
  if "$MC_BIN" stat "$ALIAS/$REPLICA/$PROBE" >/dev/null 2>&1; then
    echo "ok: replication verified ($SOURCE -> $REPLICA, probe $PROBE)"
    exit 0
  fi
  sleep 1
done
echo "FAIL: probe object never appeared in $REPLICA" >&2
exit 1
