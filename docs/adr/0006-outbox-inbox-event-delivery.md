# ADR-0006: Outbox/Inbox for Event Delivery

- Status: accepted
- Date: 2026-08-09

## Context

Domain state changes (Goal activated, Run started, Action executed, Outcome verified) must be reliably communicated to downstream consumers—Cockpit, evaluation pipelines, audit systems, and external subscribers. The platform must not lose events or produce duplicates due to network failures, process restarts, or transaction rollbacks.

## Decision

- Domain state changes and their corresponding events are committed in the same database transaction using the Transactional Outbox pattern.
- An Outbox Publisher polls the outbox table and delivers events to the Event Bus with at-least-once semantics.
- Consumers use an Inbox table and stable idempotency keys to deduplicate.
- Events use CloudEvents-style Envelope with tenant, correlation, causation, trace, schema version, and classification fields.
- Historical event semantics are immutable—never change in place.
- External callbacks must verify signatures and causal relationship to the Action/Run.

## Consequences

- Event delivery is not "exactly-once end-to-end" but guarantees at-least-once with consumer deduplication—which is achievable in practice.
- Outbox Publisher introduces a polling/change-data-capture component.
- Consumers must implement Inbox and handle duplicates.
- Events can be rebuilt from the Outbox if the Event Bus loses state.

## Verification

- Integration tests cover: transaction rollback produces no events, duplicate messages are deduplicated by consumers, Outbox recovery after Publisher crash, external callback signature and causation validation.
