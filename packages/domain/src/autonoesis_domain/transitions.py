"""Shared state-transition primitives and auditable transition records."""

from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from uuid import UUID


class InvalidStateTransition(ValueError):
    """Raised when a domain object is asked to perform an illegal transition."""


SYSTEM_ACTOR_ID = UUID(int=0)


@dataclass(frozen=True, slots=True)
class StateTransition:
    from_status: str
    to_status: str
    occurred_at: datetime
    reason: str
    actor_id: UUID

    def __post_init__(self) -> None:
        if self.occurred_at.tzinfo is None:
            raise ValueError("transition timestamp must be timezone-aware")
        if not self.reason.strip():
            raise ValueError("transition reason must not be empty")


def transition_record(
    current: StrEnum,
    target: StrEnum,
    *,
    actor_id: UUID = SYSTEM_ACTOR_ID,
    reason: str = "system transition",
    occurred_at: datetime | None = None,
) -> StateTransition:
    return StateTransition(
        from_status=current.value,
        to_status=target.value,
        occurred_at=occurred_at or datetime.now(UTC),
        reason=reason,
        actor_id=actor_id,
    )


def require_transition[StateT: StrEnum](
    current: StateT,
    target: StateT,
    allowed: dict[StateT, frozenset[StateT]],
) -> None:
    if target not in allowed.get(current, frozenset()):
        raise InvalidStateTransition(f"cannot transition from {current} to {target}")
