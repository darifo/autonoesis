# ADR 0033: Deterministic Auditable Canary Traffic Allocation

- Status: Accepted
- Date: 2026-09-09

## Context

Canary promotion previously only moved Deployment state. Nothing recorded how live requests
split between the Stable baseline and the Candidate, so the P1-05 requirement — "Canary uses
stable, auditable traffic allocation rules" — had no mechanism: an operator could neither
reproduce which version served a request nor prove the split was bounded.

## Decision

1. A `TrafficAllocation` value object (domain) carries a caller-chosen `salt` and a
   `candidate_percent` in 1..100. Assignment hashes `canary:{salt}:{request_id}` with SHA-256
   and maps the first eight digest bytes to a 0.01-percentile bucket; the request serves the
   Candidate iff the bucket is below `candidate_percent`. The salt is an audit input, not a
   secret.
2. `Deployment.enter_canary` is the only way into `CANARY` and requires the rule; the rule is
   persisted inside the Deployment's authoritative definition JSON alongside its transition
   history (the same pattern ADR-0030 used for Run→Deployment binding, so no migration is
   needed). Transitioning away from Canary keeps the rule for audit.
3. `Deployment.assign_request` fails closed: only a Canary deployment carrying a rule assigns;
   legacy rule-less rows and non-Canary states raise instead of defaulting to Stable.
4. The Application layer exposes `promote_to_canary(identity, deployment, allocation)` —
   rejecting principals that generated, graded, or approved the Candidate — and
   `resolve_request_route`, which replays the persisted rule to explain any request's route.
5. The API accepts the rule on Canary entry and exposes
   `GET /v1/deployments/{id}/route?request_id=…` so operators can verify determinism against
   the persisted rule.

## Consequences

- Assignment is stable across retries and replays: the same request id always serves the same
  version while that Deployment is in Canary, and the split is verifiable from persisted state.
- Percent selection remains statistical, not exact: a 10% rule approximates 10% over many
  requests; guardrail counters (ADR-0029) measure the realized split.
- Binding live Goal/Run creation to the resolved route, weighted stages, and per-tenant
  default rules remain future work; today the rule governs dispatch-time resolution and audit.
