"""Memory SPI, ledger, write gate, and deletion propagation for Autonoesis."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Protocol
from uuid import UUID, uuid4

from autonoesis_domain import MemoryRecord

# ── Write Gate ──────────────────────────────────────────────────────────────


class WriteDecision(StrEnum):
    ACCEPT = "accept"
    REJECT = "reject"
    MERGE = "merge"


@dataclass(frozen=True, slots=True)
class WriteGateResult:
    decision: WriteDecision
    reason: str = ""
    existing_record_id: UUID | None = None


class MemoryWriteGate:
    """Decides whether a new MemoryRecord should be accepted, rejected, or merged.

    Rules:
    - Reject records with confidence below threshold.
    - Merge records that update an existing memory (same provenance, newer observation).
    - Reject records from untrusted sources.
    """

    def __init__(self, min_confidence: float = 0.3) -> None:
        self._min_confidence = min_confidence

    async def evaluate(
        self,
        candidate: MemoryRecord,
        existing: tuple[MemoryRecord, ...],
    ) -> WriteGateResult:
        if candidate.confidence < self._min_confidence:
            return WriteGateResult(WriteDecision.REJECT, "confidence below threshold")
        if set(candidate.provenance) & {"untrusted", "unknown"}:
            return WriteGateResult(WriteDecision.REJECT, "untrusted provenance")
        for ex in existing:
            if ex.provenance == candidate.provenance and ex.memory_id != candidate.memory_id:
                return WriteGateResult(
                    WriteDecision.MERGE,
                    "merging update from same provenance",
                    ex.memory_id,
                )
        return WriteGateResult(WriteDecision.ACCEPT, "new memory accepted")


# ── Ledger ──────────────────────────────────────────────────────────────────


class LedgerEntryKind(StrEnum):
    WRITE = "write"
    MERGE = "merge"
    DELETE = "delete"


@dataclass(frozen=True, slots=True)
class LedgerEntry:
    entry_id: UUID = field(default_factory=uuid4)
    memory_id: UUID = field(default_factory=uuid4)
    kind: LedgerEntryKind = LedgerEntryKind.WRITE
    tenant_id: UUID = field(default_factory=uuid4)
    actor_id: UUID = field(default_factory=uuid4)
    recorded_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    metadata: dict[str, str] = field(default_factory=dict)


class MemoryLedger:
    """Append-only log of all memory mutations for audit and replay."""

    def __init__(self) -> None:
        self._entries: list[LedgerEntry] = []

    async def record(self, entry: LedgerEntry) -> None:
        self._entries.append(entry)

    async def history(self, memory_id: UUID) -> tuple[LedgerEntry, ...]:
        return tuple(e for e in self._entries if e.memory_id == memory_id)


# ── SPI ─────────────────────────────────────────────────────────────────────


class MemoryStorePort(Protocol):
    """Abstract memory storage backend."""

    async def store(self, record: MemoryRecord) -> None: ...
    async def get(self, memory_id: UUID) -> MemoryRecord | None: ...
    async def delete(self, memory_id: UUID) -> None: ...
    async def search(
        self, tenant_id: UUID, context: str, limit: int
    ) -> tuple[MemoryRecord, ...]: ...


class InMemoryMemoryStore:
    """Thread-unsafe in-memory implementation of MemoryStorePort."""

    def __init__(self) -> None:
        self._records: dict[UUID, MemoryRecord] = {}

    async def store(self, record: MemoryRecord) -> None:
        self._records[record.memory_id] = record

    async def get(self, memory_id: UUID) -> MemoryRecord | None:
        return self._records.get(memory_id)

    async def delete(self, memory_id: UUID) -> None:
        self._records.pop(memory_id, None)

    async def search(
        self, tenant_id: UUID, context: str, limit: int = 10
    ) -> tuple[MemoryRecord, ...]:
        results = [
            r
            for r in self._records.values()
            if r.tenant_id == tenant_id and context.lower() in r.content.lower()
        ]
        return tuple(results[:limit])


# ── Deletion Propagation ────────────────────────────────────────────────────


class DeletionPropagator:
    """Ensures cascading deletion of related memories when a parent is removed.

    In a full implementation this would:
    1. Find all memories that reference the deleted memory.
    2. Mark them for review or cascade the deletion.
    3. Record the cascade in the ledger.
    """

    def __init__(self, store: MemoryStorePort, ledger: MemoryLedger) -> None:
        self._store = store
        self._ledger = ledger

    async def cascade_delete(self, memory_id: UUID, actor_id: UUID, tenant_id: UUID) -> int:
        record = await self._store.get(memory_id)
        if record is None:
            return 0
        await self._store.delete(memory_id)
        await self._ledger.record(
            LedgerEntry(
                memory_id=memory_id,
                kind=LedgerEntryKind.DELETE,
                tenant_id=tenant_id,
                actor_id=actor_id,
            )
        )
        return 1


__all__ = [
    "DeletionPropagator",
    "InMemoryMemoryStore",
    "LedgerEntry",
    "LedgerEntryKind",
    "MemoryLedger",
    "MemoryStorePort",
    "MemoryWriteGate",
    "WriteDecision",
    "WriteGateResult",
]
