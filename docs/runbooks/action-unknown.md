# Runbook: Action Unknown Reconciliation

> Status: baseline · Last reviewed: 2026-08-09

## When to Use

An Action has entered `Unknown` status—the Tool Gateway could not determine whether the external side effect succeeded or failed. This typically happens due to network timeout, external system crash, or ambiguous response.

## Detection

- Action status changes to `unknown` in the database.
- Alert fires on `action.unknown.v1` event (if monitoring is configured).
- Cockpit shows Action with "Unknown" badge in Run detail view.
- Run may be in `Blocked` or `Running` state awaiting resolution.

## Diagnosis

1. Identify the Action: Note `action_id`, `run_id`, `tool_name`, `operation`, `resource_id`, `idempotency_key`, and timestamp.
2. Check the external system directly:
   - Does the resource show the expected change?
   - Does the external system have an audit log for the operation?
   - Was the idempotency key recorded by the external system?
3. Check Tool Gateway logs for the invocation attempt:
   - What was the error or timeout?
   - Was the request sent before the failure?
4. Check Temporal Workflow history for the Activity attempt.

## Resolution

### Case 1: Side effect DID occur

**Evidence**: External system shows the expected state change.

1. Create an `Evidence` record with `source`, `reference` (e.g., external audit log ID), and `observed_state`.
2. Transition Action from `Unknown` → `Succeeded`.
3. The Run will continue from its next Task.
4. Record the reconciliation in the audit log.

### Case 2: Side effect did NOT occur

**Evidence**: External system shows no state change; idempotency key not found.

1. If the Action is retryable and within policy limits, re-submit with the same `idempotency_key`.
2. If not retryable (e.g., L3/L4 write without idempotency support on the target), transition Action to `Failed`.
3. Run may enter `Blocked` for replan or human decision.

### Case 3: Cannot determine

**Evidence**: External system is unavailable, or evidence is ambiguous.

1. Keep Action in `Unknown`.
2. Escalate to human operator with all available context.
3. Human decides: retry, mark as failed, or initiate compensation.
4. If the uncertainty affects other Tasks, the Run may need to enter `Blocked`.

## Prevention

- Prefer tools with idempotency support in the external system.
- Set appropriate timeouts and retry policies per risk level.
- For L3/L4 Actions, ensure the external system has an audit/status endpoint for reconciliation.
- Monitor `Action Unknown` rate as an SLO metric.

## Communication

If the Action affects an external stakeholder (customer, partner), follow the communication plan:
- Internal: Notify the Goal Owner and relevant operators.
- External: If the Action involves a customer-visible effect, communicate the delay and expected resolution time.
