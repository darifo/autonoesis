# Security Policy

Autonoesis hosts high-autonomy automation. By default, prompts, retrieved content, tool output, remote agents, and external callbacks are **all untrusted**.

## Vulnerability Reporting

If you discover a suspected vulnerability, do **not** create a public Issue. Use this repository's GitHub private vulnerability reporting. If that feature is unavailable, contact the repository owner through a private channel before disclosing details.

Reports should include: affected component, impact, reproduction steps, required permissions, and known mitigations. Do not include real customer data or still-valid credentials.

## Baseline Guarantees

- Use least-privilege credentials with explicit audience and short lifetimes.
- Enforce tenant isolation and authorization at every data and tool boundary.
- Re-authorize at side-effect execution time—upstream checks do not substitute execution-time checks.
- Audit records and evidence references are append-only and immutable.
- Write operations carry stable idempotency keys. Unknown results trigger reconciliation, not blind retry.
- Evaluations run inside sandboxes with controlled egress.
- Human approval, pause, takeover, rollback, and Kill Switch paths exist for every governed boundary.
- Evolution proceeds only through the Candidate pipeline. Direct modification of production versions is prohibited.

## Defense-in-Depth Layers

| Layer | Controls |
|---|---|
| **Entry** | OIDC/mTLS, tenant context, schema validation, rate limiting, content size limits |
| **Data** | Classification labels, data minimization, row/column/object ACLs, regional storage, encryption, retention |
| **Context** | Provenance tags, instruction/data separation, injection detection, conflict signaling |
| **Runtime** | Sandbox isolation, read-only filesystem, resource quotas, unprivileged execution, network egress controls |
| **Tool** | Identity verification, delegation check, policy decision, risk classification, approval, idempotency, credential brokering |
| **Outcome** | Authoritative readback, Evidence integrity verification, immutable storage |
| **Evolution** | Data partitioning, independent grader, release approval, Shadow/Canary, automatic rollback |
| **Supply Chain** | Code signing, SBOM, provenance attestation, vulnerability scanning, allowlists, immutable artifacts |

## Agentic Threat Model Baseline

| Threat | Primary Control |
|---|---|
| Prompt Injection / Indirect Injection | External content treated as untrusted; models hold no permissions; re-authorize at Action execution |
| Tool Confusion / Excessive Agency | Capability ceiling separated from actual permissions; minimum Tool Scope; risk classification |
| Cross-tenant Leakage | Request context, repository filtering, DB RLS, object storage path, vector index multi-layer isolation |
| Credential Exfiltration | Short-lived credential broker; credentials forbidden in Prompt/Log/Artifact; egress allowlist |
| Duplicate Side Effect | Stable idempotency keys, execution records, external idempotency support, reconciliation |
| Approval Substitution | Approval bound to Action digest, policy version, and expiry; re-verify at execution time |
| Memory Poisoning | Candidate staging area, provenance tracking, conflict detection, TTL, independent review, deletion propagation |
| Evaluation Gaming | Hidden test cases, data partitioning, Outcome-first verification, independent grader, blind evaluation, anti-contamination |
| Candidate Supply-chain Attack | Code signing, SBOM, reproducible builds, isolated evaluation, explicit release gates |
| Audit Tampering | Append-only records, digest chain, WORM export, separation of duties |
| Denial of Wallet / Resource Exhaustion | Multi-level budgets, quotas, concurrency limits, max depth, circuit breakers, Kill Switch |

## Multi-Dimensional Tenant Isolation

Multi-tenancy is more than adding `tenant_id` to database tables. Isolation must be evaluated across:

- Identity and delegation contexts
- Core data, Object Store, Search/Vector, and Cache storage
- Model/Tool credentials and egress network
- Workflow Namespace, Queue, Worker Pool, Sandbox, and Workspace
- Budget, quota, rate limits, and blast radius
- Logs, Traces, Evaluation Datasets, Memory, and audit exports
- Capability Stable Channel and release policies

## Supported Versions

Supported version ranges and vulnerability disclosure timelines will be published before the first public production release.
