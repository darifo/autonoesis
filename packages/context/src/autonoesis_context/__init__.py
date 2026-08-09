"""Retrieval, ACL, freshness, conflict, compression, and snapshot for Autonoesis."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from uuid import UUID

from autonoesis_domain import (
    ContextSnapshot,
    EnvironmentFact,
    KnowledgeRef,
    MemoryRecord,
    TrustLevel,
)

# ── Freshness ───────────────────────────────────────────────────────────────


class FreshnessPolicy(StrEnum):
    STRICT = "strict"  # reject stale facts
    WARN = "warn"  # use but flag
    LAX = "lax"  # use without warning


@dataclass(frozen=True, slots=True)
class FreshnessCheck:
    """Result of checking whether a fact/record is still valid."""

    passed: bool
    age_seconds: float
    max_age_seconds: float
    policy: FreshnessPolicy = FreshnessPolicy.STRICT


class FreshnessGuard:
    """Checks whether context items are fresh enough to use."""

    @staticmethod
    def check_fact(
        fact: EnvironmentFact,
        max_age_seconds: float = 300,
        policy: FreshnessPolicy = FreshnessPolicy.STRICT,
    ) -> FreshnessCheck:
        now = datetime.now(UTC)
        age = (now - fact.observed_at).total_seconds()
        passed = age <= max_age_seconds or policy == FreshnessPolicy.LAX
        return FreshnessCheck(
            passed=passed, age_seconds=age, max_age_seconds=max_age_seconds, policy=policy
        )

    @staticmethod
    def check_memory(
        record: MemoryRecord,
        max_age_seconds: float = 3600,
        policy: FreshnessPolicy = FreshnessPolicy.STRICT,
    ) -> FreshnessCheck:
        now = datetime.now(UTC)
        age = 0.0  # MemoryRecord has no observed_at; freshness based on expires_at only
        if record.expires_at is not None and now > record.expires_at:
            return FreshnessCheck(
                passed=False, age_seconds=age, max_age_seconds=max_age_seconds, policy=policy
            )
        passed = age <= max_age_seconds or policy == FreshnessPolicy.LAX
        return FreshnessCheck(
            passed=passed, age_seconds=age, max_age_seconds=max_age_seconds, policy=policy
        )


# ── ACL ─────────────────────────────────────────────────────────────────────


class AccessLevel(StrEnum):
    READ = "read"
    USE = "use"
    NONE = "none"


@dataclass(frozen=True, slots=True)
class ACLCheck:
    allowed: bool
    level: AccessLevel = AccessLevel.NONE
    reason: str = ""


class ContextACL:
    """Enforces access control on context items.

    In production this would check tenant boundaries, data classification,
    and purpose-based access policies.
    """

    @staticmethod
    def check_access(
        item: EnvironmentFact | KnowledgeRef | MemoryRecord,
        tenant_id: UUID,
        roles: frozenset[str],
    ) -> ACLCheck:
        # Knowledge refs with low trust are read-only.
        if isinstance(item, KnowledgeRef) and item.trust in {
            TrustLevel.UNTRUSTED,
            TrustLevel.UNTRUSTED,
        }:
            return ACLCheck(
                allowed=True, level=AccessLevel.READ, reason="low-trust knowledge - read only"
            )

        # Memory with low confidence is read-only.
        if isinstance(item, MemoryRecord) and item.confidence < 0.5:
            return ACLCheck(
                allowed=True, level=AccessLevel.READ, reason="low-confidence memory - read only"
            )

        return ACLCheck(allowed=True, level=AccessLevel.USE, reason="full access")


# ── Assembly ────────────────────────────────────────────────────────────────


class ContextAssembler:
    """Assembles a ContextSnapshot from environment facts, knowledge refs,
    and memory records, applying freshness and ACL checks.
    """

    def __init__(
        self,
        freshness: FreshnessGuard | None = None,
        acl: ContextACL | None = None,
    ) -> None:
        self._freshness = freshness or FreshnessGuard()
        self._acl = acl or ContextACL()

    async def assemble(
        self,
        goal_id: UUID,
        run_id: UUID,
        tenant_id: UUID,
        roles: frozenset[str],
        environment_facts: tuple[EnvironmentFact, ...],
        knowledge_refs: tuple[KnowledgeRef, ...],
        memory_ids: tuple[UUID, ...],
        max_fact_age: float = 300,
        max_memory_age: float = 3600,
    ) -> ContextSnapshot:
        """Build a snapshot, filtering out stale or inaccessible items."""

        fresh_facts: list[EnvironmentFact] = []
        for fact in environment_facts:
            check = self._freshness.check_fact(fact, max_fact_age)
            acl_check = self._acl.check_access(fact, tenant_id, roles)
            if check.passed and acl_check.allowed:
                fresh_facts.append(fact)

        fresh_knowledge: list[KnowledgeRef] = []
        for ref in knowledge_refs:
            acl_check = self._acl.check_access(ref, tenant_id, roles)
            if acl_check.allowed:
                fresh_knowledge.append(ref)

        return ContextSnapshot(
            tenant_id=tenant_id,
            goal_id=goal_id,
            run_id=run_id,
            environment_facts=tuple(fresh_facts),
            knowledge_refs=tuple(fresh_knowledge),
            memory_ids=memory_ids,
            history_digest=_digest(fresh_facts, fresh_knowledge, memory_ids),
            tool_versions=(),
        )


# ── Compression ─────────────────────────────────────────────────────────────


class ContextCompressor:
    """Compresses large context snapshots to fit within model token limits."""

    @staticmethod
    async def compress(
        snapshot: ContextSnapshot,
        max_tokens: int = 128_000,
        priority: str = "recent",
    ) -> ContextSnapshot:
        """Return a compressed snapshot that fits within *max_tokens*.

        Current implementation is a pass-through; a full implementation
        would use truncation, summarisation, and priority-based retention.
        """
        _ = max_tokens, priority
        return snapshot


# ── Helpers ─────────────────────────────────────────────────────────────────


def _digest(
    facts: list[EnvironmentFact],
    knowledge: list[KnowledgeRef],
    memory_ids: tuple[UUID, ...],
) -> str:
    import hashlib

    parts: list[str] = [f.fact_id for f in facts]
    parts.extend(r.knowledge_id for r in knowledge)
    parts.extend(m.hex for m in memory_ids)
    return hashlib.sha256("|".join(sorted(parts)).encode()).hexdigest()


__all__ = [
    "ACLCheck",
    "AccessLevel",
    "ContextACL",
    "ContextAssembler",
    "ContextCompressor",
    "FreshnessCheck",
    "FreshnessGuard",
    "FreshnessPolicy",
]
