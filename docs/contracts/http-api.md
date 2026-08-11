# HTTP API Contracts

> Status: baseline · Last reviewed: 2026-08-09

## Common Envelope

Every cross-process command and event must carry a standard message envelope:

```yaml
message_id: uuid
correlation_id: uuid
causation_id: uuid | null
tenant_id: uuid
actor_id: uuid
principal_id: uuid | null
schema: string
schema_version: integer
created_at: rfc3339
occurred_at: rfc3339 | null
traceparent: string | null
classification: public | internal | confidential | restricted
retention_policy: string
idempotency_key: string | null
payload: object
```

## HTTP Rules

### Identity

- Tenant and identity must come from verified request context (OIDC JWT or development headers). Body claims are never accepted.
- Development mode supports `X-Tenant-ID`, `X-Actor-ID`, `X-Principal-ID`, `X-Roles` headers. Production uses OIDC-validated JWTs.

### Idempotency

- Write requests that may produce side effects must carry an `Idempotency-Key` header.
- Duplicate keys return the original response without re-executing the side effect.
- Idempotency keys are tenant-scoped.

### Optimistic Locking

- Updates must use optimistic version numbers or `If-Match` headers.
- Version conflicts return `409 Conflict` with current version.

### Asynchronous Operations

- Operations that involve durable workflows (Goal execution, Candidate evaluation) return a trackable resource reference (Goal, Run, Action).
- Do not pretend synchronous completion for asynchronous work.
- Clients poll or subscribe to SSE event streams for progress.

### Error Envelope

All errors use a standard nested envelope. `audit_ref` is null unless an error AuditEvent was
actually persisted; the API never fabricates an audit URI:

```json
{
  "error": {
    "code": "record_not_found",
    "message": "The requested resource was not found.",
    "retryable": false,
    "next_action": "verify the identifier and tenant scope",
    "correlation_id": "uuid",
    "audit_ref": null
  }
}
```

### Client Constraints

- Clients may submit Goal creation, approval decisions, and governance commands.
- Clients may not bypass the platform to mark Actions as executed.
- Clients may not declare Outcomes without Evidence references.

## Schema Compatibility

- Adding optional fields is typically backward-compatible.
- Deleting, renaming, adding required fields, or changing semantics requires a new major version.
- Published events are immutable facts—never change their meaning in place.
- Provider protocol versions are hidden from core domains by Adapters.
- OpenAPI is frozen from the FastAPI source into `docs/contracts/generated/openapi-v1.json`;
  CI rejects source/snapshot drift.
- Consumer contract tests and multi-version replay tests are part of CI.

## Resource Paths

| Method | Path | Description |
|---|---|---|
| `GET` | `/health/live` | Liveness check |
| `POST` | `/v1/capability-packs` | Install a capability pack |
| `GET` | `/v1/capability-packs` | List installed packs |
| `POST` | `/v1/agents` | Register an agent definition |
| `GET` | `/v1/agents` | List registered agents |
| `POST` | `/v1/skills` | Register a skill definition |
| `GET` | `/v1/skills` | List registered skills |
| `POST` | `/v1/tools` | Register a tool definition |
| `GET` | `/v1/tools` | List registered tools |
| `POST` | `/v1/policies` | Register a policy |
| `GET` | `/v1/policies` | List policies |
| `POST` | `/v1/budgets` | Create a budget |
| `GET` | `/v1/budgets` | List budgets |
| `POST` | `/v1/goals` | Create a goal (idempotent) |
| `GET` | `/v1/goals` | List goals |
| `GET` | `/v1/goals/{goal_id}` | Get goal details |
| `POST` | `/v1/goals/{goal_id}/runs` | Start a run |
| `GET` | `/v1/runs/{run_id}` | Get run status |
| `GET` | `/v1/runs/{run_id}/events` | SSE event stream for run |
| `POST` | `/v1/approvals/{approval_id}/decision` | Decide an approval |
| `GET` | `/v1/evidence` | List evidence |
| `GET` | `/v1/evaluation-suites` | List evaluation suites |
| `GET` | `/v1/trials` | List evaluation trials |
| `POST` | `/v1/improvement-proposals` | Create improvement proposal |
| `GET` | `/v1/improvement-proposals` | List proposals |
| `POST` | `/v1/candidates` | Create candidate |
| `POST` | `/v1/candidates/{id}/evaluate` | Submit evaluation |
| `POST` | `/v1/candidates/{id}/decision` | Approve/reject candidate |
| `POST` | `/v1/candidates/{id}/promote` | Start an approved candidate in Shadow |
| `POST` | `/v1/deployments/{id}/canary` | Promote a Shadow deployment to Canary |
| `POST` | `/v1/deployments/{id}/stable` | Promote a Canary deployment and create the Stable release |
| `POST` | `/v1/releases/{id}/rollback` | Rollback release |
| `GET` | `/v1/releases` | List releases |
| `GET` | `/v1/audit-events` | List audit events (role-gated) |
