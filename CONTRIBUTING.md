# Contributing to Autonoesis

Autonoesis is in early development with an architecture-first approach. Changes should be small, reviewable, and respect domain boundaries and data authority boundaries.

## Development Process

1. Read [AGENTS.md](AGENTS.md) and the relevant [ADR](docs/adr/README.md).
2. Create or reference an Issue with a clear expected outcome and acceptance evidence.
3. Create a single-responsibility branch.
4. Write or update tests alongside implementation.
5. Run `task check` (which runs `lint`, `typecheck`, and `test`).
6. When behavior changes, synchronously update contracts, ADRs, threat models, or runbooks.
7. Submit a Pull Request using the repository template.

## Capability Claims

- Use only `specified`, `modeled`, `unit-tested`, `integrated`, and `production-proven`.
- Any `integrated` claim must link to a real-component CI job or an archived drill report.
- Any `production-proven` claim must additionally link failure, concurrency, security, and operations acceptance evidence.
- Update the claim and evidence in the same change when a gate is removed or a runtime path changes.
- Run `task baseline` to ensure README, Cockpit, version inventories, and the maturity matrix remain aligned.

## Commit Messages

Use clear imperative mood titles. Conventional Commits prefixes are recommended:

```text
feat(domain): add explicit run cancellation transition
fix(runtime): preserve idempotency key across activity retry
docs(adr): record tool gateway authorization boundary
```

## Architecture Compliance Checklist

Before submitting a PR that touches cross-boundary concerns, verify:

### Semantic & Boundary

- [ ] External business objects vs. platform run objects are not conflated.
- [ ] Every core state type has a single authoritative writer.
- [ ] Goal, Run, Task, Action, Artifact, Evidence, and Outcome are not conflated.
- [ ] Model output becomes a structured Proposal/Command before any state change.

### Execution & Recovery

- [ ] Long tasks survive process exit (durable workflow replay).
- [ ] Retry, re-plan, compensation, takeover, and cancellation are semantically distinct.
- [ ] Action Unknown has a reconciliation path (no blind retry of writes).
- [ ] Every Agent Loop has fixed version, tool scope, and resource caps.

### Governance & Security

- [ ] Tool visibility and actual authorization are separate.
- [ ] Approval binds exact parameters, policy version, and expiry.
- [ ] Credentials are short-lived, injected at call time, and never in Prompt/Log/Artifact.
- [ ] Tenants are isolated across DB, Object, Search, Runtime, Credential, and Telemetry.
- [ ] Kill Switch exists per Tenant/Agent/Tool/Operation/Provider.

### Outcome, Evaluation & Evolution

- [ ] Verified Outcome references independent Evidence.
- [ ] Evaluation fixes version, environment, budget, and dataset.
- [ ] Generation, grading, approval, and release are separated by role.
- [ ] Candidates have safety regression, Shadow/Canary, observation window, and rollback.

## Compatibility

- Adding optional fields to contracts is typically backward-compatible.
- Deleting, renaming, adding required fields, or changing semantics requires a new major version.
- Published events are immutable facts. Do not change the meaning of an existing event type in-place.

## Testing Expectations

| Layer | Must Test |
|---|---|
| Domain Unit | Invariants, invalid inputs, state transitions, risk/digest computation |
| Application | Transaction boundaries, optimistic conflicts, outbox, idempotency, rejection paths |
| Contract | Schema compatibility, provider adapters, consumer contracts, error semantics |
| Workflow Replay | Determinism, Timer/Signal, Worker restart, cancellation, timeout, recovery |
| Integration | DB RLS, OIDC, OPA, Object Store, Event Bus, Model/Tool adapters |
| Security | Prompt injection, SSRF, credential leakage, cross-tenant, approval tampering, resource exhaustion |
| Evaluation | Success, regression, edge, attack, indeterminate, cost, and memory growth |
| End-to-End | Goal → Evidence/Outcome, and Candidate → Rollback complete chains |
| Resilience | Provider failure, DB failure, duplicate messages, Action Unknown, disaster recovery |

## Security-Sensitive Changes

Changes to identity, delegation, policy, approval, keys, sandbox, egress access, audit, tenant isolation, release gates, or data retention rules must:

- Explicitly update threat models in `docs/threat-models/`.
- Receive independent security review.
- Include negative-path tests for the modified boundary.

## Dependency Direction Rules

```
apps → application → domain
apps → adapters → application ports / runtime contracts
application → domain + contracts + capability
runtime-kernel → domain + contracts
domain ↛ FastAPI / Temporal / provider SDK / ORM / database
core ↛ examples
```

Cross-boundary dependency changes require an ADR and an architecture dependency test.

## Definition of Done

A change is complete when:

- Formatting, lint, type-check, unit, and contract tests pass.
- New state transitions, idempotency, authorization, recovery, and negative paths have tests.
- ADRs, architecture diagrams, contracts, or threat models are updated when boundaries change.
- Repeatable acceptance evidence exists—"looks right locally" is not sufficient.
- New telemetry does not leak sensitive data and can be correlated to Goal/Run/Action.
- Data migrations have a compatibility period, rollback, or forward-fix plan.
- Operational impact is recorded in Runbooks, SLOs, monitoring, and alerts.
