"""Uniform contract implemented by Hermes, Codex, Agents SDK, and custom harnesses."""

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Protocol
from uuid import UUID, uuid4


class TaskStatus(StrEnum):
    SUCCEEDED = "succeeded"
    BLOCKED = "blocked"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class TaskRequest:
    run_id: UUID
    instruction: str
    context_snapshot_id: UUID
    capability_ids: tuple[str, ...]
    task_id: UUID = field(default_factory=uuid4)


@dataclass(frozen=True, slots=True)
class TaskResult:
    task_id: UUID
    status: TaskStatus
    summary: str
    artifacts: tuple[UUID, ...] = ()
    tool_proposals: tuple[dict[str, Any], ...] = ()
    blocked_reason: str | None = None

    def __post_init__(self) -> None:
        if self.status is TaskStatus.BLOCKED and not self.blocked_reason:
            raise ValueError("blocked task result requires blocked_reason")


class Harness(Protocol):
    name: str

    async def execute(self, request: TaskRequest) -> TaskResult: ...
