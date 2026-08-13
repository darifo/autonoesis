"""Tenant-safe context ACL, conflict detection, compression, and assembly."""

from __future__ import annotations

import json
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any
from uuid import UUID

from autonoesis_domain import (
    ContextSnapshot,
    DataClassification,
    EnvironmentFact,
    FreshnessPolicy,
    KnowledgeRef,
    MemoryRecord,
    MemoryStatus,
    TrustLevel,
)


@dataclass(frozen=True, slots=True)
class FreshnessCheck:
    passed: bool
    age_seconds: float
    max_age_seconds: float
    policy: FreshnessPolicy = FreshnessPolicy.STRICT
    warning: bool = False


class FreshnessGuard:
    @staticmethod
    def check_fact(
        fact: EnvironmentFact,
        max_age_seconds: float = 300,
        policy: FreshnessPolicy | None = None,
    ) -> FreshnessCheck:
        now = datetime.now(UTC)
        effective_policy = policy or fact.freshness_policy
        age = (now - fact.observed_at).total_seconds()
        stale = now > fact.valid_until or age > max_age_seconds
        passed = not stale or effective_policy is not FreshnessPolicy.STRICT
        return FreshnessCheck(
            passed,
            age,
            max_age_seconds,
            effective_policy,
            stale and effective_policy is FreshnessPolicy.WARN,
        )

    @staticmethod
    def check_memory(record: MemoryRecord, max_age_seconds: float = 3600) -> FreshnessCheck:
        now = datetime.now(UTC)
        age = (now - record.created_at).total_seconds()
        return FreshnessCheck(
            record.status is MemoryStatus.STABLE
            and now < record.expires_at
            and age <= max_age_seconds,
            age,
            max_age_seconds,
        )


class AccessLevel(StrEnum):
    READ = "read"
    USE = "use"
    NONE = "none"


@dataclass(frozen=True, slots=True)
class ACLCheck:
    allowed: bool
    level: AccessLevel = AccessLevel.NONE
    reason: str = ""


_CLASSIFICATION_RANK = {
    DataClassification.PUBLIC: 0,
    DataClassification.INTERNAL: 1,
    DataClassification.CONFIDENTIAL: 2,
    DataClassification.RESTRICTED: 3,
}


class ContextACL:
    @staticmethod
    def check_access(
        item: EnvironmentFact | KnowledgeRef | MemoryRecord,
        tenant_id: UUID,
        roles: frozenset[str],
        *,
        purpose: str = "run_context",
        maximum_classification: DataClassification = DataClassification.INTERNAL,
        allowed_subjects: frozenset[str] = frozenset(),
    ) -> ACLCheck:
        if item.tenant_id != tenant_id:
            return ACLCheck(False, reason="tenant boundary denied")
        classification = item.classification
        if _CLASSIFICATION_RANK[classification] > _CLASSIFICATION_RANK[maximum_classification]:
            return ACLCheck(False, reason="classification clearance denied")
        allowed_roles: frozenset[str] = getattr(item, "allowed_roles", frozenset())
        if allowed_roles and not roles.intersection(allowed_roles):
            return ACLCheck(False, reason="role ACL denied")
        allowed_purposes: frozenset[str] = getattr(item, "allowed_purposes", frozenset())
        if allowed_purposes and purpose not in allowed_purposes:
            return ACLCheck(False, reason="purpose ACL denied")
        if (
            isinstance(item, EnvironmentFact)
            and allowed_subjects
            and item.subject not in allowed_subjects
        ):
            return ACLCheck(False, reason="row subject ACL denied")
        trust = getattr(item, "trust", getattr(item, "source_trust", TrustLevel.UNTRUSTED))
        if trust is TrustLevel.UNTRUSTED:
            return ACLCheck(True, AccessLevel.READ, "untrusted content is data only")
        if isinstance(item, MemoryRecord) and item.confidence < 0.5:
            return ACLCheck(True, AccessLevel.READ, "low-confidence memory is data only")
        return ACLCheck(True, AccessLevel.USE, "full access")


