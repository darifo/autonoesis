"""Development identity, OIDC validation, and OPA policy adapters."""

from dataclasses import dataclass
from typing import Any
from uuid import UUID

import httpx
import jwt
from autonoesis_application import IdentityContext
from autonoesis_domain import Action
from autonoesis_runtime import AuthorizationContext, PolicyDecision


@dataclass(frozen=True, slots=True)
class OIDCSettings:
    issuer: str
    audience: str
    jwks_url: str


class OIDCValidator:
    def __init__(self, settings: OIDCSettings) -> None:
        self._settings = settings
        self._keys = jwt.PyJWKClient(settings.jwks_url)

    def validate(self, token: str) -> IdentityContext:
        key = self._keys.get_signing_key_from_jwt(token)
        claims: dict[str, Any] = jwt.decode(
            token,
            key.key,
            algorithms=["RS256", "ES256"],
            audience=self._settings.audience,
            issuer=self._settings.issuer,
        )
        return IdentityContext(
            tenant_id=UUID(claims["tenant_id"]),
            actor_id=UUID(claims["sub"]),
            principal_id=UUID(claims.get("principal_id", claims["sub"])),
            roles=frozenset(claims.get("roles", ())),
        )


class DevelopmentPolicy:
    async def authorize(self, context: AuthorizationContext, action: Action) -> PolicyDecision:
        allowed = bool(set(context.roles) & {"platform_admin", "tenant_admin", "operator"})
        requires_approval = action.risk_level.value not in {"l0_compute", "l1_read"}
        return PolicyDecision(
            allowed=allowed,
            requires_approval=requires_approval,
            reason="development role policy",
        )


class OPAPolicyAdapter:
    def __init__(self, base_url: str, policy_path: str = "autonoesis/action/allow") -> None:
        self._base_url = base_url.rstrip("/")
        self._policy_path = policy_path

    async def authorize(self, context: AuthorizationContext, action: Action) -> PolicyDecision:
        payload = {
            "input": {
                "identity": {
                    "tenant_id": context.tenant_id,
                    "actor_id": context.actor_id,
                    "principal_id": context.principal_id,
                    "agent_id": context.agent_id,
                    "roles": context.roles,
                },
                "action": {
                    "tool": action.tool_name,
                    "operation": action.operation,
                    "resource": action.resource_scope,
                    "risk": action.risk_level.value,
                    "parameter_digest": action.parameter_digest,
                },
            }
        }
        async with httpx.AsyncClient(timeout=5) as client:
            response = await client.post(
                f"{self._base_url}/v1/data/{self._policy_path}", json=payload
            )
            response.raise_for_status()
        result = response.json().get("result", {})
        return PolicyDecision(
            allowed=bool(result.get("allowed", False)),
            requires_approval=bool(result.get("requires_approval", False)),
            reason=str(result.get("reason", "OPA policy decision")),
        )
