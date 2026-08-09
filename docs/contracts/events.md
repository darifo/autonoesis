# Event Contracts

> Status: baseline · Last reviewed: 2026-08-09

## Event Naming Convention

Events use reverse domain name + resource + past tense + version:

```text
ai.example.agent.goal.activated.v1
ai.example.agent.run.started.v1
ai.example.agent.action.unknown.v1
ai.example.agent.outcome.verified.v1
ai.example.agent.candidate.promoted.v1
```

## Command vs. Event Separation

- **Command**: Expresses intent that may be rejected. Not a fact.
- **Event**: Expresses something that has already happened and is irrevocable.

Commands must not be treated as events, and events must not be used to request action.

## CloudEvents Envelope

Events use CloudEvents-compatible envelope:

```yaml
specversion: "1.0"
id: uuid
source: "autonoesis/api" | "autonoesis/worker"
type: "ai.example.agent.goal.activated.v1"
time: rfc3339
datacontenttype: "application/json"
data:
  # payload per event type
extensions:
  tenantid: uuid
  correlationid: uuid
  causationid: uuid | null
  actorid: uuid
  principalid: uuid | null
  traceparent: string | null
  classification: public | internal | confidential | restricted
  schemaversion: integer
```

## Core Event Types

### Goal Events

| Event | Trigger |
|---|---|
| `goal.created.v1` | GoalContract created (Draft) |
| `goal.activated.v1` | Goal transitioned to Active |
| `goal.paused.v1` | Goal paused |
| `goal.satisfied.v1` | All success criteria verified |
| `goal.failed.v1` | Goal failed |
| `goal.cancelled.v1` | Goal cancelled |

### Run Events

| Event | Trigger |
|---|---|
| `run.started.v1` | Run created and started |
| `run.blocked.v1` | Run blocked (awaiting approval/facts) |
| `run.succeeded.v1` | Run completed successfully |
| `run.failed.v1` | Run failed |
| `run.cancelled.v1` | Run cancelled |

### Action Events

| Event | Trigger |
|---|---|
| `action.proposed.v1` | Action proposed by agent/harness |
| `action.authorized.v1` | Action authorized for execution |
| `action.executed.v1` | Action execution completed |
| `action.unknown.v1` | Action result uncertain—reconciliation needed |
| `action.denied.v1` | Action denied by policy or approval |

### Evidence & Outcome Events

| Event | Trigger |
|---|---|
| `evidence.recorded.v1` | Evidence captured and stored |
| `outcome.verified.v1` | Outcome verified with evidence |
| `outcome.not_met.v1` | Outcome determined not met |

### Evolution Events

| Event | Trigger |
|---|---|
| `proposal.created.v1` | ImprovementProposal created |
| `candidate.evaluating.v1` | Candidate entered evaluation |
| `candidate.approved.v1` | Candidate approved |
| `candidate.promoted.v1` | Candidate promoted to Stable |
| `candidate.rolled_back.v1` | Candidate/Release rolled back |

## Event Immutability

- Published event semantics must never change in place.
- New event versions must use a new type string (e.g., `...v2`).
- Consumers must handle unknown event types gracefully (ignore or dead-letter).

## Delivery Guarantees

- At-least-once delivery via Transactional Outbox pattern.
- Consumer deduplication via Inbox and stable idempotency keys.
- Events are not the authoritative store—they can be rebuilt from the Outbox.
