# Runbook: Kill Switch

> Status: baseline · Last reviewed: 2026-08-09

## When to Use

Activate the Kill Switch when an agent, tool, tenant, or provider exhibits behavior that must be stopped immediately:
- Suspected security breach or data exfiltration
- Runaway resource consumption (cost or compute)
- Malicious or severely erroneous actions in production
- External system compromise through the platform
- Regulatory or legal requirement to halt processing

## Kill Switch Dimensions

The Kill Switch can be activated at multiple granularities:

| Dimension | Effect |
|---|---|
| **Platform** | All governed Actions across tenants are halted through the Break-glass path |
| **Tenant** | All Goals, Runs, and Actions for the tenant are halted |
| **Agent** | All Runs using the specified agent version are halted |
| **Tool** | All Actions targeting the specified tool are blocked |
| **Operation** | A specific operation on a tool is blocked |
| **Provider** | All model calls to the specified provider are blocked |
| **Capability Pack** | All Goals using the specified pack are halted |

## Activation

### Via Cockpit

1. Navigate to Governance → Kill Switch.
2. Select the dimension (Tenant/Agent/Tool/Operation/Provider/Capability Pack).
3. Enter the target identifier.
4. Provide a reason (recorded in audit).
5. Confirm activation.

### Via API

```http
POST /v1/kill-switches
Content-Type: application/json
Idempotency-Key: <uuid>

{
  "dimension": "tool",
  "target": "payment-gateway",
  "reason": "Suspected duplicate payment processing"
}
```

Platform-wide activation is deliberately unavailable from this endpoint. Use
`POST /v1/platform/break-glass/kill-switch` with the independent `break_glass` identity,
`Idempotency-Key`, `X-Break-Glass-Ticket`, and a reviewed incident reason. See
[Tenant Isolation and Break-glass](tenant-isolation.md).

### Database emergency access

Do not use an application, tenant-admin, migration, relay, or database-superuser session to
modify platform control. If the API is unavailable, use the separately monitored Break-glass
login and the audited operational procedure in the tenant-isolation runbook.

## What Happens

- **In-progress Actions**: Already executing Actions complete or timeout normally. The Kill Switch does not interrupt in-flight external calls.
- **Pending Actions**: All new Action proposals are denied with reason "kill_switch_active".
- **Running Workflows**: Workflows continue but cannot execute new governed Actions. They enter `Blocked` state.
- **API**: Goal creation, Run start, and Action submission are rejected for affected resources.
- **Cockpit**: Kill Switch status is displayed prominently. Affected resources show "halted" status.

## Deactivation

1. Investigate and resolve the root cause.
2. Navigate to Governance → Kill Switch.
3. Deactivate the specific Kill Switch entry.
4. Provide a deactivation reason (recorded in audit).
5. Affected Runs may need manual unblocking or replanning.

## Audit

Every Kill Switch activation and deactivation is recorded in the audit log with:
- Who activated/deactivated
- Timestamp
- Dimension and target
- Reason
- Scope of affected resources

## Testing

Kill Switch activation and deactivation must be tested:
- In staging environment before production deployment.
- As part of disaster recovery drills.
- For each dimension to verify correct scope of effect.

## Monitoring

Alert if:
- Kill Switch is active for more than N minutes (configurable per environment).
- Number of blocked Actions exceeds threshold.
- Affected tenants report service unavailability.
