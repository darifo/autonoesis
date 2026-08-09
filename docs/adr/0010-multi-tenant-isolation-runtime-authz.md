# ADR-0010: Multi-Dimensional Tenant Isolation and Execution-Time Authorization

- Status: accepted
- Date: 2026-08-09

## Context

A multi-tenant agent platform must prevent data leakage, privilege escalation, and resource contention across tenants. Adding a `tenant_id` column to database tables is not sufficient—isolation must span identity, data, credentials, runtime, network, budget, and release dimensions.

## Decision

Multi-tenant isolation is evaluated and enforced across all of these dimensions:

- Identity and delegation: OIDC tenant context, per-tenant principal and role mapping.
- Core data: PostgreSQL Row-Level Security (RLS) on all tenant-scoped tables.
- Object Store: Tenant-prefixed paths, per-tenant buckets or access policies.
- Search/Vector: Tenant-filtered indices and retrieval projections.
- Cache: Per-tenant cache namespaces or key prefixes.
- Model/Tool credentials: Tenant-specific credential brokering; credentials never shared.
- Egress network: Tenant-specific egress policies and allowlists.
- Workflow Namespace, Queue, Worker Pool: Tenant-scoped or isolated as needed.
- Sandbox and Workspace: Per-tenant resource quotas and filesystem isolation.
- Budget, quota, rate limits: Hierarchical from Tenant → Capability → Goal → Run.
- Logs, Traces, Evaluation Datasets, Memory: Tenant-filtered.
- Audit exports: Per-tenant audit trails.
- Capability Stable Channel and release policies: Per-tenant capability enablement.

Authorization is execution-time: identity, delegation scope, policy version, and Action parameters are re-checked at the Tool Gateway for every external side effect. An upstream approval does not substitute for execution-time re-authorization.

## Consequences

- Every storage, caching, retrieval, and execution component must implement tenant filtering.
- Performance impact of RLS and tenant-prefixed operations must be measured.
- Tenant-level Kill Switch must disable all activity while preserving audit trail.
- Cross-tenant access attempts must be denied and logged without revealing object existence.

## Verification

- Cross-tenant tests cover: API, database, object store, search, workflow, and telemetry layers.
- Tenant isolation tests verify 404 (not 403) for non-existent and cross-tenant objects.
- Execution-time re-authorization tests confirm policy changes take effect without restart.
