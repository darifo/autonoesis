# Runbook: Governed Tool Execution

> Status: implemented baseline · Last reviewed: 2026-08-11

## Required production wiring

External effects must be invoked with `GoalExecutionApplication.execute_governed_action`. Construct
the Application with a `GovernedToolGateway`; direct caller-asserted authorization is disabled by
default. The Gateway requires an immutable Tool catalog, live delegation source, schema validator,
OPA policy adapter, Kill Switch store, PostgreSQL atomic reservation adapter, credential broker,
controlled egress registry, and durable audit adapter.

Register egress adapters by the exact `(tool_name, version, provider)` tuple. Credentials exposed to
an adapter are opaque leases with the server-owned scope and expiry. Never place credential values
in Action parameters, Context, Evidence, Audit, or logs.

## Result handling

| Result | Action state | Operator behavior |
|---|---|---|
| `rejected` | Denied | Inspect audit reason; do not execute outside the Gateway |
| `failed` | Failed | Replan or close the Run according to policy |
| `accepted` | Unknown | Reconcile using the provider status/readback API |
| `unknown` | Unknown | Never retry blindly; follow the Unknown runbook |
| `succeeded` | Succeeded | Use persisted execution Evidence for Outcome verification |

An idempotency conflict means the same key is bound to a different canonical Action digest. Treat
it as a caller defect or attack; never return the prior result. `in_progress`, `accepted`, and
`unknown` reservations are not eligible for automatic execution.

## Incident checks

1. Activate the narrowest applicable Kill Switch before investigating a suspected unsafe tool.
2. Query Action, ActionAttempt, Evidence, Audit/Outbox, budget entry, and idempotency record by
   Tenant and Action ID.
3. Compare Tool version, request digest, policy version, Approval expiry, delegation and credential
   scope. Never alter a stored digest to make an Approval match.
4. For Unknown, use authoritative external readback and the reconciliation use case.
5. Deactivate the Kill Switch only after the unsafe path is removed and a staging execution proves
   the corrected controls.
