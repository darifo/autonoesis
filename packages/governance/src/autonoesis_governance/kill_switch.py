"""In-memory Kill Switch store implementation.

See docs/runbooks/kill-switch.md for operational procedures.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from autonoesis_runtime import (
    KillSwitchDimension,
    KillSwitchQuery,
    KillSwitchRecord,
)


class InMemoryKillSwitchStore:
    """Thread-unsafe in-memory kill switch store for testing and single-process dev."""

    def __init__(self) -> None:
        self._active: dict[tuple[KillSwitchDimension, str], KillSwitchRecord] = {}

    async def is_blocked(self, query: KillSwitchQuery) -> bool:
        return any((dim, target) in self._active for dim, target in query.dimensions())

    async def activate(
        self,
        dimension: KillSwitchDimension,
        target: str,
        reason: str,
        activated_by: str,
    ) -> KillSwitchRecord:
        record = KillSwitchRecord(
            kill_switch_id=uuid4(),
            dimension=dimension,
            target=target,
            reason=reason,
            activated_by=activated_by,
            activated_at=datetime.now(UTC),
        )
        self._active[(dimension, target)] = record
        return record

    async def deactivate(
        self,
        dimension: KillSwitchDimension,
        target: str,
    ) -> KillSwitchRecord | None:
        key = (dimension, target)
        record = self._active.pop(key, None)
        if record is not None:
            record = KillSwitchRecord(
                kill_switch_id=record.kill_switch_id,
                dimension=record.dimension,
                target=record.target,
                reason=record.reason,
                activated_by=record.activated_by,
                activated_at=record.activated_at,
                deactivated_at=datetime.now(UTC),
            )
        return record

    async def list_active(self) -> tuple[KillSwitchRecord, ...]:
        return tuple(self._active.values())
