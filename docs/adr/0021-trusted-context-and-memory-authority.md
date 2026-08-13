# ADR-0021: Trusted Context Assembly and Memory Authority

- Status: accepted
- Date: 2026-08-13
- Extends: ADR-0007, ADR-0013, ADR-0017, ADR-0019

## Context

Environment Facts carried source and time but not Tenant, source authority, classification, or a
fact-owned freshness policy. Context ACL was a permissive placeholder, Snapshot persistence hashed
the serialization timestamp, conflict detection and compression were stubs, and Memory could be
inserted directly without proving it passed PII, provenance, conflict, confidence, TTL, and
approval checks. Its ledger was process-local and vector deletion was not tied to authority.

## Decision

Environment Facts and Knowledge references are Tenant-scoped and carry classification, trust,
source authority, freshness, role, purpose, Subject-row, and visible-field constraints. Context
assembly evaluates those constraints before inclusion. Prompt-injection markers downgrade content
to `UNTRUSTED`; the content remains citable data and the immutable security boundary explicitly
denies it instruction authority.

`ContextSnapshot.content_digest` is canonical and excludes copy-specific Snapshot ID and creation
time. It covers content, source/version, policy version, trust, freshness, ACL, conflict signals,
history, Memory IDs, security boundaries, and exact Tool versions. The same inputs reproduce the
same digest. Conflict detection emits explicit stable signals. Compression may truncate values but
must preserve source, citation, trust, classification, and security boundaries.

Memory starts as `PROPOSED`. Stable stores reject it until `MemoryWriteService` applies the Write
Gate and promotes it to `STABLE`. The gate rejects insufficient confidence, untrusted provenance,
expired TTL, unresolved conflicts, and PII/restricted content without a privacy reviewer or data
steward. Revision `0008_trusted_context` persists Environment Facts, append-only Memory Ledger,
deletion edges, and vector projections under forced RLS.

Deletion follows the authoritative edge graph in one transaction, tombstones every affected
Memory, appends deletion ledger entries, and removes vector projections. The vector index contains
only digest-bearing disposable projections and can be rebuilt from stable Memory; it is never a
business-state authority.

## Verification

Context tests cover cross-tenant filtering, all ACL dimensions, prompt injection, conflicts,
compression boundaries, and reproducible/sensitive digests. Memory tests prove a Run observation
cannot enter a stable store directly and exercise PII, provenance, conflict, confidence, TTL, and
approval decisions. `tests/security/test_trusted_context_memory_authority.py` verifies the Ledger,
recursive deletion, and vector cleanup on a real PostgreSQL schema migrated from `0001` to `0008`.

Production source connectors, enterprise DLP/classification engines, large-scale vector rebuilds,
and data-subject deletion drills remain deployment acceptance work.
