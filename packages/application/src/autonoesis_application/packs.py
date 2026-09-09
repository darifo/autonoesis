"""Governed Capability Pack install, lifecycle, and tenant channel use cases."""

from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from autonoesis_capability import (
    CapabilityPackManifest,
    version_satisfies,
)
from autonoesis_capability.manifest import manifest_content_digest

from autonoesis_application.platform import IdentityContext


class PackArtifactVerifier(Protocol):
    """Supply-chain gate consulted before any pack may be installed."""

    async def verify_install(self, manifest: CapabilityPackManifest) -> None: ...


class CapabilityPackStore(Protocol):
    """Persistence port for tenant-scoped pack records and stable channels."""

    async def install_pack(
        self,
        tenant_id: UUID,
        manifest: CapabilityPackManifest,
        *,
        actor_id: UUID | None = None,
    ) -> None: ...

    async def list_capability_packs(
        self, tenant_id: UUID, *, include_disabled: bool = False
    ) -> tuple[CapabilityPackManifest, ...]: ...

    async def get_installed_pack(
        self, tenant_id: UUID, pack_id: str, version: str
    ) -> CapabilityPackManifest | None: ...

    async def is_pack_revoked(self, tenant_id: UUID, pack_id: str, version: str) -> bool: ...

    async def set_pack_enabled(
        self,
        tenant_id: UUID,
        pack_id: str,
        version: str,
        enabled: bool,
        *,
        actor_id: UUID,
        reason: str,
    ) -> None: ...

    async def revoke_pack(
        self,
        tenant_id: UUID,
        pack_id: str,
        version: str,
        *,
        actor_id: UUID,
        reason: str,
    ) -> None: ...

    async def set_stable_channel(
        self, tenant_id: UUID, pack_id: str, version: str, *, actor_id: UUID
    ) -> None: ...

    async def get_stable_channel(self, tenant_id: UUID, pack_id: str) -> str | None: ...


@dataclass(frozen=True, slots=True)
class PackLifecycleCommand:
    pack_id: str
    version: str
    reason: str = ""


class CapabilityPackService:
    """Install verified packs and govern enablement, revocation, and channels."""

    def __init__(
        self,
        store: CapabilityPackStore,
        verifier: PackArtifactVerifier | None = None,
    ) -> None:
        self._store = store
        self._verifier = verifier

    async def install_pack(
        self,
        identity: IdentityContext,
        manifest: CapabilityPackManifest,
    ) -> CapabilityPackManifest:
        """Verify the supply chain, then persist the pack content-addressed."""
        if self._verifier is None:
            raise PermissionError("capability pack verification is not configured")
        await self._verifier.verify_install(manifest)
        await self._assert_dependencies_available(identity.tenant_id, manifest)
        await self._store.install_pack(identity.tenant_id, manifest, actor_id=identity.actor_id)
        return manifest

    async def disable_pack(
        self,
        identity: IdentityContext,
        command: PackLifecycleCommand,
    ) -> None:
        self._require_reason(command.reason)
        await self._store.set_pack_enabled(
            identity.tenant_id,
            command.pack_id,
            command.version,
            False,
            actor_id=identity.actor_id,
            reason=command.reason,
        )

    async def enable_pack(
        self,
        identity: IdentityContext,
        command: PackLifecycleCommand,
    ) -> None:
        if await self._store.is_pack_revoked(identity.tenant_id, command.pack_id, command.version):
            raise PermissionError("a revoked capability pack cannot be re-enabled")
        await self._store.set_pack_enabled(
            identity.tenant_id,
            command.pack_id,
            command.version,
            True,
            actor_id=identity.actor_id,
            reason=command.reason or "pack re-enabled",
        )

    async def revoke_pack(
        self,
        identity: IdentityContext,
        command: PackLifecycleCommand,
    ) -> None:
        self._require_reason(command.reason)
        await self._store.revoke_pack(
            identity.tenant_id,
            command.pack_id,
            command.version,
            actor_id=identity.actor_id,
            reason=command.reason,
        )

    async def set_stable_channel(
        self,
        identity: IdentityContext,
        command: PackLifecycleCommand,
    ) -> None:
        """Upgrade or downgrade a tenant channel after dependency reconciliation."""
        target = await self._store.get_installed_pack(
            identity.tenant_id, command.pack_id, command.version
        )
        if target is None:
            raise ValueError(
                f"capability pack {command.pack_id}@{command.version} is not installed"
            )
        if await self._store.is_pack_revoked(identity.tenant_id, command.pack_id, command.version):
            raise PermissionError("a revoked capability pack cannot become stable")
        await self._assert_dependencies_available(identity.tenant_id, target)
        await self._assert_no_dependent_breaks(identity.tenant_id, command.pack_id, command.version)
        await self._store.set_stable_channel(
            identity.tenant_id,
            command.pack_id,
            command.version,
            actor_id=identity.actor_id,
        )

    async def _assert_dependencies_available(
        self, tenant_id: UUID, manifest: CapabilityPackManifest
    ) -> None:
        installed = {
            item.pack_id: item for item in await self._store.list_capability_packs(tenant_id)
        }
        for dependency in manifest.dependencies:
            available = installed.get(dependency.pack_id)
            if available is None or not version_satisfies(
                dependency.version_spec, available.version
            ):
                raise ValueError(
                    f"capability pack {manifest.pack_id}@{manifest.version} requires "
                    f"{dependency.pack_id} {dependency.version_spec}, "
                    f"found {available.version if available else 'nothing'}"
                )

    async def _assert_no_dependent_breaks(
        self, tenant_id: UUID, pack_id: str, version: str
    ) -> None:
        for item in await self._store.list_capability_packs(tenant_id):
            for dependency in item.dependencies:
                if dependency.pack_id != pack_id:
                    continue
                if not version_satisfies(dependency.version_spec, version):
                    raise ValueError(
                        f"capability pack {item.pack_id}@{item.version} requires "
                        f"{pack_id} {dependency.version_spec}; channel {version} breaks it"
                    )

    @staticmethod
    def _require_reason(reason: str) -> None:
        if not reason.strip():
            raise ValueError("pack lifecycle operations require a recorded reason")


def pack_content_digest(manifest: CapabilityPackManifest) -> str:
    """Public content-addressing helper for views and audits."""
    return manifest_content_digest(manifest)


__all__ = [
    "CapabilityPackService",
    "CapabilityPackStore",
    "PackArtifactVerifier",
    "PackLifecycleCommand",
    "pack_content_digest",
]
