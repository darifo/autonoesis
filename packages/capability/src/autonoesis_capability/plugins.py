"""Python entry-point discovery for Capability Packs."""

from dataclasses import dataclass
from importlib.metadata import EntryPoint, entry_points
from typing import Protocol, cast

from autonoesis_capability.manifest import CapabilityPackManifest, ManifestError


class CapabilityPackPlugin(Protocol):
    manifest: CapabilityPackManifest

    def register(self, registry: object) -> None: ...


@dataclass(frozen=True, slots=True)
class DiscoveredPlugin:
    name: str
    entry_point: EntryPoint


def discover_plugins() -> tuple[DiscoveredPlugin, ...]:
    discovered: list[DiscoveredPlugin] = []
    for entry_point in entry_points(group="autonoesis.capability_packs"):
        if not entry_point.name or entry_point.name.startswith("_"):
            raise ManifestError("capability entry-point name is not allowed")
        discovered.append(DiscoveredPlugin(name=entry_point.name, entry_point=entry_point))
    return tuple(sorted(discovered, key=lambda item: item.name))


def validate_discovered_plugin(
    manifest: CapabilityPackManifest, discovered: DiscoveredPlugin
) -> None:
    """Validate distribution metadata before importing any capability code."""

    if discovered.name != manifest.pack_id:
        raise ManifestError("entry-point name must match capability pack id")
    if discovered.entry_point.value != manifest.python_entry_point:
        raise ManifestError("installed entry point does not match the manifest")
    distribution = discovered.entry_point.dist
    if distribution is None:
        raise ManifestError("entry point must belong to an installed distribution")
    if distribution.version != manifest.version:
        raise ManifestError("installed distribution version does not match the manifest")


def load_plugin(
    manifest: CapabilityPackManifest, discovered: DiscoveredPlugin
) -> CapabilityPackPlugin:
    validate_discovered_plugin(manifest, discovered)
    factory = discovered.entry_point.load()
    if not callable(factory):
        raise ManifestError("capability entry point must resolve to a factory")
    plugin = factory()
    if getattr(plugin, "manifest", None) != manifest or not callable(
        getattr(plugin, "register", None)
    ):
        raise ManifestError("capability plugin does not match its validated manifest")
    return cast(CapabilityPackPlugin, plugin)
