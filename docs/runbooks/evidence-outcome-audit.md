# Runbook: Evidence, Outcome, Audit, and Deletion Recovery

> Status: implemented baseline · Last reviewed: 2026-08-11

## Required wiring

Evidence capture requires PostgreSQL authority, a versioned S3-compatible bucket created with
Object Lock enabled, server-side encryption backed by KMS, and a configured authoritative readback
endpoint. Production endpoints must use TLS and bind to an expected service identity. Never accept
an artifact bucket, readback URL, verifier status, or source identity from a request body.

The known KMS key in Compose/CI is test-only. Production deployment must inject a separately
managed key and verify that `PutObject` returns SSE, COMPLIANCE retention, and a Version ID.

## Capture and recovery

| State | Meaning | Operator action |
|---|---|---|
| Saga `pending`, artifact missing | Object write did not complete | Restore Object Store and retry the same idempotency key/source |
| Saga `pending`, artifact present | Process failed after object write | Retry; the use case verifies bytes and commits metadata without re-reading authority |
| Saga `committed` | Evidence metadata, Audit, Outbox and idempotency committed | Verify artifact Version ID and digest if Outcome is blocked |
| Outcome `unknown` | Evidence is missing/stale/untrusted, bytes changed, or authority is unavailable | Repair authority/readback and capture new Evidence; never edit the old record |
| Deletion `retention_blocked` | Compliance retention still applies | Keep tombstone; retry only after retained-until |
| Deletion `deleted` | Artifact version removed with proof | Preserve Evidence metadata, Outcome relation, tombstone and Audit chain |

## Incident procedure

1. Activate the narrowest Kill Switch if false Outcome verification could trigger further writes.
2. Resolve Tenant, Run, Action, Evidence ID, Saga, artifact URI/Version ID, Outcome, Audit sequence
   and correlation ID.
3. Fetch the exact object version and recompute SHA-256. A mismatch is a security incident; do not
   replace metadata or upload bytes under the existing content-addressed key.
4. Re-run the configured authoritative readback and compare source identity, reference, canonical
   state and validity interval. A Tool receipt or model statement is not authoritative evidence.
5. Verify the per-Tenant Audit chain from sequence 1. Preserve the first mismatching event and all
   database/object versions for investigation.
6. For deletion, confirm the tombstone was committed before attempting object removal. Record the
   provider Version ID and proof digest after success.

## Alerts

- old pending Evidence capture Sagas;
- artifact digest/version/SSE/Object Lock mismatch;
- Outcome verification returning `unknown` or an unavailable readback source;
- deletion requests past retained-until without a proof;
- Audit sequence gaps, duplicate sequence/digest, or chain mismatch;
- API responses that contain a non-null Audit Ref not present in PostgreSQL.
