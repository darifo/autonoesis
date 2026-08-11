"""Configured HTTP authoritative readback adapter for Outcome verification."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

import httpx
from autonoesis_application import AuthoritativeObservation
from autonoesis_domain import SubjectRef, SuccessCriterion


@dataclass(frozen=True, slots=True)
class ReadbackEndpoint:
    base_url: str
    expected_identity: str
    timeout_seconds: float = 10.0
    maximum_validity_seconds: int = 300

    def __post_init__(self) -> None:
        if not self.base_url.startswith(("https://", "http://127.0.0.1", "http://localhost")):
            raise ValueError("readback endpoint must use TLS except for loopback component tests")
        if not self.expected_identity.strip():
            raise ValueError("readback expected identity must not be empty")
        if self.timeout_seconds <= 0 or self.maximum_validity_seconds <= 0:
            raise ValueError("readback timeout and validity must be positive")


class HttpAuthoritativeReadback:
    """Read a configured authority; caller-provided URLs are never accepted."""

    def __init__(
        self,
        endpoints: dict[str, ReadbackEndpoint],
        client: httpx.AsyncClient | None = None,
    ) -> None:
        if not endpoints:
            raise ValueError("at least one authoritative readback endpoint is required")
        self._endpoints = dict(endpoints)
        self._client = client or httpx.AsyncClient()
        self._owns_client = client is None

    async def close(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    async def observe(
        self,
        source: str,
        tenant_id: UUID,
        subject_refs: tuple[SubjectRef, ...],
        criterion: SuccessCriterion,
    ) -> AuthoritativeObservation:
        try:
            endpoint = self._endpoints[source]
        except KeyError as exc:
            raise LookupError(
                f"authoritative readback source {source!r} is not registered"
            ) from exc
        try:
            response = await self._client.post(
                endpoint.base_url.rstrip("/") + "/v1/readback",
                json={
                    "tenant_id": str(tenant_id),
                    "subjects": [
                        {
                            "system": item.system,
                            "subject_type": item.subject_type,
                            "subject_id": item.subject_id,
                            "version": item.version,
                        }
                        for item in subject_refs
                    ],
                    "criterion": {
                        "criterion_id": criterion.criterion_id,
                        "description": criterion.description,
                        "evidence_type": criterion.evidence_type,
                    },
                },
                timeout=endpoint.timeout_seconds,
            )
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise LookupError("authoritative readback is unavailable") from exc
        payload: Any = response.json()
        if not isinstance(payload, dict) or not isinstance(payload.get("state"), dict):
            raise ValueError("authoritative readback returned an invalid state payload")
        reference = payload.get("reference")
        criterion_met = payload.get("criterion_met")
        validity = payload.get("valid_for_seconds", endpoint.maximum_validity_seconds)
        if not isinstance(reference, str) or not reference.strip():
            raise ValueError("authoritative readback reference is missing")
        if criterion_met is not None and not isinstance(criterion_met, bool):
            raise ValueError("authoritative readback criterion result is invalid")
        if not isinstance(validity, int) or not 0 < validity <= endpoint.maximum_validity_seconds:
            raise ValueError("authoritative readback validity is invalid")
        content = json.dumps(
            payload["state"], sort_keys=True, separators=(",", ":"), ensure_ascii=False
        ).encode()
        captured_at = datetime.now(UTC)
        return AuthoritativeObservation(
            source,
            endpoint.expected_identity,
            reference,
            content.decode(),
            content,
            criterion_met,
            captured_at,
            captured_at + timedelta(seconds=validity),
        )
