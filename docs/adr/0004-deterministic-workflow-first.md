# ADR-0004: Deterministic Workflow First, Agent Loop Limited to Bounded Tasks

- Status: accepted
- Date: 2026-08-09

## Context

Long-running goals require reliable task execution across pauses, approvals, cancellations, and process restarts. The platform must choose between fully deterministic orchestration and autonomous agent decision-making for each unit of work.

## Decision

- Default to deterministic Workflow (Temporal) for all task execution.
- Agent Loop is only permitted when the next step within a Task depends on open-ended observation and the path cannot be pre-enumerated.
- Each Agent Loop must fix: Agent/Prompt/Skill/Tool/Model Route version, Context Snapshot ID, visible Tool set and resource scope, maximum turns/tokens/cost/time/concurrency/sub-agent depth, and explicit success/failure/blockage/escalation/termination conditions.
- Model output is always a structured proposal. It cannot directly mutate authoritative state or acquire permissions.

## Consequences

- Most execution paths are replayable and auditable from Workflow History.
- Agent Loop usage is an explicit design choice with bounded blast radius.
- Loop guardrails (token budget, turn limit, cost cap) prevent runaway agent behavior.
- Observability must distinguish deterministic steps from agent-chosen steps.

## Verification

- Agent Loop tests validate all guardrails trigger at their limits.
- Workflow replay tests cover process restart, timer expiry, and signal handling.
