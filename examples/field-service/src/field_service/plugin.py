"""Field Service plugin implemented only through public Autonoesis contracts."""

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol
from uuid import uuid4

from autonoesis_capability import CapabilityPackManifest, load_manifest
from autonoesis_domain import Action
from autonoesis_runtime import ToolReceipt, ToolResultStatus


@dataclass(slots=True)
class FieldServicePlugin:
    manifest: CapabilityPackManifest

    def register(self, registry: "PackRegistry") -> None:
        registry.register_pack(self.manifest)


class PackRegistry(Protocol):
    def register_pack(self, manifest: CapabilityPackManifest) -> None: ...


class FakeRepairOrderTool:
    """Idempotency is enforced by the platform gateway, not this example tool."""

    def __init__(self) -> None:
        self.orders: dict[str, tuple[str, str]] = {}

    async def execute(self, action: Action) -> ToolReceipt:
        parameters = action.parameters.to_value()
        external_id = f"WO-{str(uuid4()).split('-')[0].upper()}"
        self.orders[external_id] = (parameters["equipment_id"], "open")
        return ToolReceipt(external_id, ToolResultStatus.SUCCEEDED, (("status", "open"),))

    async def verify(self, action: Action, receipt: ToolReceipt) -> bool:
        equipment_id, status = self.orders.get(receipt.external_id, ("", "missing"))
        return equipment_id == action.parameters.to_value()["equipment_id"] and status == "open"


def create_plugin() -> FieldServicePlugin:
    root = Path(__file__).resolve().parents[2]
    return FieldServicePlugin(load_manifest(root / "capability-pack.yaml"))
