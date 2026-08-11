"""Constrained values shared by governed domain aggregates."""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from enum import StrEnum
from hashlib import sha256
from typing import Any


class RiskTier(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class BudgetUnit(StrEnum):
    COST_UNITS = "cost_units"
    TOKENS = "tokens"
    USD_MICROS = "usd_micros"


class DataClassification(StrEnum):
    PUBLIC = "public"
    INTERNAL = "internal"
    CONFIDENTIAL = "confidential"
    RESTRICTED = "restricted"


class ExecutionMode(StrEnum):
    AUTONOMOUS = "autonomous"
    SUPERVISED = "supervised"
    HUMAN_ONLY = "human_only"
    SHADOW = "shadow"


@dataclass(frozen=True, slots=True)
class BudgetAmount:
    amount: int
    unit: BudgetUnit = BudgetUnit.COST_UNITS

    def __post_init__(self) -> None:
        if isinstance(self.amount, bool) or self.amount < 0:
            raise ValueError("budget amount must be a non-negative integer")


@dataclass(frozen=True, slots=True)
class DataPolicy:
    maximum_classification: DataClassification = DataClassification.INTERNAL
    allowed_regions: tuple[str, ...] = ()
    retention_days: int = 30

    def __post_init__(self) -> None:
        if self.retention_days <= 0:
            raise ValueError("data retention must be positive")
        if any(not region.strip() for region in self.allowed_regions):
            raise ValueError("data policy regions must not be empty")
        if len(set(self.allowed_regions)) != len(self.allowed_regions):
            raise ValueError("data policy regions must be unique")


def _validate_json(value: Any, *, depth: int = 0) -> None:
    if depth > 32:
        raise ValueError("JSON value exceeds maximum nesting depth")
    if value is None or isinstance(value, (str, bool, int)):
        return
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError("JSON numbers must be finite")
        return
    if isinstance(value, list):
        for item in value:
            _validate_json(item, depth=depth + 1)
        return
    if isinstance(value, dict):
        for key, item in value.items():
            if not isinstance(key, str) or not key:
                raise ValueError("JSON object keys must be non-empty strings")
            _validate_json(item, depth=depth + 1)
        return
    raise ValueError(f"unsupported JSON value: {type(value).__name__}")


@dataclass(frozen=True, slots=True)
class JsonObject:
    """Immutable, canonical JSON object used at authorization boundaries."""

    canonical: str

    def __post_init__(self) -> None:
        try:
            parsed = json.loads(self.canonical)
        except (TypeError, json.JSONDecodeError) as exc:
            raise ValueError("canonical JSON is invalid") from exc
        if not isinstance(parsed, dict):
            raise ValueError("JSON value must be an object")
        _validate_json(parsed)
        normalized = json.dumps(
            parsed,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
        if len(normalized.encode("utf-8")) > 1_048_576:
            raise ValueError("JSON object exceeds one MiB")
        object.__setattr__(self, "canonical", normalized)

    @classmethod
    def from_value(cls, value: dict[str, Any]) -> JsonObject:
        _validate_json(value)
        return cls(
            json.dumps(
                value,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
                allow_nan=False,
            )
        )

    @property
    def digest(self) -> str:
        return sha256(self.canonical.encode("utf-8")).hexdigest()

    def to_value(self) -> dict[str, Any]:
        value = json.loads(self.canonical)
        if not isinstance(value, dict):  # pragma: no cover - protected by construction
            raise AssertionError("canonical JSON object decoded to a non-object")
        return value
