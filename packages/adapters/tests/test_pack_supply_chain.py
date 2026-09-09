"""Tests for Capability Pack supply-chain verification and sandboxed execution."""

from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest
from autonoesis_adapters import (
    InMemoryPlatformStore,
    SandboxedPackSubjectRuntime,
    StrictSupplyChainVerifier,
)
from autonoesis_application import IdentityContext, RecordNotFound
from autonoesis_capability import parse_manifest
from autonoesis_capability.signing import (
    generate_signing_key,
    public_key_hex,
    supply_chain_fields,
)


def _raw_manifest(pack_id: str, version: str) -> dict[str, Any]:
    return {
        "api_version": "autonoesis/v1alpha1",
        "pack_id": pack_id,
        "version": version,
        "python_entry_point": f"{pack_id.replace('-', '_')}.plugin:create",
        "goal_types": [
            {
                "goal_type": f"{pack_id}.run",
                "input_schema": {"type": "object"},
                "agent": "agent-1",
                "evaluation_suite": "suite-1",
                "default_policy": "policy-1",
                "default_budget": 10,
            }
        ],
        "skills": [],
        "tools": [],
        "policies": ["policy-1"],
        "evaluation_suites": ["suite-1"],
        "evaluation_subject": f"{pack_id.replace('-', '_')}.plugin:subject",
    }


def _signed(pack_id: str, version: str, key: str) -> Any:
    return supply_chain_fields(
        parse_manifest(_raw_manifest(pack_id, version)),
        private_key_hex=key,
        sbom_ref="sbom://packs/test/cyclonedx",
        sbom_digest="e" * 64,
    )


@pytest.fixture()
def dev_key() -> str:
    return generate_signing_key()


@pytest.fixture()
def verifier(dev_key: str) -> StrictSupplyChainVerifier:
    return StrictSupplyChainVerifier(
        allowed_sources=("artifact://packs/",),
        public_keys_hex=(public_key_hex(dev_key),),
    )


@pytest.mark.asyncio
async def test_signed_pack_from_allowlisted_source_passes(
    verifier: StrictSupplyChainVerifier, dev_key: str
) -> None:
    await verifier.verify_install(_signed("demo-pack", "1.0.0", dev_key))


@pytest.mark.asyncio
async def test_unsigned_or_foreign_key_packs_fail_closed(
    verifier: StrictSupplyChainVerifier, dev_key: str
) -> None:
    unsigned = parse_manifest(_raw_manifest("demo-pack", "1.0.0"))
    with pytest.raises(PermissionError, match="artifact URI"):
        await verifier.verify_install(unsigned)
    foreign = _signed("demo-pack", "1.0.0", generate_signing_key())
    with pytest.raises(PermissionError, match="signature"):
        await verifier.verify_install(foreign)


@pytest.mark.asyncio
async def test_tampered_content_fails_digest_verification(
    verifier: StrictSupplyChainVerifier, dev_key: str
) -> None:
    from dataclasses import replace

    signed = _signed("demo-pack", "1.0.0", dev_key)
    tampered = replace(
        signed,
        goal_types=(replace(signed.goal_types[0], default_budget=999999),),
    )
    with pytest.raises(PermissionError, match="digest mismatch"):
        await verifier.verify_install(tampered)


@pytest.mark.asyncio
async def test_disallowed_source_fails_closed(dev_key: str) -> None:
    verifier = StrictSupplyChainVerifier(
        allowed_sources=("artifact://trusted-registry/",),
        public_keys_hex=(public_key_hex(dev_key),),
    )
    signed = supply_chain_fields(
        parse_manifest(_raw_manifest("demo-pack", "1.0.0")),
        private_key_hex=dev_key,
        sbom_ref="sbom://packs/test/cyclonedx",
        sbom_digest="e" * 64,
        artifact_uri="artifact://evil.example/demo/1.0.0",
    )
    with pytest.raises(PermissionError, match="not allowlisted"):
        await verifier.verify_install(signed)


@pytest.mark.asyncio
async def test_missing_sbom_fails_closed(verifier: StrictSupplyChainVerifier, dev_key: str) -> None:
    from dataclasses import replace

    signed = _signed("demo-pack", "1.0.0", dev_key)
    with pytest.raises(PermissionError, match=r"does not verify|SBOM"):
        await verifier.verify_install(replace(signed, sbom_ref=None))


@pytest.mark.asyncio
async def test_same_version_different_content_is_a_conflict(dev_key: str) -> None:
    from autonoesis_capability import manifest_payload

    store = InMemoryPlatformStore()
    tenant = uuid4()
    manifest = _signed("demo-pack", "1.0.0", dev_key)
    await store.install_pack(tenant, manifest)
    tampered = parse_manifest({**manifest_payload(manifest), "policies": ["sneaky-policy"]})
    with pytest.raises(ValueError, match="content conflict"):
        await store.install_pack(tenant, tampered)
    # An identical resubmission stays idempotent.
    await store.install_pack(tenant, manifest)


