# ADR-0009: Capability Pack as Standard Extension Unit

- Status: accepted
- Date: 2026-08-09

## Context

Industry-specific and scenario-specific behaviors (Goal Types, Agents, Skills, Tools, Policies, Evaluation Suites) must extend the platform without modifying the core. The extension mechanism must support versioning, validation, dependency management, and supply chain integrity.

## Decision

- Capability Pack is the standard, versioned delivery unit for all industry and scenario extensions.
- A Capability Pack manifest declares: Goal Types with JSON Schema, Agent/Skill/Tool/Workflow references, SubjectRef rules and Connectors, Context/Memory Policies, default budgets, risk and approval requirements, Evaluation Suites, data classification, retention and regional restrictions, dependencies, signatures, and security scan results.
- Installation pipeline enforces: strict Manifest validation, Schema validation, version matching, reference integrity, dependency review, signature/SBOM verification, tenant authorization, and audit recording.
- Capability Packs may include a Python Entry Point for complex behavior registration.
- Core packages are forbidden from importing Capability Pack code. Examples only use public interfaces.

## Consequences

- Platform core remains industry-agnostic.
- Capability Packs become the supply chain unit—requiring signing, SBOM, and vulnerability scanning.
- Manifest evolution must maintain backward compatibility through schema versioning.
- Console shows generic run objects; industry-specific pages are the pack author's responsibility.

## Verification

- Manifest tests validate strict field checking, schema validation, version matching, and dependency integrity.
- Architecture boundary tests scan core source for industry-specific vocabulary.
- Example Capability Pack (Field Service) end-to-end test only imports public packages.
