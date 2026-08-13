# mypy: ignore-errors
"""Tests for memory package."""

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from autonoesis_domain import DataClassification, MemoryRecord, MemoryStatus, TrustLevel
from autonoesis_memory import (
    InMemoryMemoryStore,
    LedgerEntry,
    LedgerEntryKind,
    MemoryLedger,
    MemoryWriteGate,
    MemoryWriteService,
    WriteDecision,
)


def _record(**overrides: object) -> MemoryRecord:
    defaults: dict[str, object] = {
        "tenant_id": uuid4(),
        "content": "test memory",
        "confidence": 0.8,
        "provenance": ("test",),
        "scope": "test",
        "approved_by": uuid4(),
        "expires_at": datetime.now(UTC) + __import__("datetime").timedelta(hours=1),
    }
    defaults.update({k: v for k, v in overrides.items() if v is not None})
    return MemoryRecord(**defaults)  # type: ignore[arg-type]


class TestMemoryWriteGate:
    @pytest.mark.asyncio
    async def test_accepts_valid_record(self) -> None:
        gate = MemoryWriteGate()
        result = await gate.evaluate(_record(), ())
        assert result.decision == WriteDecision.ACCEPT

    @pytest.mark.asyncio
    async def test_rejects_low_confidence(self) -> None:
        gate = MemoryWriteGate(min_confidence=0.5)
        result = await gate.evaluate(_record(confidence=0.2), ())
        assert result.decision == WriteDecision.REJECT

    @pytest.mark.asyncio
    async def test_rejects_untrusted_provenance(self) -> None:
        gate = MemoryWriteGate()
        result = await gate.evaluate(_record(provenance=("untrusted",)), ())
        assert result.decision == WriteDecision.REJECT

    @pytest.mark.asyncio
    async def test_merges_same_provenance(self) -> None:
        gate = MemoryWriteGate()
        existing = _record()
        candidate = _record(provenance=existing.provenance)
        result = await gate.evaluate(candidate, (existing,))
        assert result.decision == WriteDecision.MERGE

    @pytest.mark.asyncio
    async def test_rejects_pii_without_privacy_approval_and_conflicts(self) -> None:
        gate = MemoryWriteGate()
        pii = _record(contains_pii=True, classification=DataClassification.RESTRICTED)
        assert (await gate.evaluate(pii, ())).decision is WriteDecision.REJECT
        existing = _record(conflict_keys=("customer:42:email",)).stabilize()
        candidate = _record(
            conflict_keys=("customer:42:email",),
            content="contradictory value",
        )
        assert (await gate.evaluate(candidate, (existing,))).decision is WriteDecision.REJECT

    @pytest.mark.asyncio
    async def test_write_service_is_only_path_to_stable_memory(self) -> None:
        store, ledger = InMemoryMemoryStore(), MemoryLedger()
        observation = _record(source_trust=TrustLevel.AUTHORITATIVE)
        with pytest.raises(PermissionError, match="Write Gate"):
            await store.store(observation)
        stable = await MemoryWriteService(store, ledger).write(observation, uuid4(), ())
        assert stable.status is MemoryStatus.STABLE
        assert (await ledger.history(stable.memory_id))[0].kind is LedgerEntryKind.WRITE


class TestMemoryLedger:
    @pytest.mark.asyncio
    async def test_records_and_retrieves(self) -> None:
        ledger = MemoryLedger()
        mem_id = uuid4()
        entry = LedgerEntry(
            memory_id=mem_id, kind=LedgerEntryKind.WRITE, tenant_id=uuid4(), actor_id=uuid4()
        )
        await ledger.record(entry)
        history = await ledger.history(mem_id)
        assert len(history) == 1
        assert history[0].kind == LedgerEntryKind.WRITE


class TestInMemoryMemoryStore:
    @pytest.mark.asyncio
    async def test_store_and_retrieve(self) -> None:
        store = InMemoryMemoryStore()
        record = _record()
        await store.store(record.stabilize())
        retrieved = await store.get(record.memory_id)
        assert retrieved is not None
        assert retrieved.content == "test memory"

    @pytest.mark.asyncio
    async def test_delete(self) -> None:
        store = InMemoryMemoryStore()
        record = _record()
        await store.store(record.stabilize())
        await store.delete(record.memory_id)
        assert await store.get(record.memory_id) is None
