# ADR-0011: Candidate → Evaluation → Approval → Shadow → Canary → Stable Release Pipeline

- Status: accepted
- Date: 2026-08-09

## Context

Improving agent capabilities (instructions, skills, prompts, model routes) in production must be safe, auditable, and reversible. Direct modification of production versions creates unaccountable drift and unverifiable regressions.

## Decision

All capability changes follow a governed release pipeline:

```text
Post-run Analysis → ImprovementProposal → CandidateVersion
→ Offline Evaluation (regression, safety, cost gates)
→ Independent Approval
→ Shadow (silent parallel execution, compare outcomes)
→ Canary (partial production traffic with observation window)
→ Stable (full promotion with rollback pointer)
```

Gate checks at each stage:
- **Offline Evaluation**: Must pass regression, safety, and cost thresholds on fixed evaluation suites.
- **Approval**: Independent human or policy approval; generator and evaluator must not be the approver.
- **Shadow**: Candidate runs in parallel with Stable; outcomes compared but Candidate results discarded.
- **Canary**: Percentage-based traffic; automatic rollback if guardrail metrics breach thresholds.
- **Stable**: Creates Release with previous_stable_version_id; previous Stable retained for rollback.

Forbidden from the evolution pipeline: identity, delegation, tenant isolation, policy roots, audit retention, Kill Switch, production code, and infrastructure configurations.

## Consequences

- Every Stable capability has a verifiable chain: proposal → evaluation → approval → release evidence.
- Shadow/Canary phases add infrastructure complexity (parallel execution, traffic splitting, monitoring).
- Rollback is a first-class operation, not an emergency manual procedure.
- Release history provides compliance evidence for every production change.

## Verification

- Candidate lifecycle tests cover all state transitions and role separation.
- Shadow/Canary tests validate outcome comparison and guardrail-based automatic rollback.
- Forbidden target tests confirm identity, policy, and infrastructure cannot be evolution targets.
