# ADR 0036: Real-Signal Observability, Phase Ledger FinOps, and the Live Operations Console

- Status: Accepted
- Date: 2026-09-09

## Context

P1-07 required observability that reflects the running platform. Before this decision the
console rendered static sample rows, no process emitted traces or structured logs, SLO budgets
averaged measurements unweighted (ignoring `sample_count` and `gte`/`lte` semantics), the
FinOps tracker was an in-memory list disconnected from the authoritative budget ledger, and
operator surfaces for approval, unknown reconciliation, kill switch, rollback, and run
takeover had no HTTP exposure at all.

## Decision

1. **Shared telemetry module.** `autonoesis_adapters.telemetry` configures OpenTelemetry
   (OTLP/HTTP exporter) and a JSON log formatter. Without an OTLP endpoint both are no-ops:
   processes never fail startup for missing telemetry. The API adds a request-span middleware
   that links `X-Tenant-ID`/`X-Correlation-ID` into span attributes and returns `X-Trace-ID`;
   the Worker installs Temporal's `TracingInterceptor` so workflow/activity execution carries
   the trace; repository authoritative facts (`_record_fact`), Tool Gateway reservations, and
   model adapters emit child spans. Trace continuity across API→Temporal→activity rides the
   propagated context; correlation ids remain the joinable fallback in span attributes.
2. **Redacting structured logs.** One JSON object per record with service, level, logger,
   message, trace ids, and contextual tenant/correlation fields. Secrets are scrubbed
   recursively: sensitive key names and long homogeneous blobs are replaced with
   `[redacted]` before serialization.
3. **Metrics from real events.** SLO measurements are projected from persisted audit events
   (`AuditEventSloProjector`): outcome success rate and action unknown rate carry the event
   counts as `sample_count`. SLIs without event instrumentation are absent, never synthesized.
   `GET /v1/slos` computes budgets from the tenant's own audit chain.
4. **Weighted SLO budgets.** `SLORegistry.compute_budget` weights every measurement by
   `sample_count`; `gte` targets consume shortfalls below the target, `lte` targets consume
   excess above it, zero-sample measurements fabricate nothing (full budget), matching
   `docs/slo/error-budget-policy.md`.
5. **Phase-ledger FinOps.** `CostPhaseLedger` records estimate/reserve/settle/retry_waste
   entries through the authoritative `budget_ledger` (unique reference = idempotency) and
   summarizes per run and per goal; legacy `tool_execution` reservations count as reserves.
   `GET /v1/finops/runs/{id}` and `/v1/finops/goals/{id}` expose the phase breakdown.
6. **Operations surface.** New HTTP endpoints — run listing, run takeover/cancel, run action
   listing, and unknown-action reconciliation — join approval decisions, kill switches, and
   release rollback as governed operator mutations (roles + Idempotency-Key + audit). The one
   sanctioned POST under `/v1/actions` is `/reconcile`; outcomes remain read-only over HTTP.
7. **Live console.** Cockpit fetches real platform state through a typed API client
   (operator-supplied connection settings, identity headers, fresh idempotency keys). Data
   pages render loading/error/empty states explicitly and never fall back to sample rows; the
   overview remains a labelled static mock. The operations center drives all five high-risk
   surfaces behind typed-confirmation dialogs (e.g. `HALT`, `ROLLBACK`, `RECONCILE`) that
   require pasting the target identifier.

## Consequences

- The compose stack's Jaeger/OTel-collector becomes live infrastructure for API and worker
  traces; metric/log pipelines in the collector remain to be configured.
- Console credentials live in the operator's browser (localStorage) and are sent as dev-mode
  identity headers; production console authentication must move to OIDC-issued identities.
- Latency SLIs (approval p50/p95) and per-goal FinOps rollups over longer windows need
  event-time pairing instrumentation that remains future work.
