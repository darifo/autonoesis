# mypy: ignore-errors
"""Tests for context package."""

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from autonoesis_context import (
    ContextACL,
    ContextAssembler,
    FreshnessGuard,
    FreshnessPolicy,
)
from autonoesis_domain import (
    ContextSnapshot,
    EnvironmentFact,
    KnowledgeRef,
    MemoryRecord,
    TrustLevel,
)


def _fact(**overrides: object) -> EnvironmentFact:
    defaults: dict[str, object] = {
        "fact_id": "f1",
        "source": "test",
        "subject": "test",
        "value": {"val": 1},
        "observed_at": datetime.now(UTC),
        "valid_until": datetime.now(UTC) + timedelta(hours=1),
        "trust": TrustLevel.ADVISORY,
    }
    defaults.update({k: v for k, v in overrides.items() if v is not None})
    return EnvironmentFact(**defaults)


def _memory(**overrides: object) -> MemoryRecord:
    defaults: dict[str, object] = {
        "tenant_id": uuid4(),
        "scope": "test",
        "content": "test memory",
        "provenance": ("test",),
        "confidence": 0.8,
        "expires_at": datetime.now(UTC) + timedelta(hours=1),
        "approved_by": uuid4(),
    }
    defaults.update({k: v for k, v in overrides.items() if v is not None})
    return MemoryRecord(**defaults)


class TestFreshnessGuard:
    def test_fact_is_fresh(self) -> None:
        fact = _fact()
        check = FreshnessGuard.check_fact(fact, max_age_seconds=600)
        assert check.passed is True

    def test_fact_is_stale(self) -> None:
        fact = _fact(observed_at=datetime.now(UTC) - timedelta(hours=1))
        check = FreshnessGuard.check_fact(fact, max_age_seconds=60)
        assert check.passed is False

    def test_lax_policy_allows_stale(self) -> None:
        fact = _fact(observed_at=datetime.now(UTC) - timedelta(hours=1))
        check = FreshnessGuard.check_fact(fact, max_age_seconds=60, policy=FreshnessPolicy.LAX)
        assert check.passed is True


class TestContextACL:
    def test_full_access_for_trusted(self) -> None:
        ref = KnowledgeRef(
            knowledge_id="k1",
            version="1",
            source="test",
            citation="test",
            trust=TrustLevel.AUTHORITATIVE,
        )
        check = ContextACL.check_access(ref, uuid4(), frozenset({"operator"}))
        assert check.level.value == "use"

    def test_read_only_for_low_trust(self) -> None:
        ref = KnowledgeRef(
            knowledge_id="k1",
            version="1",
            source="test",
            citation="test",
            trust=TrustLevel.UNTRUSTED,
        )
        check = ContextACL.check_access(ref, uuid4(), frozenset({"operator"}))
        assert check.level.value == "read"

    def test_read_only_for_low_confidence_memory(self) -> None:
        mem = _memory(confidence=0.2)
        check = ContextACL.check_access(mem, uuid4(), frozenset({"operator"}))
        assert check.level.value == "read"


class TestContextAssembler:
    @pytest.mark.asyncio
    async def test_assembles_snapshot(self) -> None:
        assembler = ContextAssembler()
        fact = _fact()
        ref = KnowledgeRef(
            knowledge_id="k1",
            version="1",
            source="test",
            citation="test",
            trust=TrustLevel.AUTHORITATIVE,
        )
        mem_id = uuid4()

        snapshot = await assembler.assemble(
            goal_id=uuid4(),
            run_id=uuid4(),
            tenant_id=uuid4(),
            roles=frozenset({"operator"}),
            environment_facts=(fact,),
            knowledge_refs=(ref,),
            memory_ids=(mem_id,),
        )
        assert isinstance(snapshot, ContextSnapshot)
        assert mem_id in snapshot.memory_ids
