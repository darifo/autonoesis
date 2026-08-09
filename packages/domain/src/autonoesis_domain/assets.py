"""Versioned Agent, Skill, and Tool capability assets."""

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any
from uuid import UUID, uuid4


class AssetStage(StrEnum):
    CANDIDATE = "candidate"
    STABLE = "stable"
    RETIRED = "retired"


class SideEffectClass(StrEnum):
    COMPUTE = "compute"
    READ = "read"
    REVERSIBLE_WRITE = "reversible_write"
    HIGH_IMPACT_WRITE = "high_impact_write"
    PRIVILEGED = "privileged"


@dataclass(frozen=True, slots=True)
class LoopPolicy:
    max_rounds: int
    max_tokens: int
    max_cost_units: int
    timeout_seconds: int

    def __post_init__(self) -> None:
        if min(self.max_rounds, self.max_tokens, self.max_cost_units, self.timeout_seconds) <= 0:
            raise ValueError("agent loop limits must be positive")


@dataclass(frozen=True, slots=True)
class AgentDefinition:
    tenant_id: UUID
    name: str
    description: str
    agent_id: UUID = field(default_factory=uuid4)


@dataclass(frozen=True, slots=True)
class AgentVersion:
    tenant_id: UUID
    agent_id: UUID
    version: int
    instruction: str
    model_route: str
    skill_ids: tuple[str, ...]
    tool_ids: tuple[str, ...]
    loop_policy: LoopPolicy
    stage: AssetStage = AssetStage.CANDIDATE
    agent_version_id: UUID = field(default_factory=uuid4)

    def __post_init__(self) -> None:
        if self.version < 1 or not self.instruction.strip() or not self.model_route.strip():
            raise ValueError("agent version, instruction, and model route are required")


@dataclass(frozen=True, slots=True)
class SkillDefinition:
    skill_id: str
    version: str
    input_schema: dict[str, Any]
    output_schema: dict[str, Any]
    executor: str
    evaluation_suite_id: str

    def __post_init__(self) -> None:
        if any(
            not item.strip()
            for item in (self.skill_id, self.version, self.executor, self.evaluation_suite_id)
        ):
            raise ValueError("skill identifiers must not be empty")


@dataclass(frozen=True, slots=True)
class ToolDefinition:
    tool_id: str
    version: str
    input_schema: dict[str, Any]
    output_schema: dict[str, Any]
    adapter: str
    side_effect: SideEffectClass
    idempotent: bool
    verification: str
    compensation: str | None = None

    def __post_init__(self) -> None:
        if any(
            not item.strip()
            for item in (self.tool_id, self.version, self.adapter, self.verification)
        ):
            raise ValueError("tool identifiers and verification must not be empty")
        if (
            self.side_effect
            in {
                SideEffectClass.REVERSIBLE_WRITE,
                SideEffectClass.HIGH_IMPACT_WRITE,
                SideEffectClass.PRIVILEGED,
            }
            and not self.idempotent
        ):
            raise ValueError("write tools must declare an idempotent execution contract")
