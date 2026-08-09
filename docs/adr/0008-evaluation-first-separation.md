# ADR-0008: Evaluation-First with Separation of Improvement, Grading, and Release

- Status: accepted
- Date: 2026-08-09

## Context

An agent platform that optimizes its own behavior must prevent a component from generating, grading, and releasing its own candidates. Without separation, evaluation becomes self-validating and improvement becomes unaccountable.

## Decision

- Evaluation is the gate for all improvement—not an afterthought.
- `ImprovementProposal` is generated from post-run analysis of trajectories, outcomes, and human feedback.
- `CandidateVersion` is the unit of proposed change, with a fixed baseline, artifact, generator identity, and evaluation suite.
- Grader pipeline runs in strict order: deterministic rules → Outcome/Evidence verification → Trajectory inspection → LLM Grader (with rubric and calibration) → Human Grader.
- Grader results allow `pass | fail | unknown | invalid`—forcing indeterminate samples out of green metrics.
- Generator, Grader, and Approver must be distinct identities/roles.
- Stable promotion creates a `Release` with `previous_stable_version_id` for rollback.

## Consequences

- Self-grading and self-approval are prevented at the application layer, enforced at the Candidate lifecycle service.
- Evaluation suites must be versioned and their composition affects pass rates.
- Independent human or policy-based approval is required before Stable promotion.
- Release history provides a complete audit trail of what changed, who approved it, and how to roll back.

## Verification

- Candidate lifecycle tests verify generator ≠ grader and generator ≠ approver rejection.
- Evaluation suite tests cover deterministic, outcome, trajectory, and LLM grading layers.
- Release tests verify stable pointer chain and rollback semantics.
