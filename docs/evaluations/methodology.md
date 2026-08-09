# Evaluation Methodology

> Status: proposed · Last reviewed: 2026-08-09

## Purpose

Evaluation is the gate for all capability improvement in Autonoesis. It answers: "Does this version perform better, worse, or the same as baseline, and is it safe to release?"

## Evaluation Objects

| Object | Definition |
|---|---|
| `EvaluationCase` | A reproducible scenario with input, constraints, and success evidence |
| `EvaluationSuite` | A collection of Cases with explicit coverage structure, weights, and version |
| `EvaluationHarness` | A fixed environment with specific model, tool stubs/simulations, budget, and data collection |
| `EvaluationTrial` | A single independent run of a subject version against a Suite in a Harness |
| `GraderResult` | The output of a rule, model, or human grader with evidence |

## Grader Pipeline

Graders execute in strict priority order. Lower-priority graders only run if higher-priority ones pass:

### 1. Deterministic Rules

**What**: Schema validation, file integrity, data invariants, security hard-checks.
**Who**: Automated rule engine.
**Output**: `pass | fail` with rule reference.
**Failure means**: Candidate is rejected immediately. No further grading.

### 2. Outcome/Evidence Verification

**What**: Did the agent achieve the expected real-world outcome? Is Evidence present and verifiable?
**Who**: Evidence verifier (reads authoritative system state or simulation).
**Output**: `pass | fail | unknown` with evidence references.
**Failure means**: Candidate failed to produce verifiable outcomes.

### 3. Trajectory Inspection

**What**: Did the agent take appropriate steps? Was there unauthorized access, excessive retries, unnecessary exposure?
**Who**: Trajectory analyzer.
**Output**: `pass | fail` with trajectory issues annotated.
**Failure means**: Agent behavior was unsafe or inefficient, even if outcome was achieved.

### 4. LLM Grader

**What**: Semantic quality assessment of agent reasoning and communication.
**Who**: Independent LLM with rubric and calibration set.
**Output**: `score (0-1) | pass | fail | unknown` with rationale.
**Requires**: Fixed rubric, calibration on known samples, blind evaluation where possible.

### 5. Human Grader

**What**: Professional judgment, high-risk evaluation, value judgments, boundary cases.
**Who**: Authorized human evaluator.
**Output**: `score (0-1) | pass | fail | unknown` with rationale.
**Used for**: High-risk Candidates, indeterminate automated results, value-sensitive outcomes.

## Result Categories

| Result | Meaning |
|---|---|
| `pass` | Candidate meets or exceeds baseline on this case |
| `fail` | Candidate performs worse than baseline or violates a hard constraint |
| `unknown` | Cannot determine (environment anomaly, missing evidence) |
| `invalid` | Trial could not be completed (infrastructure failure, timeout) |

`unknown` and `invalid` results must not be coerced into pass/fail. They are reported separately and investigated.

## Suite Design Principles

1. **Coverage**: Cases should cover normal paths, edge cases, boundary conditions, and attack scenarios.
2. **Independence**: Cases should be independent—passing one should not guarantee passing another.
3. **Weighting**: Cases may be weighted by business criticality. Default is equal weight.
4. **Versioning**: Suites are versioned. Changes to case composition require a new version.
5. **Hidden cases**: A subset of cases may be hidden from generators to prevent overfitting.
6. **Calibration**: LLM and human graders must be calibrated on known samples before evaluating Candidates.

## Anti-Patterns

- Reporting only "best case" or average results without distribution.
- Hiding failed cases or recategorizing them as "edge cases."
- Using the same model for generation and grading.
- Allowing the generator to see evaluation cases before the trial.
- Forcing indeterminate results into binary pass/fail.
