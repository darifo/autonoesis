"""Strict, versioned Capability Pack manifest loading."""

import re
from dataclasses import dataclass
from hashlib import sha256
from json import dumps
from pathlib import Path
from typing import Any, cast

import yaml
from jsonschema import Draft202012Validator

_IDENTIFIER = re.compile(r"^[a-z][a-z0-9]*(?:[._-][a-z0-9]+)*$")
_SEMVER = re.compile(r"^\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?$")
_ENTRY_POINT = re.compile(r"^[A-Za-z_][A-Za-z0-9_.]*:[A-Za-z_][A-Za-z0-9_]*$")
_SHA256_HEX = re.compile(r"^[0-9a-f]{64}$")
_SIGNATURE_HEX = re.compile(r"^[0-9a-f]{128}$")
_ARTIFACT_URI = re.compile(r"^[a-z][a-z0-9+.-]*://[A-Za-z0-9._~/-]{1,400}$")
_VERSION_SPEC_ITEM = re.compile(r"^(=|>=|<=|>|<)?(\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?|\*)$")


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
class PackDependency:
    """A declared dependency on another Capability Pack version range."""

    pack_id: str
    version_spec: str

    def __post_init__(self) -> None:
        if _IDENTIFIER.fullmatch(self.pack_id) is None:
            raise ManifestError("dependency pack_id must be a normalized identifier")
        if not self.version_spec.split() or not all(
            _VERSION_SPEC_ITEM.fullmatch(item) for item in self.version_spec.split()
        ):
            raise ManifestError(f"dependency version spec is invalid: {self.version_spec}")


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
    evaluation_subject: str | None = None
    artifact_uri: str | None = None
    artifact_digest: str | None = None
    signature: str | None = None
    sbom_ref: str | None = None
    sbom_digest: str | None = None
    dependencies: tuple[PackDependency, ...] = ()


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
    required = {
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
    allowed = required | {
        "evaluation_subject",
        "artifact_uri",
        "artifact_digest",
        "signature",
        "sbom_ref",
        "sbom_digest",
        "dependencies",
    }
    if set(raw) - allowed or not required <= set(raw):
        raise ManifestError(f"manifest fields must be a subset of: {sorted(allowed)}")
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
    evaluation_subject = raw.get("evaluation_subject")
    if evaluation_subject is not None and (
        not isinstance(evaluation_subject, str)
        or _ENTRY_POINT.fullmatch(evaluation_subject) is None
    ):
        raise ManifestError("evaluation_subject must be module:function")
    if evaluation_subject is not None and (
        evaluation_subject.partition(":")[0].split(".", maxsplit=1)[0] != expected_module_root
    ):
        raise ManifestError("evaluation_subject must be owned by the capability pack module")
    artifact_uri = raw.get("artifact_uri")
    if artifact_uri is not None and (
        not isinstance(artifact_uri, str) or _ARTIFACT_URI.fullmatch(artifact_uri) is None
    ):
        raise ManifestError("artifact_uri must be a bounded URI with an explicit scheme")
    artifact_digest = raw.get("artifact_digest")
    if artifact_digest is not None and (
        not isinstance(artifact_digest, str) or _SHA256_HEX.fullmatch(artifact_digest) is None
    ):
        raise ManifestError("artifact_digest must be a lowercase sha256 hex digest")
    signature = raw.get("signature")
    if signature is not None and (
        not isinstance(signature, str) or _SIGNATURE_HEX.fullmatch(signature) is None
    ):
        raise ManifestError("signature must be a lowercase hex ed25519 signature")
    sbom_ref = raw.get("sbom_ref")
    if sbom_ref is not None and (
        not isinstance(sbom_ref, str) or _ARTIFACT_URI.fullmatch(sbom_ref) is None
    ):
        raise ManifestError("sbom_ref must be a bounded URI with an explicit scheme")
    sbom_digest = raw.get("sbom_digest")
    if sbom_digest is not None and (
        not isinstance(sbom_digest, str) or _SHA256_HEX.fullmatch(sbom_digest) is None
    ):
        raise ManifestError("sbom_digest must be a lowercase sha256 hex digest")
    dependencies_raw = raw.get("dependencies", [])
    if not isinstance(dependencies_raw, list):
        raise ManifestError("dependencies must be a list")
    dependencies_list: list[PackDependency] = []
    for item in dependencies_raw:
        if not isinstance(item, dict) or not isinstance(item.get("version_spec"), str):
            raise ManifestError("dependency entries must be objects")
        dependencies_list.append(
            PackDependency(
                pack_id=_require_identifier(item.get("pack_id"), "dependencies.pack_id"),
                version_spec=item["version_spec"],
            )
        )
    dependencies = tuple(dependencies_list)
    declared = [dependency.pack_id for dependency in dependencies]
    if len(set(declared)) != len(declared):
        raise ManifestError("dependencies must be unique per pack")
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
        evaluation_subject=evaluation_subject,
        goal_types=tuple(goal_types),
        skills=_require_string_list(raw["skills"], "skills"),
        tools=_require_string_list(raw["tools"], "tools"),
        policies=_require_string_list(raw["policies"], "policies"),
        evaluation_suites=_require_string_list(raw["evaluation_suites"], "evaluation_suites"),
        artifact_uri=artifact_uri,
        artifact_digest=artifact_digest,
        signature=signature,
        sbom_ref=sbom_ref,
        sbom_digest=sbom_digest,
        dependencies=dependencies,
    )


