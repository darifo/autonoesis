"""Tests for governed Capability Pack lifecycle use cases."""

from typing import Any
from uuid import UUID, uuid4

import pytest
from autonoesis_application import (
    CapabilityPackService,
    IdentityContext,
    PackLifecycleCommand,
)
from autonoesis_capability import CapabilityPackManifest, parse_manifest

DIGEST = "a" * 64


def _manifest(pack_id: str, version: str, **overrides: Any) -> CapabilityPackManifest:
    raw: dict[str, Any] = {
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
    }
    raw.update(overrides)
    return parse_manifest(raw)


class FakePackStore:
    def __init__(self) -> None:
        self.packs: dict[tuple[UUID, str, str], CapabilityPackManifest] = {}
        self.states: dict[tuple[UUID, str, str], dict[str, bool]] = {}
        self.channels: dict[tuple[UUID, str], str] = {}
        self.events: list[str] = []

    async def install_pack(
        self,
        tenant_id: UUID,
        manifest: CapabilityPackManifest,
        *,
        actor_id: UUID | None = None,
    ) -> None:
        self.packs[(tenant_id, manifest.pack_id, manifest.version)] = manifest
        self.states.setdefault(
            (tenant_id, manifest.pack_id, manifest.version), {"enabled": True, "revoked": False}
        )
        self.events.append("installed")

    async def list_capability_packs(
        self, tenant_id: UUID, *, include_disabled: bool = False
    ) -> tuple[CapabilityPackManifest, ...]:
        return tuple(
            item
            for (item_tenant, _, _), item in self.packs.items()
            if item_tenant == tenant_id
            and (
                include_disabled
                or self.states.get((item_tenant, item.pack_id, item.version), {}).get(
                    "enabled", True
                )
            )
        )

    async def get_installed_pack(
        self, tenant_id: UUID, pack_id: str, version: str
    ) -> CapabilityPackManifest | None:
        return self.packs.get((tenant_id, pack_id, version))

    async def is_pack_revoked(self, tenant_id: UUID, pack_id: str, version: str) -> bool:
        return self.states.get((tenant_id, pack_id, version), {}).get("revoked", False)

    async def set_pack_enabled(
        self,
        tenant_id: UUID,
        pack_id: str,
        version: str,
        enabled: bool,
        *,
        actor_id: UUID,
        reason: str,
    ) -> None:
        self.states.setdefault((tenant_id, pack_id, version), {})
        self.states[(tenant_id, pack_id, version)]["enabled"] = enabled
        self.events.append("enabled" if enabled else "disabled")

    async def revoke_pack(
        self,
        tenant_id: UUID,
        pack_id: str,
        version: str,
        *,
        actor_id: UUID,
        reason: str,
    ) -> None:
        self.states.setdefault((tenant_id, pack_id, version), {})
        self.states[(tenant_id, pack_id, version)]["revoked"] = True
        self.states[(tenant_id, pack_id, version)]["enabled"] = False
        self.events.append("revoked")

    async def set_stable_channel(
        self, tenant_id: UUID, pack_id: str, version: str, *, actor_id: UUID
    ) -> None:
        self.channels[(tenant_id, pack_id)] = version
        self.events.append("channel")

    async def get_stable_channel(self, tenant_id: UUID, pack_id: str) -> str | None:
        return self.channels.get((tenant_id, pack_id))


class AcceptingVerifier:
    def __init__(self) -> None:
        self.calls: list[str] = []

    async def verify_install(self, manifest: CapabilityPackManifest) -> None:
        self.calls.append(manifest.pack_id)


class RejectingVerifier:
    async def verify_install(self, manifest: CapabilityPackManifest) -> None:
        raise PermissionError(f"pack rejected: {manifest.pack_id}")


def identity(tenant_id: UUID) -> IdentityContext:
    return IdentityContext(tenant_id, uuid4(), uuid4(), frozenset({"tenant_admin"}))


@pytest.mark.asyncio
async def test_install_requires_a_configured_verifier() -> None:
    store = FakePackStore()
    service = CapabilityPackService(store)
    with pytest.raises(PermissionError, match="verification is not configured"):
        await service.install_pack(identity(uuid4()), _manifest("demo-pack", "1.0.0"))
    assert not store.packs


