# ADR 0031: Persist Paired Shadow Comparison Evidence

- Status: Accepted
- Date: 2026-08-25

## Context

Shadow write suppression prevents a Candidate from producing external side effects, but the release
path still lacked a governed operation that executes pinned Stable and Candidate versions together
and preserves their comparison. Aggregated guardrail counters alone cannot prove which request and
which two versions produced a release observation.

The Temporal Candidate lifecycle also reported `stable` immediately after creating a Shadow
Deployment. That label bypassed the intended Shadow evidence, Canary, and Stable release gates.

## Decision

1. `CandidateLifecycleService.execute_shadow_pair` loads the authoritative Shadow Deployment and
   Candidate, then concurrently invokes a `ShadowSubjectRuntime` for the pinned baseline version and
   Candidate version with the same request reference and input.
2. The runtime receives an explicit effect contract: Stable serves the normal path, while Candidate
   executes with external effects disabled. Runtime adapters must route Candidate effects to an
   Effect Sink; the existing execution-time Shadow write guard remains a second enforcement layer.
3. Every pair produces an immutable `ShadowComparison` containing both versions and each side's
   Outcome score, cost, latency, security violations, human corrections, and suppressed external
   write attempts. PostgreSQL stores these facts in the tenant-scoped, RLS-protected
   `shadow_comparisons` table, unique per Deployment and request reference.
4. The application projects Outcome, cost, latency, security, and human-correction deltas into the
   existing per-Deployment Shadow observation counters so later promotion policy can consume them.
5. Candidate lifecycle completion after approval now reports `shadow`, never `stable`. Stable remains
   reachable only through the Canary promotion gate and Release creation path.

## Consequences

- Release evidence retains the exact request and version pair instead of only a rolling aggregate.
- Non-Shadow Deployments fail before either subject runtime is invoked.
- A failed metric projection cannot erase the immutable comparison source fact; projections can be
  rebuilt from it. Atomic outbox-based projection is a future hardening item.
- The application orchestration boundary is implemented and testable. A production Worker adapter
  now exposes a registered, non-retryable `ShadowPairWorkflow`/Activity contract and fails closed
  when no Shadow Runtime is injected. Live-request dispatch, a production Shadow Runtime and
  Candidate sandboxing, Canary routing, and the independent Release Executor remain required before
  P1-05 is complete.
