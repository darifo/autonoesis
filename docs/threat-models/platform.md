# Platform Threat Model

> Status: baseline · Last reviewed: 2026-08-09

## Protected Assets

| Asset | Impact of Compromise |
|---|---|
| Tenant data & isolation | Cross-tenant data leakage; regulatory violation |
| Identity & delegation | Unauthorized actions; privilege escalation |
| Approval records | Bypassed governance; unaccountable side effects |
| Tool credentials & network permissions | Lateral movement; data exfiltration |
| Run/Action/Outcome authoritative state | Corrupted execution history; false outcomes |
| Context/Memory/Evidence | Poisoned retrieval; fabricated evidence |
| Candidate/Stable versions | Supply chain compromise; rogue capability deployment |
| Audit trail | Tampered evidence; compliance failure |
| Kill Switch | Inability to stop malicious or runaway agents |

## Trust Boundaries

| Boundary | Trust Level |
|---|---|
| End users / API clients | Untrusted—authenticated but not trusted for authorization claims |
| Retrieved content (documents, web, tools) | Untrusted—may contain injection payloads |
| Model providers | Untrusted—models may hallucinate or be adversarially influenced |
| Harness Sandbox | Semi-trusted—models run here with resource limits |
| MCP/A2A remote agents | Untrusted—external agents may be compromised or malicious |
| Enterprise tools & callbacks | Semi-trusted—authenticated but subject to business logic errors |
| Memory/Vector services | Semi-trusted—may be poisoned via retrieval or write paths |
| CI/CD & Capability Pack supply chain | Semi-trusted—requires signing and verification |
| Platform infrastructure (DB, Workflow, Object Store) | Trusted—core infrastructure with access controls |

## Threat Catalog

### T-001: Prompt Injection / Indirect Injection

**Description**: Attacker injects instructions through user input, retrieved documents, tool output, or external agent messages that cause the model to bypass controls, disclose data, or execute unauthorized actions.

**Controls**:
- External content always treated as untrusted data, never as instructions.
- Model output is a structured proposal—cannot directly mutate authoritative state.
- Action execution re-authorizes at the Tool Gateway regardless of model output.
- Source separation: system instructions vs. retrieved content vs. user input clearly delimited.
- Content classification labels on all retrieved data.

### T-002: Cross-Tenant Data Leakage

**Description**: One tenant accesses another tenant's goals, runs, evidence, memory, or evaluation data through API, database, search, or telemetry.

**Controls**:
- OIDC Tenant Context established at authentication boundary.
- Repository layer filters by tenant_id on all queries.
- PostgreSQL Row-Level Security (RLS) on all tenant-scoped tables.
- Object Store paths include tenant prefix.
- HTTP 404 for non-existent and cross-tenant objects (no existence disclosure).
- Telemetry and logs filtered by tenant context.

### T-003: Duplicate Side Effects

**Description**: Network retries, workflow replays, or message redelivery cause the same external write (payment, email, order) to execute multiple times.

**Controls**:
- Stable idempotency keys on every write Action.
- Persistent idempotency records in PostgreSQL.
- Tool Gateway deduplicates by idempotency_key before execution.
- External systems required to support idempotency where possible.

### T-004: Action Unknown (Timeout/Partial Failure)

**Description**: External system call times out or returns ambiguous result. Platform cannot determine whether the side effect occurred.

**Controls**:
- Action enters `Unknown` status.
- Blind retry of write operations is prohibited.
- Reconciliation Worker queries external system's authoritative state.
- On confirmation: transition to Succeeded or Failed.
- On persistent uncertainty: escalate to human operator with all available context.

### T-005: Model Declares Success Without Evidence

**Description**: Model generates a response claiming the goal is complete, but no verifiable evidence exists.

**Controls**:
- Outcome is an independent domain object, not derived from model output.
- Verified Outcome must reference at least one Evidence object.
- Evidence contains configured source identity, external reference, Subject, Action, immutable
  artifact Version ID/digest, validity, classification, retention and integrity information.
- Tool receipt (HTTP 200) is not sufficient proof of business outcome.
- Outcome status cannot be supplied by the caller; the verifier re-reads the configured authority
  and verifies the exact object version before deciding.
- Missing, stale, untrusted or digest-mismatched Evidence yields `unknown`, never Verified.

### T-006: Approval Parameter Substitution

**Description**: Action parameters are changed after approval but before execution, bypassing the governance check.

**Controls**:
- Approval binds to exact `argument_digest` (SHA-256 of canonical sorted parameters).
- Tool Gateway re-computes digest at execution time and compares with approval.
- Digest mismatch → execution rejected, re-approval required.
- Approval has expiry (`expires_at`).

### T-007: Memory Poisoning

**Description**: Malicious or low-quality observations are written to long-term memory, degrading future agent behavior.

**Controls**:
- Observations enter Memory Candidate staging, not directly into Stable Memory.
- Memory Write Gate: provenance check, PII/secret scan, classification scan, scope check, confidence check, conflict check.
- Human or policy approval required before promotion to Stable Memory.
- Memory records have TTL and support invalidation and deletion propagation.

### T-008: Self-Grading / Self-Approving Candidates

**Description**: The same component that generates a Candidate also evaluates or approves it, creating a self-validating improvement loop.

**Controls**:
- Candidate generator, grader, and approver must be distinct identities.
- `CandidateLifecycleService` enforces generator ≠ grader and generator ≠ approver at the application layer.
- Independent evaluation suites with fixed versions, environments, and datasets.
- Grader results allow `unknown` and `invalid` to prevent forcing indeterminate samples into pass/fail.

### T-009: Malicious Capability Pack

**Description**: A Capability Pack contains malicious code, declares excessive permissions, or introduces supply chain vulnerabilities.

**Controls**:
- Strict Manifest validation (exact fields, JSON Schema, version matching).
- Signature verification before installation.
- SBOM inclusion and verification.
- Source allowlist and dependency review.
- Tenant authorization check before installation.
- Sandbox execution for Pack Entry Points.
- Audit recording of all installations.

### T-010: Audit Tampering

**Description**: An attacker with platform access modifies or deletes audit records to hide unauthorized actions.

**Controls**:
- Append-only audit records in PostgreSQL.
- Per-Tenant monotonic sequence and SHA-256 chain serialized by a transaction advisory lock.
- Application roles can insert but cannot update/delete Audit rows; Outbox carries the committed
  Audit Ref and digest.
- Deletion preserves Evidence metadata, Outcome relations, a tombstone and proof.
- WORM (Write Once Read Many) storage export for compliance-critical environments.
- Separation of duties: audit access is role-gated, separate from operational access.

### T-011: Denial of Wallet / Resource Exhaustion

**Description**: Attacker or runaway agent exhausts budgets through excessive model calls, tool invocations, or sandbox usage.

**Controls**:
- Hierarchical budgets: Tenant → Capability → Goal → Run → Task/Action.
- Hard limits on model tokens, tool invocations, sandbox CPU/GPU/time.
- Concurrency limits, max agent depth, max fan-out.
- Circuit breakers on per-tenant, per-agent, per-tool, and per-provider dimensions.
- Kill Switch for immediate termination with audit trail.
