"""Development identity, OIDC validation, and OPA policy adapters."""

from dataclasses import dataclass
from functools import lru_cache
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
    allowed_token_types: tuple[str, ...] = ("access", "at+jwt")
    jwks_cache_seconds: int = 300


class OIDCValidator:
    def __init__(self, settings: OIDCSettings) -> None:
        self._settings = settings
        self._keys = jwt.PyJWKClient(
            settings.jwks_url,
            cache_keys=True,
            cache_jwk_set=True,
            lifespan=settings.jwks_cache_seconds,
        )

    def validate(self, token: str) -> IdentityContext:
        header = jwt.get_unverified_header(token)
        key = self._keys.get_signing_key_from_jwt(token)
        claims: dict[str, Any] = jwt.decode(
            token,
            key.key,
            algorithms=["RS256", "ES256"],
            audience=self._settings.audience,
            issuer=self._settings.issuer,
            options={"require": ["iss", "aud", "sub", "tenant_id", "exp", "iat"]},
        )
        token_type = str(claims.get("token_use", header.get("typ", ""))).lower()
        if token_type not in self._settings.allowed_token_types:
            raise jwt.InvalidTokenError("token type is not accepted")
        subject = str(claims["sub"])
        if not subject.strip():
            raise jwt.InvalidTokenError("token subject is required")
        return IdentityContext(
            tenant_id=UUID(claims["tenant_id"]),
            actor_id=UUID(subject),
            principal_id=UUID(claims.get("principal_id", subject)),
            roles=frozenset(claims.get("roles", ())),
            agent_id=claims.get("agent_id"),
            subject=subject,
            token_type=token_type,
        )


@lru_cache(maxsize=8)
def cached_oidc_validator(settings: OIDCSettings) -> OIDCValidator:
    """Reuse the PyJWKClient and its bounded JWKS cache for the process lifetime."""

    return OIDCValidator(settings)


class DevelopmentPolicy:
    async def authorize(self, context: AuthorizationContext, action: Action) -> PolicyDecision:
        allowed = bool(set(context.roles) & {"platform_admin", "tenant_admin", "operator"})
        requires_approval = action.risk_level.value not in {"l0_compute", "l1_read"}
        return PolicyDecision(
            allowed=allowed,
            requires_approval=requires_approval,
            reason="development role policy",
            policy_version=context.policy_version,
        )


class OPAPolicyAdapter:
    def __init__(
        self,
        base_url: str,
        policy_version: str,
        policy_path: str = "autonoesis/action/allow",
    ) -> None:
        self._base_url = base_url.rstrip("/")
        if not policy_version.strip():
            raise ValueError("OPA policy version must be immutable and non-empty")
        self._policy_version = policy_version
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
            policy_version=self._policy_version,
        )
