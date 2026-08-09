# Runbook: Candidate Rollback

> Status: baseline · Last reviewed: 2026-08-09

## When to Use

Roll back a Candidate that has been promoted to Stable when:
- Canary guardrail metrics breach thresholds (automatic rollback).
- Production issues are traced to the new version.
- Security vulnerability discovered in the Candidate.
- Business decision to revert to previous behavior.

## Detection

- **Automatic**: Canary phase monitors guardrail metrics. If thresholds are breached, rollback is triggered automatically.
- **Manual**: Operator observes degradation in Cockpit dashboards, receives user reports, or is alerted by monitoring.
- **Scheduled**: Routine review determines the Candidate should not remain Stable.

## Rollback Process

### Automatic Rollback (Canary Phase)

1. Canary monitoring detects guardrail breach (e.g., Outcome verification rate drops below threshold).
2. Rollback workflow is triggered automatically.
3. Traffic is shifted back to previous Stable version.
4. Candidate version is transitioned to `RolledBack`.
5. Release record updated with rollback timestamp and reason.
6. Alert sent to platform operators.
7. Post-rollback: operator investigates root cause.

### Manual Rollback (Stable Phase)

#### Via Cockpit

1. Navigate to Evolution → Releases.
2. Locate the Release containing the Candidate to roll back.
3. Click "Rollback".
4. Provide a reason (required, recorded in audit).
5. Confirm rollback.
6. Verify: previous Stable version is now active.

#### Via API

```http
POST /v1/releases/{release_id}/rollback
Content-Type: application/json
Idempotency-Key: <uuid>

{
  "reason": "Outcome verification rate dropped 15% after promotion"
}
```

## Post-Rollback Verification

1. Confirm the previous Stable version is serving requests.
2. Check Outcome verification rate, Action success rate, and latency return to baseline.
3. Review audit trail for the rollback event.
4. Any in-flight Runs that were using the rolled-back Candidate may need replanning.

## Post-Rollback Actions

1. **Root cause analysis**: Why did the Candidate fail?
   - Review evaluation results—was there a gap in test coverage?
   - Review Canary metrics—which guardrail was breached?
   - Review Shadow results—were there warning signs?
2. **Update evaluation suite**: Add regression tests for the discovered failure mode.
3. **Update Improvement Proposal**: Document the failure evidence.
4. **Decide on the Candidate**: Reject with evidence, or fix and resubmit as a new Candidate.

## Prevention

- Ensure evaluation suites cover the failure mode before re-promoting.
- Verify Shadow phase ran long enough to detect the issue.
- Review Canary thresholds—were they sensitive enough?
- Consider longer observation windows for high-risk changes.

## Communication

- Internal: Notify the team that proposed the Candidate, the approver, and platform operators.
- Stakeholders: If the change was visible to end users, communicate the rollback and expected behavior.
- Audit: The rollback event is permanently recorded.

## Rollback Failure

If rollback itself fails (previous Stable version unavailable or corrupted):

1. Escalate to platform SRE immediately.
2. Attempt to restore previous Stable from Object Store backup.
3. If restoration fails, deploy last known good version from release history.
4. If all versions are compromised, invoke incident response and consider pausing all Goal execution for the affected capability.