@pytest.mark.asyncio
async def test_install_verifies_then_persists_with_actor() -> None:
    store = FakePackStore()
    verifier = AcceptingVerifier()
    service = CapabilityPackService(store, verifier)
    context = identity(uuid4())
    manifest = _manifest("demo-pack", "1.0.0")
    installed = await service.install_pack(context, manifest)
    assert installed is manifest
    assert verifier.calls == ["demo-pack"]
    assert store.packs[(context.tenant_id, "demo-pack", "1.0.0")] is manifest


@pytest.mark.asyncio
async def test_rejected_pack_never_persists() -> None:
    store = FakePackStore()
    service = CapabilityPackService(store, RejectingVerifier())
    with pytest.raises(PermissionError, match="rejected"):
        await service.install_pack(identity(uuid4()), _manifest("demo-pack", "1.0.0"))
    assert not store.packs


@pytest.mark.asyncio
async def test_channel_requires_installed_and_unrevoked_target() -> None:
    store = FakePackStore()
    service = CapabilityPackService(store)
    context = identity(uuid4())
    with pytest.raises(ValueError, match="not installed"):
        await service.set_stable_channel(context, PackLifecycleCommand("demo-pack", "2.0.0"))
    await store.install_pack(context.tenant_id, _manifest("demo-pack", "2.0.0"))
    await store.revoke_pack(
        context.tenant_id, "demo-pack", "2.0.0", actor_id=uuid4(), reason="supply incident"
    )
    with pytest.raises(PermissionError, match="revoked"):
        await service.set_stable_channel(context, PackLifecycleCommand("demo-pack", "2.0.0"))


@pytest.mark.asyncio
async def test_channel_rejects_broken_dependencies_and_dependents() -> None:
    store = FakePackStore()
    service = CapabilityPackService(store)
    context = identity(uuid4())
    tenant = context.tenant_id
    await store.install_pack(tenant, _manifest("base-pack", "1.0.0"))
    await store.install_pack(tenant, _manifest("base-pack", "2.0.0"))
    await store.install_pack(
        tenant,
        _manifest(
            "top-pack",
            "1.0.0",
            dependencies=[{"pack_id": "base-pack", "version_spec": ">=1.0.0 <2.0.0"}],
        ),
    )
    await store.set_stable_channel(tenant, "base-pack", "1.0.0", actor_id=uuid4())
    # Upgrading base to 2.0.0 breaks top-pack's declared range.
    with pytest.raises(ValueError, match="breaks it"):
        await service.set_stable_channel(context, PackLifecycleCommand("base-pack", "2.0.0"))
    # A pack with unsatisfied dependencies cannot be installed or pinned.
    await store.install_pack(
        tenant,
        _manifest(
            "missing-dep", "1.0.0", dependencies=[{"pack_id": "absent", "version_spec": "*"}]
        ),
    )
    with pytest.raises(ValueError, match="requires absent"):
        await service.set_stable_channel(context, PackLifecycleCommand("missing-dep", "1.0.0"))


@pytest.mark.asyncio
async def test_revoked_pack_cannot_be_reenabled() -> None:
    store = FakePackStore()
    service = CapabilityPackService(store)
    context = identity(uuid4())
    await store.install_pack(context.tenant_id, _manifest("demo-pack", "1.0.0"))
    await service.revoke_pack(
        context, PackLifecycleCommand("demo-pack", "1.0.0", "supply chain incident")
    )
    with pytest.raises(PermissionError, match="cannot be re-enabled"):
        await service.enable_pack(context, PackLifecycleCommand("demo-pack", "1.0.0"))


@pytest.mark.asyncio
async def test_lifecycle_operations_require_reasons() -> None:
    store = FakePackStore()
    service = CapabilityPackService(store)
    context = identity(uuid4())
    with pytest.raises(ValueError, match="reason"):
        await service.disable_pack(context, PackLifecycleCommand("demo-pack", "1.0.0"))
    with pytest.raises(ValueError, match="reason"):
        await service.revoke_pack(context, PackLifecycleCommand("demo-pack", "1.0.0"))
