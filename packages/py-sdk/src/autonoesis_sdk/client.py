"""Small async client covering the stable Goal and Run entry points."""

from dataclasses import dataclass
from typing import Any
from uuid import UUID, uuid4

import httpx


@dataclass(frozen=True, slots=True)
class ClientIdentity:
    tenant_id: UUID
    actor_id: UUID
    principal_id: UUID
    roles: tuple[str, ...]


class AutonoesisClient:
    def __init__(
        self,
        base_url: str,
        identity: ClientIdentity,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._identity = identity
        self._client = client or httpx.AsyncClient(base_url=base_url, timeout=30)

    def _headers(self, idempotency_key: str | None = None) -> dict[str, str]:
        headers = {
            "X-Tenant-ID": str(self._identity.tenant_id),
            "X-Actor-ID": str(self._identity.actor_id),
            "X-Principal-ID": str(self._identity.principal_id),
            "X-Roles": ",".join(self._identity.roles),
        }
        if idempotency_key is not None:
            headers["Idempotency-Key"] = idempotency_key
        return headers

    async def create_goal(
        self, payload: dict[str, Any], idempotency_key: str | None = None
    ) -> dict[str, Any]:
        response = await self._client.post(
            "/v1/goals",
            json=payload,
            headers=self._headers(idempotency_key or str(uuid4())),
        )
        response.raise_for_status()
        return dict(response.json())

    async def start_run(self, goal_id: UUID, idempotency_key: str | None = None) -> dict[str, Any]:
        response = await self._client.post(
            f"/v1/goals/{goal_id}/runs",
            headers=self._headers(idempotency_key or str(uuid4())),
        )
        response.raise_for_status()
        return dict(response.json())

    async def get_run(self, run_id: UUID) -> dict[str, Any]:
        response = await self._client.get(f"/v1/runs/{run_id}", headers=self._headers())
        response.raise_for_status()
        return dict(response.json())

    async def close(self) -> None:
        await self._client.aclose()