def _canonical(value: Any) -> str:
    return dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def manifest_payload(manifest: CapabilityPackManifest) -> dict[str, Any]:
    """Lossless, canonical-serializable payload for persistence and transport."""
    payload: dict[str, Any] = {
        "api_version": manifest.api_version,
        "pack_id": manifest.pack_id,
        "version": manifest.version,
        "python_entry_point": manifest.python_entry_point,
        "goal_types": [
            {
                "goal_type": item.goal_type,
                "input_schema": item.input_schema,
                "agent": item.agent,
                "evaluation_suite": item.evaluation_suite,
                "default_policy": item.default_policy,
                "default_budget": item.default_budget,
            }
            for item in manifest.goal_types
        ],
        "skills": list(manifest.skills),
        "tools": list(manifest.tools),
        "policies": list(manifest.policies),
        "evaluation_suites": list(manifest.evaluation_suites),
        "dependencies": [
            {"pack_id": item.pack_id, "version_spec": item.version_spec}
            for item in manifest.dependencies
        ],
    }
    for field in (
        "evaluation_subject",
        "artifact_uri",
        "artifact_digest",
        "signature",
        "sbom_ref",
        "sbom_digest",
    ):
        value = getattr(manifest, field)
        if value is not None:
            payload[field] = value
    return payload


def canonical_unsigned_payload(manifest: CapabilityPackManifest) -> dict[str, Any]:
    """The exact bytes a signature commits to: everything except the signature."""
    payload = manifest_payload(manifest)
    payload.pop("signature", None)
    return payload


def manifest_content_digest(manifest: CapabilityPackManifest) -> str:
    """Content-address the manifest's declarative payload.

    All supply-chain metadata (artifact URI/digests, SBOM, signature) is
    excluded, so attaching or updating metadata never changes the content
    address while the signature still commits to the full unsigned payload.
    """
    payload = canonical_unsigned_payload(manifest)
    for field in ("artifact_digest", "sbom_digest", "artifact_uri", "sbom_ref"):
        payload.pop(field, None)
    return sha256(_canonical(payload).encode("utf-8")).hexdigest()


def canonical_signature_bytes(manifest: CapabilityPackManifest) -> bytes:
    return _canonical(canonical_unsigned_payload(manifest)).encode("utf-8")


def _semver_key(version: str) -> tuple[int | tuple[Any, ...], ...]:
    core, _, prerelease = version.partition("-")
    numbers = tuple(int(part) for part in core.split("."))
    if not prerelease:
        # A release outranks any prerelease of the same triple.
        return (*numbers, 1, ())
    identifiers = tuple(
        (0, int(item)) if item.isdigit() else (1, item) for item in prerelease.split(".")
    )
    return (*numbers, 0, identifiers)


def version_satisfies(spec: str, version: str) -> bool:
    """Evaluate a (possibly compound) dependency spec: every comparator must hold."""
    comparators = spec.split()
    if not comparators:
        raise ManifestError("dependency version spec is invalid: empty")
    results = [_version_satisfies_one(item, version) for item in comparators]
    return all(results)


def _version_satisfies_one(item: str, version: str) -> bool:
    match = _VERSION_SPEC_ITEM.fullmatch(item)
    if match is None:
        raise ManifestError(f"dependency version spec is invalid: {item}")
    operator = match.group(1) or "="
    target = match.group(2)
    if _SEMVER.fullmatch(version) is None:
        raise ManifestError(f"version must use semantic versioning: {version}")
    if target == "*":
        return operator in {"=", ">=", "<=", ">", "<"}
    left, right = _semver_key(version), _semver_key(target)
    return {
        "=": left == right,
        ">": left > right,
        ">=": left >= right,
        "<": left < right,
        "<=": left <= right,
    }[operator]


def compare_versions(left: str, right: str) -> int:
    """Deterministic semver ordering helper for channel resolution."""
    key_left, key_right = _semver_key(left), _semver_key(right)
    if key_left < key_right:
        return -1
    return 1 if key_left > key_right else 0


def validate_payload(goal_type: GoalTypeManifest, payload: dict[str, Any]) -> None:
    errors = sorted(
        Draft202012Validator(goal_type.input_schema).iter_errors(payload),
        key=lambda error: list(error.path),
    )
    if errors:
        raise ManifestError(f"goal input is invalid: {errors[0].message}")
