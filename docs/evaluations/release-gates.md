# Release Gates

> Status: proposed · Last reviewed: 2026-08-09

## Gate Overview

Every Candidate must pass through sequential release gates before Stable promotion. Each gate is a decision point with explicit criteria.

```text
Candidate Draft
  ↓
Gate 1: Offline Evaluation
  ↓
Gate 2: Independent Approval
  ↓
Gate 3: Shadow Deployment
  ↓
Gate 4: Canary Deployment
  ↓
Stable
```

## Gate 1: Offline Evaluation

**Purpose**: Verify the Candidate passes all automated checks before any production exposure.

**Criteria**:
- [ ] All deterministic rule checks pass (schema, data, security invariants).
- [ ] Outcome/Evidence verification pass rate ≥ suite threshold.
- [ ] No security or safety case failures (gating).
- [ ] Trajectory inspection passes (no unauthorized access, excessive retries, unnecessary exposure).
- [ ] LLM Grader score ≥ threshold (if applicable).
- [ ] No regression vs. baseline on any case.
- [ ] Cost per trial within budget.

**Decision**: Auto-pass if all criteria met. Auto-fail if any gating criterion fails. Manual review if LLM Grader results are `unknown` or `invalid`.

## Gate 2: Independent Approval

**Purpose**: Human or policy-based approval from someone other than the generator or evaluator.

**Criteria**:
- [ ] Approver identity ≠ generator identity.
- [ ] Approver identity ≠ evaluator identity.
- [ ] Evaluation results reviewed and acknowledged.
- [ ] Risk assessment reviewed.
- [ ] Rollback plan verified.
- [ ] Approval decision recorded with rationale and policy version.

**Decision**: Explicit approve or reject. No automatic approval.

## Gate 3: Shadow Deployment

**Purpose**: Run Candidate in parallel with Stable, comparing outcomes without affecting production.

**Criteria**:
- [ ] Shadow execution running for minimum observation period (configurable, default: 24 hours).
- [ ] Outcome agreement rate with Stable ≥ threshold.
- [ ] No security violations in shadow execution.
- [ ] Cost within shadow budget allocation.
- [ ] No evidence of data leakage between shadow and production.

**Decision**: Auto-proceed if criteria met. Auto-pause if metrics degrade. Manual decision if borderline.

## Gate 4: Canary Deployment

**Purpose**: Expose a percentage of production traffic to the Candidate with automatic guardrails.

**Criteria**:
- [ ] Canary traffic percentage within configured range (start at 5%, increase incrementally).
- [ ] Guardrail metrics within thresholds:
  - Outcome verification rate not degraded.
  - Action unknown rate not increased.
  - Policy deny rate not increased.
  - Cost per Goal not exceeded.
  - Latency not degraded beyond threshold.
- [ ] Observation window elapsed for each traffic increment.
- [ ] No human escalations caused by Candidate behavior.

**Decision**: Auto-proceed to next increment if guardrails pass. Auto-rollback if any guardrail breaches. Manual override available for emergency rollback.

## Promotion to Stable

After all gates pass:
1. Candidate status transitions to `Stable`.
2. `Release` record created with `previous_stable_version_id`.
3. Previous Stable retained for rollback.
4. All production traffic shifted to new Stable.
5. Canary and Shadow configurations cleaned up.

## Rollback

At any point, the Candidate can be rolled back:
- **During Canary**: Automatic on guardrail breach. Manual on operator decision.
- **After Stable**: Manual rollback via API or Cockpit. See [Rollback Runbook](../runbooks/rollback-candidate.md).

## Gate Override

In emergencies, gates may be overridden:
- Requires documented risk acceptance by authorized approver.
- Override reason and approver identity recorded in audit.
- Overridden Candidate is flagged for post-promotion review.
- Repeated overrides for the same capability trigger process review.
