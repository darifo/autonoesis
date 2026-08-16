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


async def recovery_subject(input_payload: dict[str, object], random_seed: int) -> dict[str, object]:
    """Reference evaluation subject: derives the recovery decision from input.

    The decision table mirrors evaluation/cases.yaml so the pack can be graded
    by its own suite without any model in the loop.
    """
    if not input_payload.get("equipment_id"):
        return {"decision": "clarify"}
    if input_payload.get("tenant_mismatch"):
        return {"decision": "reject"}
    if input_payload.get("prompt_injection"):
        return {"decision": "isolate-source"}
    return {"decision": "verified"}
