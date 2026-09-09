# ADR 0032: Tenant-Isolated Shadow Request Dispatch

- Status: Accepted
- Date: 2026-08-25

## Context

ADR-0031 introduced the per-request Shadow Workflow and comparison evidence, but no control-plane
entry point could dispatch live mirrored inputs. Dispatch must not cross tenant Worker pools, leak
raw input into identifiers, or create duplicate Stable execution when a client retries.

## Decision

1. The API exposes `POST /v1/deployments/{id}/shadow-requests` to principals with the
   `release_executor` or `shadow_dispatcher` role. It reloads the tenant-authoritative Deployment and
   rejects requests unless the Deployment is currently in Shadow.
2. Each request carries a caller-generated UUID and JSON input. The dispatcher canonicalizes the
   JSON and hashes it; the request reference and Workflow ID contain the UUID and digest, never the
   raw input.
3. `TenantNamespaces.shadow_workflow_id` derives a tenant-prefixed, Deployment-scoped identifier.
   Shadow Workflows always use the tenant's high-risk Temporal Namespace and Task Queue when tenant
   isolation is enabled.
4. Exact retries use Temporal `USE_EXISTING` with completed-ID reuse rejected. The API returns the
   deterministic existing ID for both running and completed duplicates, never re-executing Stable.
5. Missing dispatch configuration returns 503. Missing Worker Shadow Runtime remains a
   non-retryable Activity failure; neither layer fabricates a comparison.

## Consequences

- Live callers now have a deterministic route into `ShadowPairWorkflow` with tenant and Deployment
  boundaries visible in the Workflow ID.
- The input Payload remains in encrypted Temporal history and must follow the same classification,
  retention, and access policy as its Stable request; it is not copied into identifiers.
- Dispatch is synchronous with Temporal acceptance. A PostgreSQL outbox for Shadow requests and
  crash reconciliation remain future hardening if upstream callers cannot retry 5xx responses.
- A production Shadow Runtime and Candidate sandbox are still required before live dual-run can be
  enabled safely.
