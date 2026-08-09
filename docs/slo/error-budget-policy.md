# Error Budget Policy

> Status: proposed · Last reviewed: 2026-08-09

## Purpose

Error budgets quantify how much unreliability a service can tolerate before user happiness is impacted. They create a objective, data-driven mechanism for balancing feature velocity against reliability.

## Budget Calculation

```
Error Budget = (1 - SLO) × Total Valid Requests in Measurement Window
```

Example: If SLO is 99.9% availability and 1,000,000 valid requests occur in a 30-day window:
- Error Budget = (1 - 0.999) × 1,000,000 = 1,000 allowable errors

## Measurement Windows

| Environment | Window | Rationale |
|---|---|---|
| Development | 7 days | Fast iteration |
| Staging | 14 days | Pre-production validation |
| Production | 30 days | Aligned with business cycles |

## Budget Governance

### Spending Rules

1. **Normal operations**: Consumed by unplanned SLO violations only.
2. **Planned consumption**: Scheduled maintenance that will cause violations must be pre-approved and deducted from budget.
3. **Emergency consumption**: Incident response actions are exempt from pre-approval but are reviewed post-incident.

### Budget Thresholds

| Threshold | Action |
|---|---|
| > 50% remaining | Normal operations. Features and reliability work balanced. |
| 20% - 50% remaining | Increased monitoring. Reliability work prioritized over features. |
| < 20% remaining | Feature freeze for affected service. All engineering time on reliability. |
| 0% (exhausted) | Incident declared. Post-mortem required. Budget reset only after demonstrated improvement. |

## Budget Reset

- Automatic reset at the start of each measurement window.
- Early reset may be approved after: root cause analysis completed, remediation deployed, and 7 consecutive days within SLO.
- Budget does not carry over between windows.

## Exclusions

The following are excluded from error budget consumption:

- Requests that fail due to client errors (4xx, invalid input).
- Requests during declared maintenance windows (pre-approved budget deduction).
- Requests that fail due to external dependencies beyond platform control (model provider outage), provided the platform's fallback and graceful degradation mechanisms function correctly.
- Requests in development/staging environments.

## Reporting

- Error budget dashboard updated daily in Cockpit (Governance → SLO).
- Weekly budget status review in platform standup.
- Monthly budget report for stakeholders.

## Enforcement

- Automated: CI/CD pipeline blocks Candidate promotions when error budget is below 20%.
- Manual: Platform lead may override the block with documented risk acceptance (recorded in audit).
- Post-incident: Every budget exhaustion event requires a post-mortem with corrective actions.

## Relationship to AI FinOps

Error budgets complement cost budgets. A service may be within its error budget but exceed its cost budget (or vice versa). Both must be satisfied for normal operations:

- **Error budget exhausted**: Feature freeze regardless of cost.
- **Cost budget exhausted**: Spending freeze regardless of error budget.
- **Both exhausted**: Incident declared; executive escalation.
