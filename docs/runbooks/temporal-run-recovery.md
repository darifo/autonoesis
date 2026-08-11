# Runbook: Temporal Run Dispatch and Recovery

> Status: implemented baseline · Last reviewed: 2026-08-11

## Required wiring

The Worker needs its normal PostgreSQL application connection, a separate
`AUTONOESIS_DISPATCH_DATABASE_URL` login in `autonoesis_relay`, and a Temporal endpoint. The
Dispatcher reads only committed Run-request Outbox events. It starts `goal-run-{run_id}` and marks
the event published only after Temporal accepts that fixed ID. The Reconciler periodically compares
PostgreSQL Run state with Temporal execution state.

Never start a Goal Run manually with a different Workflow ID, mark an Outbox row published to hide
a start failure, or change PostgreSQL Run state directly to match Temporal.

## Failure handling

| Observation | Expected response |
|---|---|
| Pending Run-request event, no Workflow | Dispatcher/Reconciler starts the fixed Workflow ID |
| Active DB Run, closed Temporal Workflow | Inspect Workflow failure/history; use an Application recovery command or close the Run |
| Terminal/blocked DB Run, running Workflow | Signal cancel or takeover as authorized; verify the final DB transition |
| Write Activity timed out or Worker died | Do not retry externally; inspect Gateway reservation and reconcile Unknown |
| Approval wait appears stuck | Verify Approval ID, Run binding, expiry and persisted decision; resend only the ID if valid |
| Replay fails during upgrade | Stop rollout, retain the old Worker build, and add a compatible Patch/version branch |

## Incident procedure

1. Pause the affected queue or activate the narrowest Kill Switch if further writes could be unsafe.
2. Resolve Tenant ID, business Run ID, fixed Workflow ID, Outbox event and Action idempotency key.
3. Compare PostgreSQL Run/Action/Approval state with Temporal description and history. PostgreSQL is
   authoritative for accepted business facts; Temporal history is authoritative for orchestration.
4. For a missing Workflow, let the Dispatcher or Reconciler use the fixed ID. Do not create an
   alternate execution.
5. For an ambiguous write, use provider readback and `ReconcileUnknownAction`; never reset the
   Activity attempt count or invent a success result.
6. Resume processing only after the Reconciler reports no unexplained mismatch and a replay check
   passes for the deployed Workflow build.

## Deployment checks

- Run replay tests against retained representative histories before upgrading Workers.
- Confirm the dispatch login can `SET LOCAL ROLE autonoesis_relay` but cannot assume migration or
  application roles.
- Verify Worker shutdown closes process-level stores after dispatch, reconciliation and Temporal
  polling stop.
- Alert on old unpublished Run-request events, missing Workflows, active-DB/closed-Workflow findings,
  terminal-DB/running-Workflow findings and write Activity failures.
