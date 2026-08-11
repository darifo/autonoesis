# ADR-0015: Make Tool Execution an Atomic Governed Boundary

- Status: accepted
- Date: 2026-08-11
- Supersedes: the implementation assumptions in ADR-0005

## Context

The original Tool Gateway checked policy and approval, but charged an in-memory budget before an
independent in-memory idempotency lookup. Concurrent requests could therefore double-charge and
potentially execute twice. Tool identity, delegation, credential lifetime, server-owned risk,
egress, and ambiguous results were not enforced by one contract. Application authorization also
accepted a caller-provided `policy_allowed` boolean.

## Decision

- `GovernedToolGateway` is the mandatory runtime boundary for external effects. Production
  `GoalExecutionApplication` disables direct caller-asserted authorization and exposes
  `execute_governed_action` instead.
- The Gateway resolves an exact immutable Tool version, validates operation/resource/schema,
  derives risk from that server definition, evaluates live delegation and policy, checks the Kill
  Switch, verifies an exact unexpired Approval, obtains an opaque short-lived credential lease,
  and only then reserves execution.
- L4 is denied unless the Gateway is explicitly constructed with a separately reviewed override.
- PostgreSQL serializes the unique `(Tenant, Idempotency Key)` identity with a transaction-scoped
  advisory lock and binds it to the exact Tool version and request digest. The same transaction
  checks the Goal budget, inserts the idempotency record, and writes the uniquely referenced budget
  charge. A retry never charges twice.
- A reused key with a different canonical Action digest is a conflict. `pending`, `accepted`, and
  `unknown` are never automatically re-executed.
- Result semantics are `rejected | accepted | succeeded | failed | unknown`. `accepted` means only
  that the provider accepted work and therefore maps to an Unknown Action until reconciliation.
  Succeeded requires verifier confirmation.
- Application persists the resulting Action transition, immutable ActionAttempt, Evidence, Audit,
  Outbox event, and command idempotency fact. The database reservation remains recovery evidence
  if the process fails after the external call but before Application persistence.
- Credentials remain opaque references and can be consumed only through an exact
  tool-version/provider registration in the controlled egress adapter.

## Consequences

- Tool adapters cannot own authorization, budget, retry, or business completion decisions.
- A timeout can block progress until an operator or reconciler proves the external state; this is
  safer than a blind retry.
- PostgreSQL is required for production reservation semantics. The in-memory implementation is a
  deterministic test model only.
- Revision `0004_governed_tool_gateway` extends durable idempotency facts with Run, Action, Tool,
  version, request digest, cost, normalized result, and execution status.

## Verification

- Unit acceptance tests cover post-approval mutation, expiry, policy change, delegation
  revocation, schema/scope/risk enforcement, L4 default deny, Kill Switch audit, concurrent
  duplicate execution, digest collision, Accepted, and Unknown.
- PostgreSQL 17 component tests exercise concurrent reservation, one budget charge, cached result,
  digest conflict, and Unknown replay suppression after a fresh `0001` → `0004` migration.
- A real OPA 1.4.2 component test confirms read, write-with-approval, and L4 default-deny policy
  decisions.
