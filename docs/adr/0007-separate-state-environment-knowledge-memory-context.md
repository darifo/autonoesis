# ADR-0007: Separate State, Environment, Knowledge, Memory, and Context

- Status: accepted
- Date: 2026-08-09

## Context

Agent systems commonly conflate multiple information categories into a single "memory" or "context" abstraction, often backed by a generic vector store. This creates confusion about authority, freshness, retention, and access control.

## Decision

Five distinct information types are maintained with separate lifecycles:

| Type | Answers | Authority | Time Character | Write Rules |
|---|---|---|---|---|
| **State** | What is the current status of platform objects? | Strong | Current | Only via domain use cases and state machines |
| **Environment Fact** | What does the outside world look like right now? | Per source | Short-lived, requires refresh | Observed from authoritative connectors with `valid_until` |
| **Knowledge** | What stable facts and rules does the organization recognize? | Medium to strong | Versioned | Published by knowledge sources with content governance |
| **Memory** | What from past experience is worth reusing across runs? | Advisory | Has TTL, conflict, and invalidation | Through independent Memory Write Gate |
| **Context** | What is the minimum trusted view needed for this phase? | Derived | One-run snapshot | Assembled by policy and frozen |

Vector indices are retrieval projections only. They must not become the authoritative store for any of the five types.

## Consequences

- Each type has explicit lifecycle, retention, and access control.
- Context Assembly Pipeline produces frozen snapshots with provenance and trust scoring.
- Memory Write Gate prevents direct injection of run observations into Stable Memory.
- System complexity increases with five separate subsystems, but confusion and authority violations decrease.

## Verification

- Architecture tests verify five types are not conflated in domain code.
- Memory Write Gate tests cover provenance, PII scan, confidence, conflict, and approval checks.
- Context Snapshot tests verify immutability after creation.
