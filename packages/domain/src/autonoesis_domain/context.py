"""Separated environment, knowledge, memory, and immutable context snapshots."""

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any
from uuid import UUID, uuid4


class TrustLevel(StrEnum):
    UNTRUSTED = "untrusted"
    ADVISORY = "advisory"
    AUTHORITATIVE = "authoritative"


@dataclass(frozen=True, slots=True)
class EnvironmentFact:
    fact_id: str
    source: str
    subject: str
    value: dict[str, Any]
    observed_at: datetime
    valid_until: datetime
    trust: TrustLevel

    def __post_init__(self) -> None:
        if self.observed_at.tzinfo is None or self.valid_until.tzinfo is None:
            raise ValueError("environment fact timestamps must be timezone-aware")
        if self.valid_until < self.observed_at:
            raise ValueError("environment fact validity cannot end before observation")


@dataclass(frozen=True, slots=True)
class KnowledgeRef:
    knowledge_id: str
    version: str
    source: str
    citation: str
    trust: TrustLevel


@dataclass(frozen=True, slots=True)
class MemoryRecord:
    tenant_id: UUID
    scope: str
    content: str
    provenance: tuple[str, ...]
    confidence: float
    expires_at: datetime
    approved_by: UUID
    memory_id: UUID = field(default_factory=uuid4)

    def __post_init__(self) -> None:
        if not 0 <= self.confidence <= 1:
            raise ValueError("memory confidence must be between zero and one")
        if not self.provenance:
            raise ValueError("memory requires provenance")
        if self.expires_at.tzinfo is None:
            raise ValueError("memory expiry must be timezone-aware")


@dataclass(frozen=True, slots=True)
class ContextSnapshot:
    tenant_id: UUID
    goal_id: UUID
    run_id: UUID
    environment_facts: tuple[EnvironmentFact, ...]
    knowledge_refs: tuple[KnowledgeRef, ...]
    memory_ids: tuple[UUID, ...]
    history_digest: str
    tool_versions: tuple[str, ...]
    conflicts: tuple[str, ...] = ()
    snapshot_id: UUID = field(default_factory=uuid4)
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    def __post_init__(self) -> None:
        if not self.history_digest.strip():
            raise ValueError("context snapshot requires a history digest")
        if self.created_at.tzinfo is None:
            raise ValueError("context snapshot timestamp must be timezone-aware")
