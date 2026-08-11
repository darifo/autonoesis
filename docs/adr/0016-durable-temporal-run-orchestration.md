# ADR-0016: Make Temporal Run Orchestration Recoverable and Deterministic

- Status: accepted
- Date: 2026-08-11
- Supersedes: the implementation assumptions in ADR-0004 and ADR-0006

## Context

The original Worker started Workflows directly and Activities constructed their own stores. A
successful PostgreSQL Run commit followed by a failed Temporal start could strand the Run. Signals
could carry untrusted conclusions, write Activities used default retry behavior, and there was no
DB/Workflow reconciliation or replay evidence. These gaps made process restart and ambiguous
external results unsafe.

## Decision

- A committed `autonoesis.run.requested.v1` Outbox event is the only dispatch source. A dedicated
  relay login explicitly assumes the `autonoesis_relay` role in each transaction because PostgreSQL
  does not inherit `BYPASSRLS` through role membership.
- Every Run uses the fixed Workflow ID `goal-run-{run_id}` with reject-duplicate reuse and
  use-existing conflict policies. The Dispatcher marks the Outbox event published only after
  Temporal confirms the idempotent start.
- A Reconciler compares authoritative PostgreSQL Run status with Temporal execution status. It
  automatically starts missing Workflows for active Runs and emits findings for mismatches that
  need business reconciliation.
- Workflow inputs and Activity inputs are frozen typed contracts. Workflows retain only immutable
  IDs and deterministic control state. Activities receive process-lifetime dependencies and call
  Application or Repository boundaries; they do not create stores or engines.
- Approval signals carry only an Approval ID. The following Activity reloads the authoritative
  Approval and verifies its Run binding and validity.
- Cancel, pause, resume, and takeover are explicit signals. Cancellation is observed before
  planning/evaluation and after an in-flight write returns, so it cannot interrupt a write and
  cause a blind retry. Takeover only confirms a Run already blocked by an authorized database
  command.
- Write Activities have one attempt. Timeouts, heartbeats, business deadlines, and result
  reconciliation replace blind retries. The governed Tool Gateway remains responsible for
  idempotency and Unknown outcomes.
- Long histories continue as new after external progress. Workflow changes use Temporal Patch
  markers and must replay retained histories before deployment.
- Production Workers use `SandboxedWorkflowRunner`; non-sandboxed execution is not an allowed
  production fallback.

## Consequences

- Temporal is a durable process coordinator, not the business-state authority. A running Workflow
  cannot repair a terminal PostgreSQL Run without an explicit Application use case.
- Dispatcher and Reconciler require a narrowly scoped cross-tenant relay identity. Compromise of
  that identity can observe dispatch metadata, so credentials and queue access remain separate
  from the API/Worker application role.
- A failed write Activity stops automatic progress and may require Unknown reconciliation. This is
  intentionally safer than repeating an external mutation.
- Continue-as-New changes the Temporal Run ID while preserving the fixed Workflow ID and business
  Run identity.

## Verification

- Unit tests cover failed-start recovery, fixed-ID duplicate dispatch, Approval re-read and Run
  binding, takeover confirmation, and both DB/Temporal mismatch directions.
- Real Temporal tests cover approval wait across Worker restart, cancellation during planning,
  approval wait and write execution, pause/resume, Continue-as-New, and history replay.
- A PostgreSQL 17 + Temporal component test injects the first start failure, proves the Outbox stays
  pending, then recovers exactly one Workflow and reports a closed-Workflow/active-Run mismatch.
- Governed Tool Gateway tests independently prove that repeated external-write requests reuse the
  same reservation and never repeat an Unknown or completed side effect.
