# Capability Pack Contract

> Status: baseline · Last reviewed: 2026-08-09

## Manifest Structure

A Capability Pack is defined by a `capability-pack.yaml` manifest:

```yaml
api_version: "autonoesis/v1alpha1"
pack_id: "field-service.restore-equipment"
version: "0.1.0"
python_entry_point: "field_service.plugin:create_plugin"

goal_types:
  - goal_type: "field-service.restore-equipment"
    input_schema:
      type: object
      required: ["equipment_id", "symptoms"]
      properties:
        equipment_id:
          type: string
        symptoms:
          type: array
          items:
            type: string
    agent: "field-service-diagnosis"
    evaluation_suite: "field-service-recovery"
    default_policy: "field-service-production-write"
    default_budget: 100

skills:
  - skill_id: "diagnose-from-telemetry"
    # ...

tools:
  - tool_id: "field-service-read-telemetry"
    # ...

policies:
  - policy_id: "field-service-production-write"
    # ...

evaluation_suites:
  - suite_id: "field-service-recovery"
    # ...
```

## Installation Validation

The installation pipeline enforces:

1. **API version check**: `api_version` must be `autonoesis/v1alpha1`.
2. **SemVer validation**: `version` must be valid SemVer.
3. **Strict field validation**: Unknown fields in manifest are rejected.
4. **JSON Schema validation**: Each `goal_type.input_schema` must be valid JSON Schema (Draft 2020-12).
5. **Manifest-Entry Point version match**: `python_entry_point` distribution version must match manifest `version`.
6. **Pack ID ownership**: Entry point package name must match `pack_id` prefix.
7. **Identifier uniqueness**: Goal types, skill IDs, tool IDs, policy IDs, suite IDs must be unique within the pack.
8. **Reference integrity**: All agent, skill, tool, policy, and suite references must resolve within the pack.
9. **Dependency review**: External dependencies declared and verified.
10. **Signature/SBOM verification**: Pack must be signed; SBOM must be present and verified.
11. **Tenant authorization**: Installing tenant must be authorized for the pack.
12. **Audit recording**: Installation event with manifest digest recorded.

## Python Entry Point

Complex behavior uses a Python entry point:

```python
# setup.cfg / pyproject.toml
[project.entry-points."autonoesis.capability_packs"]
field-service.restore-equipment = "field_service.plugin:create_plugin"
```

The entry point factory returns a `CapabilityPackPlugin` with:
- `manifest`: The validated `CapabilityPackManifest`
- `register(registry)`: Registers goal types, skills, tools, policies with the platform

## Compatibility

- Capability Packs are versioned independently of the platform.
- Manifest schema evolves through versioned `api_version` fields.
- New optional manifest fields are backward-compatible.
- Required field additions, field removals, or semantic changes require a new `api_version`.
- Platform validates manifest against its supported `api_version` range and rejects unsupported versions.

## Supply Chain

- Every Capability Pack must be signed.
- SBOM (Software Bill of Materials) must be included.
- Platform verifies signature and SBOM before installation.
- Pack contents are immutable after installation (identified by content digest).
- Packs may declare dependencies on other packs with version ranges.
