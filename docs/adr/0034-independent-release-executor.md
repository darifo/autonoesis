# ADR 0034: Independent Release Executor Owns Release and Rollback

- Status: Accepted
- Date: 2026-09-09

## Context

Canary entry, Stable promotion, and release rollback were executed synchronously inside API
request handlers. The P1-05 requirement — "promotion and rollback are both executed through an
independent Release Executor" — was unmet: a request path could mutate release state directly,
transitions were not durable, and the executing principal was the API caller rather than a
dedicated executor duty. Additionally, the worker's grader and promoter activities shared the
zero principal, so the domain's separation-of-duties gate (ADR-0020/0025) correctly refused
promotion in the real Temporal lifecycle flow.

## Decision

1. A dedicated `ReleaseExecutionWorkflow` (Temporal) is the only executor of release
   transitions. Its single activity `execute_release_command` accepts exactly three actions —
   `enter_canary`, `release_stable`, `rollback_release` — and applies them through the
   Application service under a deterministic per-tenant release-executor principal
   (`uuid5(zero, "release-executor:{tenant}")`), distinct from the grader principal
   (`uuid5(zero, "grader:{tenant}")`). Unknown actions fail non-retryably.
2. The activity runs with no retries: the Deployment state machine is the idempotency fence —
   a replayed command either finds the transition already applied or fails, matching
   `promote_candidate`.
3. The API endpoints for Canary entry, Stable promotion, and release rollback no longer call
   the Application service. They pre-check authoritative state (Shadow/Canary/active release,
   returning 409/404), then dispatch the command to the executor and return 202 with the
   Workflow id. Without a configured dispatcher they fail closed with 503.
4. `TemporalReleaseCommandDispatcher` derives a tenant-prefixed, action-scoped Workflow id from
   the canonical-JSON command digest (`TenantNamespaces.release_workflow_id`), routes through
   the tenant high-risk Namespace/Task Queue, and starts with `USE_EXISTING` +
   `REJECT_DUPLICATE`, mirroring ADR-0032: an identical retried command never executes twice.
5. Shadow request dispatch (ADR-0032) and this executor are separate surfaces: shadow pairs are
   per-request mirrors; release commands are per-transition governance.

## Consequences

- Release state can no longer be mutated from a synchronous request path; every transition is
  durable, independently identified, and replayable from Workflow history plus PostgreSQL.
- Responses are dispatch acknowledgements, not transition results; callers observe outcomes via
  deployment/release reads. The frozen OpenAPI contract reflects the new 202 shapes.
- A PostgreSQL outbox for release commands with crash reconciliation, kill-switch integration
  in the executor, and automatic guardrail-driven dispatch remain future hardening.
