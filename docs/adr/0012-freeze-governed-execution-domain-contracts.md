# ADR-0012: Freeze Governed Execution Domain Contracts Before Persistence

- Status: accepted
- Date: 2026-08-11

## Context

The prototype represented risk, budgets, classifications, execution mode, and Action arguments
with primitive strings or flat key/value tuples. Approval only bound an argument digest, Run did
not freeze the versions it executed, verified Outcome accepted opaque Evidence IDs, and Candidate
could transition directly from Approved to Stable. Those shapes cannot enforce execution-time
authorization or produce a trustworthy evidence and release chain.

## Decision

The domain contract is frozen around the following invariants:

- Risk tier, budget unit, data classification, execution mode, compensation, capture method, and
  integrity are constrained values.
- Goal activation requires a future deadline, positive budget, explicit owner, data policy, and a
  positive concurrent-Run limit. Delegation is an explicit optional reference.
- Plan owns a validated Task DAG. Every Task can declare preconditions, estimated cost, risk,
  compensation capability, and Evidence requirements; indirect cycles are rejected.
- Run must bind an immutable `RunExecutionSnapshot` containing Plan, ContextSnapshot, Agent,
  Skill, Tool, Model Route, and Policy versions before it can enter Running.
- Action arguments use bounded canonical nested JSON. The Action digest covers every executable
  field, including immutable Tool Version, operation, resource scope, arguments, risk,
  idempotency, expected effect, classification, and execution mode.
- `ActionExecutionEnvelope` is the complete execution boundary. Its digest is recomputed during
  construction so a caller cannot provide fields that disagree with the approved Action digest.
- Approval binds Tenant, Run, Action, Tool Version, operation, resource scope, argument digest,
  complete Action digest, Policy Version, role, and expiry. Authorization is evaluated against all
  bindings at execution time.
- Evidence includes content digest, source identity, capture method, classification, validity
  interval, and integrity status. A Verified Outcome contains complete Evidence objects, and
  rejects cross-tenant, cross-Run, invalid, expired, or integrity-unverified Evidence.
- State-bearing aggregates append transition timestamp, reason, Actor, and optimistic version.
- Candidate ends at Approved or Rejected. An Approved Candidate creates a separate Deployment;
  Deployment must pass Shadow then Canary before Stable, and Release requires that Stable
  Deployment.

Transport contracts may re-export domain value enums but must not duplicate their validation
behavior. PostgreSQL mappings and cross-process schemas must serialize these frozen semantics
without weakening them.

## Consequences

- Primitive and positional constructors are intentionally incompatible and must be migrated.
- API and adapters must convert transport primitives into domain values at their boundaries.
- The old Candidate `Approved → Stable` shortcut is removed; clients use Deployment endpoints.
- P0-03 migrations must persist Run snapshots, transition metadata, complete Approval bindings,
  Evidence metadata, and Deployment relationships.
- Execution-time services can reject tampering without trusting request-provided risk or digest.

## Verification

- Domain tests cover expired Goal and illegal budget rejection, indirect Plan cycles, immutable Run
  snapshots, nested Action digest changes, exact Approval binding, complete Evidence requirements,
  tampered execution envelopes, and Candidate deployment gate order.
- Runtime tests exercise the exact Approval predicate used by the Tool Gateway.
- Architecture-boundary, Ruff, MyPy strict, and the complete unit suite remain required gates.
