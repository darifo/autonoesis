# ADR-0014: Make Application Use Cases the Governed Execution Writer

- Status: accepted
- Date: 2026-08-11

## Context

The API previously owned Goal/Run idempotency and Approval mutation, while Temporal Activities
directly advanced Run state and could mark a Run successful without persisted Tasks, Evidence, or
Outcomes. Repository methods were individually transactional, but there was no Application-owned
transaction spanning multiple aggregate changes, Audit, Outbox, and idempotency acceptance.

## Decision

- `GoalExecutionApplication` is the sole production writer for the initial vertical execution use
  cases: Goal creation/activation, Run request and context, validated planning, Task advancement,
  Action proposal/authorization/attempts, Approval, Evidence, Outcome, reconciliation, and
  Run/Goal completion.
- Every invocation carries `CommandContext`: tenant-bound Identity, Correlation, Causation,
  Idempotency Key, and canonical request digest. Reusing a key with a different digest is an
  explicit concurrency conflict.
- The Application opens the transaction. PostgreSQL aggregate methods reuse its task-local
  session, so business state, Audit, Outbox, and idempotency acceptance commit or roll back
  together. The in-memory adapter snapshots state to preserve the same test contract.
- `CreateGoal` persists Draft and `ActivateGoal` is a separate authorized transition.
- Context is immutable per Run. Plan validation binds the Context, Plan, Agent, Skill, Tool,
  Model Route, and Policy versions into the Run execution snapshot before Running begins.
- Tool receipts are persisted as immutable `ActionAttempt` facts. They may advance an Action to
  Succeeded, Failed, or Unknown, but cannot create an Outcome. Unknown requires an explicit
  reconciliation attempt.
- `CompleteRun` is the only success decision for a Run and requires successful Tasks/Actions plus
  a Verified Outcome for every Goal criterion. `SatisfyOrFailGoal` separately decides the Goal.
- API controllers, Temporal Activities, and the operational management command invoke these same
  use cases. Activities may dispatch work but cannot infer business success from Activity return.

## Consequences

- The API now exposes explicit Goal activation; callers cannot request a Run for a Draft Goal.
- A Temporal prototype can remain Running until a later gateway/verifier records the required
  facts. This is deliberate and replaces the former false-success shortcut.
- Revision `0003_application_use_cases` adds tenant-isolated Action Attempts and enforces one
  Context Snapshot per Run.
- P0-05 can replace the policy and Tool adapters without moving authorization or completion
  invariants out of Application.

## Verification

- `packages/application/tests/test_execution_use_cases.py` covers the complete reference chain,
  rejection, conflicting decisions, Unknown reconciliation, expired authorization, idempotent
  retry, request-digest mismatch, and transaction rollback.
- `packages/adapters/tests/test_postgres_authority.py` runs the Application transaction on real
  PostgreSQL and verifies Context, Plan, and reconciliation visibility through a second Store.
- API and Worker tests assert Draft/activation semantics and that Activity dispatch does not mark
  a Run successful.
