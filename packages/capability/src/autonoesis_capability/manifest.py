"""Strict, versioned Capability Pack manifest loading."""

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

import yaml
from jsonschema import Draft202012Validator

_IDENTIFIER = re.compile(r"^[a-z][a-z0-9]*(?:[._-][a-z0-9]+)*$")
_SEMVER = re.compile(r"^\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?$")
_ENTRY_POINT = re.compile(r"^[A-Za-z_][A-Za-z0-9_.]*:[A-Za-z_][A-Za-z0-9_]*$")


class ManifestError(ValueError):
    """Raised when a Capability Pack cannot be trusted or loaded."""


@dataclass(frozen=True, slots=True)
class GoalTypeManifest:
    goal_type: str
    input_schema: dict[str, Any]
    agent: str
    evaluation_suite: str
    default_policy: str
    default_budget: int


@dataclass(frozen=True, slots=True)
class CapabilityPackManifest:
    api_version: str
    pack_id: str
    version: str
    python_entry_point: str
    goal_types: tuple[GoalTypeManifest, ...]
    skills: tuple[str, ...]
    tools: tuple[str, ...]
    policies: tuple[str, ...]
    evaluation_suites: tuple[str, ...]


def _require_identifier(value: object, field: str) -> str:
    if not isinstance(value, str) or _IDENTIFIER.fullmatch(value) is None:
        raise ManifestError(f"{field} must be a normalized identifier")
    return value


def _require_string_list(value: object, field: str) -> tuple[str, ...]:
    if not isinstance(value, list):
        raise ManifestError(f"{field} must be a list")
    result = tuple(_require_identifier(item, field) for item in value)
    if len(set(result)) != len(result):
        raise ManifestError(f"{field} must not contain duplicates")
    return result


def load_manifest(path: Path) -> CapabilityPackManifest:
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise ManifestError(f"unable to read manifest: {exc}") from exc
    if not isinstance(raw, dict):
        raise ManifestError("manifest root must be an object")
    return parse_manifest(cast(dict[str, Any], raw))


def parse_manifest(raw: dict[str, Any]) -> CapabilityPackManifest:
    expected = {
        "api_version",
        "pack_id",
        "version",
        "python_entry_point",
        "goal_types",
        "skills",
        "tools",
        "policies",
        "evaluation_suites",
    }
    if set(raw) != expected:
        raise ManifestError(f"manifest fields must be exactly: {sorted(expected)}")
    api_version = raw["api_version"]
    if api_version != "autonoesis/v1alpha1":
        raise ManifestError("unsupported capability manifest api_version")
    version = raw["version"]
    if not isinstance(version, str) or _SEMVER.fullmatch(version) is None:
        raise ManifestError("version must use semantic versioning")
    entry_point = raw["python_entry_point"]
    if not isinstance(entry_point, str) or _ENTRY_POINT.fullmatch(entry_point) is None:
        raise ManifestError("python_entry_point must be module:function")
    pack_id = _require_identifier(raw["pack_id"], "pack_id")
    module_name = entry_point.partition(":")[0]
    expected_module_root = pack_id.replace("-", "_")
    if module_name.split(".", maxsplit=1)[0] != expected_module_root:
        raise ManifestError("python_entry_point must be owned by the capability pack module")
    goal_types_raw = raw["goal_types"]
    if not isinstance(goal_types_raw, list) or not goal_types_raw:
        raise ManifestError("goal_types must be a non-empty list")
    goal_types: list[GoalTypeManifest] = []
    for item in goal_types_raw:
        if not isinstance(item, dict):
            raise ManifestError("goal type entry must be an object")
        required = {
            "goal_type",
            "input_schema",
            "agent",
            "evaluation_suite",
            "default_policy",
            "default_budget",
        }
        if set(item) != required:
            raise ManifestError("goal type fields are incomplete or unknown")
        schema = item["input_schema"]
        if not isinstance(schema, dict):
            raise ManifestError("input_schema must be an object")
        Draft202012Validator.check_schema(schema)
        budget = item["default_budget"]
        if not isinstance(budget, int) or budget <= 0:
            raise ManifestError("default_budget must be a positive integer")
        goal_types.append(
            GoalTypeManifest(
                goal_type=_require_identifier(item["goal_type"], "goal_type"),
                input_schema=cast(dict[str, Any], schema),
                agent=_require_identifier(item["agent"], "agent"),
                evaluation_suite=_require_identifier(item["evaluation_suite"], "evaluation_suite"),
                default_policy=_require_identifier(item["default_policy"], "default_policy"),
                default_budget=budget,
            )
        )
    identifiers = [item.goal_type for item in goal_types]
    if len(set(identifiers)) != len(identifiers):
        raise ManifestError("goal types must be unique")
    return CapabilityPackManifest(
        api_version=api_version,
        pack_id=pack_id,
        version=version,
        python_entry_point=entry_point,
        goal_types=tuple(goal_types),
        skills=_require_string_list(raw["skills"], "skills"),
        tools=_require_string_list(raw["tools"], "tools"),
        policies=_require_string_list(raw["policies"], "policies"),
        evaluation_suites=_require_string_list(raw["evaluation_suites"], "evaluation_suites"),
    )


def validate_payload(goal_type: GoalTypeManifest, payload: dict[str, Any]) -> None:
    errors = sorted(
        Draft202012Validator(goal_type.input_schema).iter_errors(payload),
        key=lambda error: list(error.path),
    )
    if errors:
        raise ManifestError(f"goal input is invalid: {errors[0].message}")
