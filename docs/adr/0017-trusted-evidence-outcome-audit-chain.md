# ADR-0017: Require Immutable Evidence and Independent Outcome Verification

- Status: accepted
- Date: 2026-08-11
- Supersedes: the implementation assumptions in ADR-0002 and ADR-0014

## Context

Evidence metadata was durable, but artifact bytes were held only by an in-memory object-store fake.
Classification and secret detection happened after the write, object keys had no Tenant prefix, and
there was no version, encryption, retention, or object-lock proof. `VerifyOutcome` accepted a
caller-provided status and verifier version, so a caller could self-certify a Tool receipt. Audit
rows were append-oriented but had no tamper-evident sequence, and API errors returned fictional
`audit://` references that did not resolve to committed events.

## Decision

- `EvidenceAdmissionPolicy` scans size, classification, PII, secrets, and Goal retention policy
  before any object write. Detected secrets are rejected; classification cannot exceed the Goal
  data policy.
- Evidence artifacts use a deterministic
  `tenants/{tenant}/evidence/{evidence}/{sha256}` S3 key. The adapter requires SSE-S3, bucket
  versioning, a returned Version ID, and COMPLIANCE Object Lock until the retained-until timestamp.
  Reads use the recorded version and verify SHA-256 bytes before returning content.
- A deterministic Evidence ID and PostgreSQL `evidence_capture_sagas` row are committed before the
  external object write. The content-addressed write is idempotent. If metadata commit fails after
  the object succeeds, the next invocation reloads the pending Saga, verifies the object, and
  completes Evidence metadata, Audit, Outbox, and command idempotency in one transaction.
- Evidence records carry the artifact digest/version, configured source identity, external source
  reference, Action, Run, Subject references, capture/validity interval, classification, retention,
  and integrity status.
- Tool receipts always produce `unverified` Evidence. `VerifyOutcome` no longer accepts a status,
  verifier identity, or verification time from its caller. `TrustedOutcomeVerifier` requires fresh
  authoritative-readback Evidence, verifies immutable artifact bytes, re-reads the configured
  authority, compares source identity/reference/state/digest, and then decides
  `verified | not_met | unknown` against the Goal Success Criterion.
- HTTP readback endpoints are registered by server configuration. Arbitrary caller URLs are
  rejected; non-loopback endpoints require TLS and are bound to an expected source identity.
- Every newly committed AuditEvent receives a per-Tenant monotonic sequence and SHA-256 chain under
  a PostgreSQL transaction advisory lock. Application roles retain INSERT but not UPDATE/DELETE.
  Outbox events include the committed Audit Ref and digest.
- Deletion never removes Evidence metadata or Outcome relationships. It writes a tombstone and
  Outbox event first; object retention may block deletion. A completed deletion stores provider
  Version ID, timestamp, and a SHA-256 deletion proof.
- Error responses with no committed AuditEvent return a null `audit_ref`. Only committed chained
  events expose `audit://events/{event_id}?digest=...`.

## Consequences

- Local and CI MinIO require an explicit test KMS key. Production must use an independently managed
  KMS; the repository's known local key is not a production credential.
- Compliance Object Lock intentionally prevents immediate erasure. Data-subject deletion remains a
  durable pending/retention-blocked tombstone until policy permits artifact removal.
- Upgraded installations may contain legacy Audit rows without chain fields. They cannot pass
  `verify_audit_chain`; export or migration policy must preserve and separately label them.
- Object Store availability can delay Evidence completion, but it cannot cause an unverified
  Outcome to become Verified.

## Verification

- Unit/security tests cover pre-write secret/classification rejection, content mismatch, tampering,
  stale/missing/untrusted Evidence, Tool-receipt rejection, recoverable metadata failure, HTTP source
  allowlisting, audit-detail tampering, retention blocking, and deletion proofs.
- A real MinIO component test verifies SSE-S3, Version ID, Tenant prefix, COMPLIANCE Object Lock,
  digest readback, retention rejection, and proof-bearing deletion.
- A PostgreSQL 17 + MinIO component test verifies `0001` → `0005`, durable Saga recovery state,
  independently reloaded Evidence/Outcome, deletion tombstone, real Audit Ref, and an intact digest
  chain during concurrent appends from two Store instances.
