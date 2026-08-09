# Context & Memory Threat Model

> Status: baseline · Last reviewed: 2026-08-09

## Scope

Context and Memory subsystems control what information agents can access (Context Assembly) and what information persists across runs (Memory). Compromise leads to data leakage, injection, poisoning, and privilege escalation.

## Assets

- Context Snapshot contents (Environment Facts, Knowledge, Memory, History)
- Memory Records (long-term learned information)
- Retrieval indices (search/vector projections)
- Context Assembly Pipeline integrity
- Memory Write Gate integrity

## Threats

### CM-001: Retrieval-Based Prompt Injection

**Description**: Malicious content in retrieved documents, knowledge bases, or memory records injects instructions that override agent behavior.

**Controls**:
- All retrieved content tagged with provenance and trust level.
- System instructions vs. retrieved content clearly separated in prompt structure.
- Retrieved content never treated as executable instruction.
- Model output validated as structured proposal before any state change.
- Content classification and trust scoring applied during Context Assembly.

### CM-002: Cross-Tenant Context Leakage

**Description**: Context Assembly retrieves data from another tenant's knowledge, memory, or environment facts.

**Controls**:
- Tenant context propagated through entire retrieval pipeline.
- Row-level filtering on all retrieval sources (DB RLS, vector index tenant filter).
- Context Snapshot records tenant_id and is verified against request tenant.

### CM-003: Memory Poisoning via Repeated Injection

**Description**: Attacker repeatedly submits interactions that create false memory patterns, degrading future agent decisions.

**Controls**:
- Memory Write Gate requires provenance, confidence, and recurrence checks.
- Low-confidence or single-occurrence observations do not enter Stable Memory.
- Conflict detection: new memory that contradicts existing memory triggers review.
- Human or policy approval before Stable Memory promotion.
- Memory records have TTL and automatic expiry.

### CM-004: Stale Context Leading to Wrong Decisions

**Description**: Agent acts on expired environment facts (prices, inventory, permissions, personnel) without refresh.

**Controls**:
- Environment Facts carry `valid_until` timestamps.
- Context Assembly checks freshness before inclusion.
- Long-running tasks must refresh specified Fact types before execution.
- Stale Fact triggers Replan rather than continuing with invalid assumptions.

### CM-005: Context Over-Privilege

**Description**: Agent receives more context than necessary for its task, increasing injection surface and data exposure.

**Controls**:
- Data minimization: Context Assembly retrieves only what the task requires and the identity is authorized to see.
- Token budget allocation limits total context size.
- Compression with source links preserves references without full content inclusion.
- Audit records what context was provided for each decision.

### CM-006: Memory Deletion Evasion

**Description**: Data subject requests deletion, but copies persist in memory records, retrieval indices, or cached snapshots.

**Controls**:
- Deletion request propagates to: Memory Ledger (hard delete or tombstone), Search/Vector indices (re-index), Context Snapshots (mark invalid, do not serve), Analysis projections (remove or anonymize).
- Minimum audit proof of deletion retained per compliance requirements.
- Regular deletion propagation verification.