@pytest.mark.asyncio
async def test_pack_lifecycle_and_channels_in_memory(dev_key: str) -> None:
    store = InMemoryPlatformStore()
    tenant = uuid4()
    identity = IdentityContext(tenant, uuid4(), uuid4(), frozenset({"tenant_admin"}))
    await store.install_pack(tenant, _signed("demo-pack", "1.0.0", dev_key))
    await store.install_pack(tenant, _signed("demo-pack", "2.0.0", dev_key))
    await store.set_stable_channel(tenant, "demo-pack", "2.0.0", actor_id=identity.actor_id)
    assert await store.get_stable_channel(tenant, "demo-pack") == "2.0.0"
    assert await store.get_goal_type(tenant, "demo-pack.run")
    # A channel pinned to a disabled version fails closed: no silent fallback.
    await store.set_pack_enabled(
        tenant,
        "demo-pack",
        "2.0.0",
        False,
        actor_id=identity.actor_id,
        reason="incident review",
    )
    with pytest.raises(RecordNotFound):
        await store.get_goal_type(tenant, "demo-pack.run")
    await store.set_pack_enabled(
        tenant,
        "demo-pack",
        "2.0.0",
        True,
        actor_id=identity.actor_id,
        reason="incident cleared",
    )
    # Unpinned enabled versions stop serving once a channel exists.
    await store.set_pack_enabled(
        tenant,
        "demo-pack",
        "1.0.0",
        False,
        actor_id=identity.actor_id,
        reason="old version retired",
    )
    assert await store.get_goal_type(tenant, "demo-pack.run")
    await store.revoke_pack(
        tenant, "demo-pack", "2.0.0", actor_id=identity.actor_id, reason="supply incident"
    )
    assert await store.is_pack_revoked(tenant, "demo-pack", "2.0.0")
    events = [event.event_type for event in store.audits]
    assert "capability_pack.installed" not in events  # InMemory audits are explicit
    assert "capability_pack.disabled" in events
    assert "capability_pack.revoked" in events
    assert "capability_pack.channel_updated" in events


@pytest.mark.asyncio
async def test_sandboxed_runtime_executes_subject_in_subprocess(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pack_module = tmp_path / "sandbox_demo_pack"
    pack_module.mkdir()
    (pack_module / "plugin.py").write_text(
        "def subject(input_payload, random_seed):\n"
        '    return {"doubled": input_payload["value"] * 2, "seeded": random_seed > 0}\n'
    )
    _prepend_pythonpath(monkeypatch, tmp_path)

    store = InMemoryPlatformStore()
    tenant = uuid4()
    manifest = parse_manifest(_raw_manifest("sandbox-demo-pack", "1.0.0"))
    await store.add_capability_pack(tenant, manifest)
    runtime = SandboxedPackSubjectRuntime(store, timeout_seconds=15)

    result = await runtime.execute_artifact(
        "pack://sandbox-demo-pack/1.0.0", tenant, uuid4(), {"value": 21}, 7
    )
    assert result.output_payload == {"doubled": 42, "seeded": True}
    assert result.executor_id == "sandboxed-pack-subject-runtime@1"
    assert "pack-sandbox" in result.environment_ref


@pytest.mark.asyncio
async def test_sandboxed_runtime_fails_closed_on_crash_and_timeout(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pack_module = tmp_path / "crash_demo_pack"
    pack_module.mkdir()
    (pack_module / "plugin.py").write_text(
        "def subject(input_payload, random_seed):\n    raise RuntimeError('boom')\n"
    )
    _prepend_pythonpath(monkeypatch, tmp_path)
    store = InMemoryPlatformStore()
    tenant = uuid4()
    await store.add_capability_pack(
        tenant, parse_manifest(_raw_manifest("crash-demo-pack", "1.0.0"))
    )

    runtime = SandboxedPackSubjectRuntime(store, timeout_seconds=10)
    with pytest.raises(RuntimeError, match="sandboxed subject failed"):
        await runtime.execute_artifact("pack://crash-demo-pack/1.0.0", tenant, uuid4(), {}, 1)

    hang_module = tmp_path / "hang_demo_pack"
    hang_module.mkdir()
    (hang_module / "plugin.py").write_text(
        "import time\ndef subject(input_payload, random_seed):\n    time.sleep(30)\n    return {}\n"
    )
    await store.add_capability_pack(
        tenant, parse_manifest(_raw_manifest("hang-demo-pack", "1.0.0"))
    )
    tight = SandboxedPackSubjectRuntime(store, timeout_seconds=1)
    with pytest.raises(RuntimeError, match="timed out"):
        await tight.execute_artifact("pack://hang-demo-pack/1.0.0", tenant, uuid4(), {}, 1)


def _prepend_pythonpath(monkeypatch: pytest.MonkeyPatch, path: Path) -> None:
    import os

    existing = os.environ.get("PYTHONPATH", "")
    monkeypatch.setenv("PYTHONPATH", f"{path}{os.pathsep}{existing}" if existing else str(path))


def test_verifier_requires_configuration() -> None:
    with pytest.raises(ValueError, match="allowed source"):
        StrictSupplyChainVerifier(allowed_sources=(), public_keys_hex=("ab" * 32,))
    with pytest.raises(ValueError, match="public key"):
        StrictSupplyChainVerifier(allowed_sources=("artifact://packs/",), public_keys_hex=())
