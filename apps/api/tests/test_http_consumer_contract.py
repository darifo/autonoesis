"""Frozen OpenAPI and behavior contracts consumed by SDK/UI clients."""

import json
from pathlib import Path
from uuid import uuid4

from autonoesis_adapters import InMemoryPlatformStore
from autonoesis_api.main import build_app
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[3]
CONTRACT = ROOT / "docs/contracts/generated/openapi-v1.json"


def test_openapi_source_matches_frozen_consumer_contract() -> None:
    expected = json.loads(CONTRACT.read_text(encoding="utf-8"))
    actual = build_app(InMemoryPlatformStore()).openapi()

    assert actual == expected
    error_schema = actual["components"]["schemas"]["ErrorEnvelope"]
    assert error_schema["required"] == ["error"]
    assert actual["openapi"].startswith("3.1.")


def test_all_public_mutations_require_idempotency_and_no_outcome_bypass_exists() -> None:
    schema = json.loads(CONTRACT.read_text(encoding="utf-8"))
    operations = {
        (method.upper(), path): definition
        for path, path_item in schema["paths"].items()
        for method, definition in path_item.items()
        if method in {"post", "put", "patch", "delete"}
    }
    assert operations
    for operation, definition in operations.items():
        headers = {
            parameter["name"]
            for parameter in definition.get("parameters", ())
            if parameter.get("in") == "header"
        }
        assert "Idempotency-Key" in headers, operation
    assert all("actions" not in path or method == "GET" for method, path in operations)
    assert all("outcomes" not in path or method == "GET" for method, path in operations)


def test_validation_failure_uses_the_documented_error_envelope() -> None:
    client = TestClient(build_app(InMemoryPlatformStore()))
    response = client.post(
        "/v1/goals",
        json={},
        headers={
            "X-Tenant-ID": str(uuid4()),
            "X-Actor-ID": str(uuid4()),
            "Idempotency-Key": "consumer-invalid-goal",
        },
    )

    assert response.status_code == 422
    assert set(response.json()) == {"error"}
    assert set(response.json()["error"]) == {
        "audit_ref",
        "code",
        "correlation_id",
        "message",
        "next_action",
        "retryable",
    }
    assert response.json()["error"]["audit_ref"] is None
