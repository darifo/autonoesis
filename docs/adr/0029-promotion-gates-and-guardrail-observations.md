# ADR 0029: Promotion Gates and Per-Deployment Guardrail Observations

- Status: Accepted
- Date: 2026-08-16

## Context

Deployments could transition from Canary to Stable, and be rolled back, without any recorded
evidence: no observation window, no sample count, no guardrail counters. The P1-05 acceptance rules
require that Canary promotion be refused without enough samples or elapsed observation time, that
missing metrics block rather than silently pass, and that guardrail breaches roll back only the
target deployment.

## Decision

1. `DeploymentObservation` persists one counter per (tenant, deployment, stage, metric) with sample
   count, consecutive breach count, last value, and first/last sample timestamps. The
   `deployment_observations` table is tenant-scoped with RLS and a four-way uniqueness constraint
   (migration `0013`, one-way).
2. `CandidateLifecycleService.record_observation` records a sample for the deployment's current
   stage and updates the consecutive breach counter against an optional guardrail operator and
   threshold. Observations recorded against a different stage are rejected.
3. `PromotionPolicy` names the minimum sample count, the observation window in seconds, and the
   required metrics. `release_stable` now requires the deployment to be in Canary, requires the
   window (measured from the persisted Canary transition time) to have elapsed, and requires every
   required metric to have at least the minimum number of samples with a recorded value. Missing
   metrics refuse promotion.
4. `rollback_deployment` rolls a deployment back with a recorded reason without requiring a prior
   Release, and `rollback_if_breached` rolls back when a metric's consecutive breach count reaches a
   threshold — so guardrail breaches affect only the target deployment.
5. Stable-pointer uniqueness remains enforced by the existing partial unique index on active
   releases; concurrent promotion is additionally serialized by the deployment's optimistic version
   CAS, so only one concurrent request can reach Stable. A PostgreSQL component test asserts
   exactly one winner.

## Consequences

- Promotion and rollback now carry persisted, queryable evidence, closing the observation-window,
  minimum-sample, and guardrail-isolation acceptance items.
- Shadow traffic write-suppression (the remaining acceptance rule) still needs a Run-to-Deployment
  linkage at execution time, which is the next P1-05 increment.
- Guardrail thresholds remain governed call-time parameters; persisting named guardrail rules
  alongside deployments is deferred to the release-executor wiring.