class ConflictDetector:
    @staticmethod
    def detect(facts: tuple[EnvironmentFact, ...]) -> tuple[str, ...]:
        seen: dict[tuple[str, str], str] = {}
        conflicts: set[str] = set()
        for fact in facts:
            key = (fact.subject, fact.fact_id)
            value = json.dumps(fact.value, sort_keys=True, separators=(",", ":"))
            if key in seen and seen[key] != value:
                conflicts.add(f"environment:{fact.subject}:{fact.fact_id}")
            seen[key] = value
        return tuple(sorted(conflicts))


_INJECTION_MARKERS = (
    "ignore previous",
    "ignore all previous",
    "system prompt",
    "developer message",
    "execute tool",
)


def mark_prompt_injection(fact: EnvironmentFact) -> EnvironmentFact:
    value = json.dumps(fact.value, sort_keys=True).lower()
    if any(marker in value for marker in _INJECTION_MARKERS):
        return replace(fact, trust=TrustLevel.UNTRUSTED)
    return fact


class ContextAssembler:
    def __init__(
        self,
        freshness: FreshnessGuard | None = None,
        acl: ContextACL | None = None,
        conflicts: ConflictDetector | None = None,
    ) -> None:
        self._freshness = freshness or FreshnessGuard()
        self._acl = acl or ContextACL()
        self._conflicts = conflicts or ConflictDetector()

    async def assemble(
        self,
        goal_id: UUID,
        run_id: UUID,
        tenant_id: UUID,
        roles: frozenset[str],
        environment_facts: tuple[EnvironmentFact, ...],
        knowledge_refs: tuple[KnowledgeRef, ...],
        memory_records: tuple[MemoryRecord, ...],
        history_digest: str,
        tool_versions: tuple[str, ...],
        *,
        purpose: str = "run_context",
        policy_version: str = "context-policy@1",
        maximum_classification: DataClassification = DataClassification.INTERNAL,
        allowed_subjects: frozenset[str] = frozenset(),
    ) -> ContextSnapshot:
        facts: list[EnvironmentFact] = []
        warnings: list[str] = []
        for raw in environment_facts:
            fact = mark_prompt_injection(raw)
            fresh = self._freshness.check_fact(fact)
            access = self._acl.check_access(
                fact,
                tenant_id,
                roles,
                purpose=purpose,
                maximum_classification=maximum_classification,
                allowed_subjects=allowed_subjects,
            )
            if fresh.passed and access.allowed:
                facts.append(fact)
                if fresh.warning:
                    warnings.append(f"stale:{fact.fact_id}")

        knowledge = tuple(
            ref
            for ref in knowledge_refs
            if self._acl.check_access(
                ref,
                tenant_id,
                roles,
                purpose=purpose,
                maximum_classification=maximum_classification,
            ).allowed
        )
        memories = tuple(
            item
            for item in memory_records
            if self._freshness.check_memory(item).passed
            and self._acl.check_access(
                item,
                tenant_id,
                roles,
                purpose=purpose,
                maximum_classification=maximum_classification,
            ).allowed
        )
        conflicts = (*self._conflicts.detect(tuple(facts)), *sorted(warnings))
        return ContextSnapshot(
            tenant_id,
            goal_id,
            run_id,
            tuple(facts),
            knowledge,
            tuple(item.memory_id for item in memories),
            history_digest,
            tuple(sorted(tool_versions)),
            policy_version,
            conflicts,
        )


class ContextCompressor:
    @staticmethod
    async def compress(snapshot: ContextSnapshot, max_tokens: int = 128_000) -> ContextSnapshot:
        if max_tokens < 64:
            raise ValueError("context budget is too small to retain security boundaries")
        budget = max_tokens * 4
        facts: list[EnvironmentFact] = []
        used = 0
        for fact in snapshot.environment_facts:
            encoded = json.dumps(fact.value, sort_keys=True)
            remaining = max(0, budget - used)
            value: dict[str, Any] = fact.value
            if len(encoded) > remaining:
                value = {"summary": encoded[:remaining], "truncated": True}
            facts.append(replace(fact, value=value, visible_fields=tuple(value)))
            used += min(len(encoded), remaining)
        return replace(snapshot, environment_facts=tuple(facts))


__all__ = [
    "ACLCheck",
    "AccessLevel",
    "ConflictDetector",
    "ContextACL",
    "ContextAssembler",
    "ContextCompressor",
    "FreshnessCheck",
    "FreshnessGuard",
    "FreshnessPolicy",
    "mark_prompt_injection",
]
