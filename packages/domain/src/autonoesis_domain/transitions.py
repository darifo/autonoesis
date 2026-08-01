"""Shared state-transition primitives."""

from enum import StrEnum


class InvalidStateTransition(ValueError):
    """Raised when a domain object is asked to perform an illegal transition."""


def require_transition[StateT: StrEnum](
    current: StateT,
    target: StateT,
    allowed: dict[StateT, frozenset[StateT]],
) -> None:
    if target not in allowed.get(current, frozenset()):
        raise InvalidStateTransition(f"cannot transition from {current} to {target}")
