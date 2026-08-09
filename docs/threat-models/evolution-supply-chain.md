# Evolution & Supply Chain Threat Model

> Status: baseline · Last reviewed: 2026-08-09

## Scope

The evolution pipeline (ImprovementProposal → Candidate → Evaluation → Approval → Shadow → Canary → Stable) and Capability Pack supply chain introduce risks of unauthorized capability changes, evaluation gaming, and supply chain compromise.

## Assets

- Candidate artifacts (prompt changes, skill code, model routes)
- Evaluation suites, datasets, and grader results
- Release history and Stable pointers
- Capability Pack manifests and entry points
- Supply chain attestations (signatures, SBOM)

## Threats

### EV-001: Candidate Self-Approval

**Description**: The same identity or component generates, evaluates, and approves a Candidate, creating an uncontrolled improvement loop.

**Controls**:
- `CandidateLifecycleService` enforces generator ≠ grader and generator ≠ approver.
- Evaluation suites are versioned and independent of the generator.
- Approval records the approving identity, policy version, and evaluation evidence.
- Audit trail captures the complete chain: proposal → candidate → evaluation → approval → release.

### EV-002: Evaluation Gaming

**Description**: Candidate is optimized to pass known evaluation cases without genuine improvement, or evaluation data is contaminated by training on test cases.

**Controls**:
- Hidden test cases not visible to the generator.
- Data partitioning: evaluation datasets separated from training/improvement data.
- Independent grader using fixed rubric and calibration set.
- Blind evaluation where possible (grader does not know which Candidate is being evaluated).
- Outcome-first verification: success is measured by real-world results, not just model output matching.
- Anti-contamination scanning of evaluation datasets.

### EV-003: Malicious Capability Pack

**Description**: A Capability Pack declares benign capabilities but contains code that escalates privileges, exfiltrates data, or modifies platform behavior.

**Controls**:
- Manifest strict field validation—unknown fields rejected.
- Signature verification against trusted publishers.
- SBOM inclusion and dependency vulnerability scanning.
- Source allowlist and publisher reputation.
- Sandbox execution for Capability Pack Entry Points.
- Capability ceiling: Pack cannot grant permissions beyond platform policy.
- Tenant authorization required before installation.
- Audit record of all installations with manifest digest.

### EV-004: Rollback Failure

**Description**: A promoted Candidate causes production issues, but the rollback mechanism fails because the previous Stable version is unavailable or corrupted.

**Controls**:
- Every Release records `previous_stable_version_id`.
- Previous Stable artifacts are immutable and retained.
- Rollback is a first-class operation tested in CI.
- Canary phase with automatic guardrail-based rollback reduces blast radius.
- Shadow phase validates Candidate against production traffic before promotion.

### EV-005: Unauthorized Evolution Target

**Description**: The evolution pipeline attempts to modify forbidden targets: identity, delegation, tenant isolation, policy roots, audit retention, Kill Switch, production code, or infrastructure.

**Controls**:
- `ImprovementTarget` enum limits allowed targets to: Agent Instruction, Skill, Prompt Asset, Model Route.
- Application layer rejects proposals targeting forbidden categories.
- Architecture tests verify forbidden categories are not evolvable.
- Infrastructure changes follow existing SDLC/IaC processes, not the evolution pipeline.

### EV-006: Supply Chain Dependency Confusion

**Description**: A Capability Pack declares a dependency that resolves to a malicious package with a similar name.

**Controls**:
- Dependency review during installation validates package origin and integrity.
- Allowlist of trusted package registries and publishers.
- Lock file with content hashes for all dependencies.
- Regular vulnerability scanning of installed packs.

### EV-007: Shadow/Canary Data Leakage

**Description**: Shadow or Canary execution of a Candidate exposes production data to an unproven version.

**Controls**:
- Shadow execution uses production data but discards results—no external side effects.
- Shadow environment has same data access controls as production.
- Canary traffic is limited to a percentage; automatic rollback on guardrail breach.
- All Shadow/Canary execution is audited and subject to the same data policies as Stable.
