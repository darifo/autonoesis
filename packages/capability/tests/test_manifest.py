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
    with pytest.raises(ManifestError, match="subset of"):
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
        "evaluation_subject": manifest.evaluation_subject,
    }
    with pytest.raises(ManifestError, match="owned"):
        parse_manifest(malicious)

    unowned_subject = {
        **malicious,
        "python_entry_point": manifest.python_entry_point,
        "evaluation_subject": "os:system",
    }
    with pytest.raises(ManifestError, match="owned"):
        parse_manifest(unowned_subject)

    entry_point = EntryPoint(
        name=manifest.pack_id,
        value=manifest.python_entry_point,
        group="autonoesis.capability_packs",
    )
    with pytest.raises(ManifestError, match="installed distribution"):
        validate_discovered_plugin(manifest, DiscoveredPlugin(manifest.pack_id, entry_point))


class TestSupplyChainFields:
    def _raw(self, **overrides: object) -> dict[str, object]:
        raw: dict[str, object] = {
            "api_version": "autonoesis/v1alpha1",
            "pack_id": "supply-demo",
            "version": "1.2.3",
            "python_entry_point": "supply_demo.plugin:create",
            "goal_types": [
                {
                    "goal_type": "supply-demo.run",
                    "input_schema": {"type": "object"},
                    "agent": "demo-agent",
                    "evaluation_suite": "demo-suite",
                    "default_policy": "demo-policy",
                    "default_budget": 10,
                }
            ],
            "skills": [],
            "tools": [],
            "policies": ["demo-policy"],
            "evaluation_suites": ["demo-suite"],
        }
        raw.update(overrides)
        return raw

    def test_supply_chain_fields_round_trip(self) -> None:
        from autonoesis_capability import manifest_content_digest, manifest_payload, parse_manifest

        raw = self._raw(
            artifact_uri="artifact://packs/supply-demo/1.2.3",
            artifact_digest="a" * 64,
            signature="b" * 128,
            sbom_ref="sbom://packs/supply-demo/cyclonedx",
            sbom_digest="c" * 64,
            dependencies=[{"pack_id": "other-pack", "version_spec": ">=1.0.0"}],
        )
        manifest = parse_manifest(raw)
        assert manifest.artifact_digest == "a" * 64
        assert manifest.dependencies[0].pack_id == "other-pack"
        rebuilt = parse_manifest(manifest_payload(manifest))
        assert rebuilt == manifest
        assert manifest_content_digest(rebuilt) == manifest_content_digest(manifest)

    def test_malformed_supply_chain_fields_are_rejected(self) -> None:
        from autonoesis_capability import parse_manifest

        with pytest.raises(ManifestError, match="artifact_uri"):
            parse_manifest(self._raw(artifact_uri="not a uri"))
        with pytest.raises(ManifestError, match="artifact_digest"):
            parse_manifest(self._raw(artifact_digest="XYZ"))
        with pytest.raises(ManifestError, match="signature"):
            parse_manifest(self._raw(signature="a" * 64))
        with pytest.raises(ManifestError, match="sbom_ref"):
            parse_manifest(self._raw(sbom_ref=""))
        with pytest.raises(ManifestError, match="version spec"):
            parse_manifest(self._raw(dependencies=[{"pack_id": "other", "version_spec": "latest"}]))

    def test_content_digest_is_stable_across_metadata_attachment(self) -> None:
        from dataclasses import replace

        from autonoesis_capability import manifest_content_digest, parse_manifest
        from autonoesis_capability.signing import supply_chain_fields

        manifest = parse_manifest(self._raw())
        signed = supply_chain_fields(
            manifest,
            private_key_hex=_dev_key(),
            sbom_ref="sbom://packs/supply-demo/cyclonedx",
            sbom_digest="d" * 64,
        )
        assert manifest_content_digest(signed) == manifest_content_digest(manifest)
        assert replace(signed, artifact_uri="artifact://elsewhere/1") is not None
        assert manifest_content_digest(
            replace(signed, artifact_uri="artifact://elsewhere/1")
        ) == manifest_content_digest(manifest)


def _dev_key() -> str:
    from autonoesis_capability.signing import generate_signing_key

    return generate_signing_key()


class TestVersionSpecs:
    @pytest.mark.parametrize(
        ("spec", "version", "expected"),
        [
            ("1.2.3", "1.2.3", True),
            ("=1.2.3", "1.2.4", False),
            (">=1.0.0", "1.9.9", True),
            (">=2.0.0", "1.9.9", False),
            ("<2.0.0", "1.9.9", True),
            ("<2.0.0", "2.0.0", False),
            (">0.1.0", "0.1.0", False),
            ("*", "0.0.1", True),
            (">=1.0.0", "2.0.0-rc.1", True),
        ],
    )
    def test_version_satisfies(self, spec: str, version: str, expected: bool) -> None:
        from autonoesis_capability import version_satisfies

        assert version_satisfies(spec, version) is expected

    def test_prerelease_sorts_before_release(self) -> None:
        from autonoesis_capability import compare_versions

        assert compare_versions("1.0.0-rc.1", "1.0.0") == -1
        assert compare_versions("1.0.0", "0.9.9") == 1
        assert compare_versions("1.0.0", "1.0.0") == 0
