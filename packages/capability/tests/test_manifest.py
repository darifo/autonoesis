from importlib.metadata import EntryPoint
from pathlib import Path

import pytest
from autonoesis_capability import (
    DiscoveredPlugin,
    ManifestError,
    load_manifest,
    parse_manifest,
    validate_discovered_plugin,
    validate_payload,
)


def test_field_service_manifest_has_ten_evaluation_cases() -> None:
    root = Path(__file__).resolve().parents[3]
    manifest = load_manifest(root / "examples/field-service/capability-pack.yaml")
    cases = (root / "examples/field-service/evaluation/cases.yaml").read_text()
    assert manifest.pack_id == "field-service"
    assert cases.count("  - {id:") == 10


def test_manifest_rejects_unknown_fields_and_invalid_payload() -> None:
    with pytest.raises(ManifestError, match="exactly"):
        parse_manifest({"api_version": "autonoesis/v1alpha1", "unexpected": True})
    root = Path(__file__).resolve().parents[3]
    manifest = load_manifest(root / "examples/field-service/capability-pack.yaml")
    with pytest.raises(ManifestError, match="required"):
        validate_payload(manifest.goal_types[0], {"customer_id": "C-1"})


def test_manifest_rejects_unowned_or_unversioned_entry_points() -> None:
    root = Path(__file__).resolve().parents[3]
    manifest = load_manifest(root / "examples/field-service/capability-pack.yaml")
    malicious = {
        "api_version": manifest.api_version,
        "pack_id": manifest.pack_id,
        "version": manifest.version,
        "python_entry_point": "os:system",
        "goal_types": [
            {
                "goal_type": item.goal_type,
                "input_schema": item.input_schema,
                "agent": item.agent,
                "evaluation_suite": item.evaluation_suite,
                "default_policy": item.default_policy,
                "default_budget": item.default_budget,
            }
            for item in manifest.goal_types
        ],
        "skills": list(manifest.skills),
        "tools": list(manifest.tools),
        "policies": list(manifest.policies),
        "evaluation_suites": list(manifest.evaluation_suites),
    }
    with pytest.raises(ManifestError, match="owned"):
        parse_manifest(malicious)

    entry_point = EntryPoint(
        name=manifest.pack_id,
        value=manifest.python_entry_point,
        group="autonoesis.capability_packs",
    )
    with pytest.raises(ManifestError, match="installed distribution"):
        validate_discovered_plugin(manifest, DiscoveredPlugin(manifest.pack_id, entry_point))
