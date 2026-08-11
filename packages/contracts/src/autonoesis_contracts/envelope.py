"""Bootstrap message envelope shared by commands and events."""

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from autonoesis_domain import DataClassification as DataClassification


@dataclass(frozen=True, slots=True)
class MessageEnvelope:
    """Versioned metadata and payload for an Autonoesis command or event."""

    schema: str
    schema_version: int
    tenant_id: UUID
    actor_id: UUID
    payload: dict[str, Any]
    message_id: UUID = field(default_factory=uuid4)
    correlation_id: UUID = field(default_factory=uuid4)
    causation_id: UUID | None = None
    traceparent: str | None = None
    classification: DataClassification = DataClassification.INTERNAL
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    def __post_init__(self) -> None:
        if not self.schema.strip():
            raise ValueError("schema must not be empty")
        if self.schema_version < 1:
            raise ValueError("schema_version must be positive")
        if self.created_at.tzinfo is None:
            raise ValueError("created_at must be timezone-aware")
