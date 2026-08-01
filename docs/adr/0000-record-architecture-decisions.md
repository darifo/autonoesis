# ADR-0000: Record architecture decisions

- Status: accepted
- Date: 2026-08-01

## Context

Autonoesis combines domain state, durable execution, agent harnesses, external tools, governance, and controlled evolution. Important boundaries can otherwise become implicit and drift across code, deployment, and team ownership.

## Decision

Record decisions that affect authority, process boundaries, persistence, protocols, security, tenancy, or release policy as versioned Markdown ADRs.

Each ADR contains context, decision, consequences, alternatives, and verification. Accepted ADRs are immutable except for clarifications; a new ADR supersedes an old decision.

## Consequences

- Contributors can understand why a boundary exists.
- Reviewers can identify architectural changes rather than treating them as local refactors.
- Documentation work becomes part of the definition of done.

## Template

```markdown
# ADR-NNNN: <decision>

- Status: proposed
- Date: YYYY-MM-DD

## Context
## Decision
## Consequences
## Alternatives considered
## Verification
```
