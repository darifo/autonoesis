# Service Level Objectives

> Status: proposed · Last reviewed: 2026-08-09

## SLI/SLO Framework

Numerical SLO values require observable capacity and business baselines. The following framework defines what to measure; exact numbers will be set jointly by Product, SRE, and Business after production baselines are established.

| Category | SLI Examples | Target Direction |
|---|---|---|
| **Control Plane Availability** | Goal/Run/Approval API success rate | Defined per business tier; not bound to model provider availability |
| **Durability** | Workflow recovery rate, event loss rate | Replayable; core events zero loss |
| **Side-Effect Safety** | Duplicate side-effect rate, Action Unknown reconciliation time | Duplicate side effects approach zero; Unknown has defined response target |
| **Outcome Integrity** | Verified Outcome Evidence completeness rate | 100% |
| **Governance** | Unauthorized Action execution count, cross-tenant leakage count | 0 |
| **Human-in-the-Loop** | Approval wait time, takeover recovery time | Defined per risk tier and business timeline |
| **Release** | Canary guardrail-breach automatic rollback time | Measurable and drilled |

## Error Budget Policy

### Principles

1. **Error budget is per service, per SLO**: Each SLI has its own error budget.
2. **Budget is consumed by violations**: Every request that fails the SLO threshold consumes budget.
3. **Budget exhaustion triggers action**: When budget is exhausted for a measurement window, new feature releases are paused until reliability is restored.
4. **Budget is not for "expected" failures**: Planned maintenance and known downtime consume budget and must be accounted for.

### Budget Consumption Rules

- **Automatic consumption**: Any request that violates the SLO.
- **Planned consumption**: Scheduled maintenance windows.
- **Emergency consumption**: Incident response actions that may cause SLO violations.

### Budget Exhaustion Protocol

1. **Alert**: SRE and platform team notified.
2. **Feature freeze**: No new Candidate promotions or capability deployments.
3. **Reliability work prioritized**: Bug fixes, performance improvements, capacity additions take precedence over feature work.
4. **Post-mortem**: Root cause analysis within N business days.
5. **Budget reset**: After the measurement window rolls over, or after demonstrated reliability improvement.

## Key Metrics

### Outcome Metrics

- **Goal satisfaction rate**: Percentage of Goals reaching `Satisfied` status.
- **Outcome verified rate**: Percentage of Outcomes with `Verified` status and complete Evidence.
- **Evidence completeness**: Percentage of Verified Outcomes with all required Evidence references present.

### Reliability Metrics

- **Run success rate**: Percentage of Runs reaching `Succeeded`.
- **Run block rate**: Percentage of Runs entering `Blocked`.
- **Run cancel rate**: Percentage of Runs cancelled.
- **Action unknown rate**: Percentage of Actions entering `Unknown`.
- **Recovery time**: Time from `Unknown` to resolution (Succeeded or Failed).

### Quality Metrics

- **Evaluation pass rate**: Percentage of Candidates passing offline evaluation.
- **Regression rate**: Percentage of evaluation cases that regressed vs. baseline.
- **Human correction rate**: Percentage of Actions where human intervention changed the outcome.

### Security Metrics

- **Policy deny rate**: Percentage of Actions denied by policy.
- **Approval bypass attempts**: Count of attempts to execute without required approval.
- **Prompt injection detections**: Count of detected injection attempts.
- **Cross-tenant violation attempts**: Count of detected cross-tenant access attempts.

### Cost & Efficiency Metrics

- **Cost per verified Goal**: Total cost (model + tool + sandbox + storage) / number of Verified Goals.
- **Token/tool/sandbox cost**: Cost breakdown by resource type.
- **Wasted retry cost**: Cost of Actions that ultimately failed.
- **Time-to-first-plan**: Time from Goal creation to first Plan version.
- **Time-to-outcome**: Time from Goal activation to Outcome verification.
- **Approval wait time**: Time from Approval request to decision.
- **Critical path duration**: Longest sequential chain of Tasks in a Run.

### Evolution Metrics

- **Candidate win rate**: Percentage of Candidates that reach Stable.
- **Canary rollback rate**: Percentage of Canary deployments that trigger automatic rollback.
- **Time-to-stable**: Time from Candidate creation to Stable promotion.
- **Capability drift**: Measured divergence between current Stable and baseline evaluation results.

## Optimization Target

The primary optimization target is **total cost per verified successful Goal**—not single token price or single model latency. This aligns platform optimization with business value delivery.
