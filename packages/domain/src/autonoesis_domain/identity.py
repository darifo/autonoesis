"""Enterprise identity, scoped delegation, and emergency authorization invariants."""

from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from enum import StrEnum
from uuid import UUID, uuid4


class IdentityKind(StrEnum):
    HUMAN = "human"
    SERVICE = "service"
    AGENT = "agent"


@dataclass(frozen=True, slots=True)
class EnterpriseIdentity:
    tenant_id: UUID
    actor_id: UUID
    principal_id: UUID
    subject: str
    kind: IdentityKind
    service_id: str | None = None
    agent_id: str | None = None

    def __post_init__(self) -> None:
        if not self.subject.strip():
            raise ValueError("identity subject is required")
        if self.kind is IdentityKind.SERVICE and not self.service_id:
            raise ValueError("service identity requires service_id")
        if self.kind is IdentityKind.AGENT and not self.agent_id:
            raise ValueError("agent identity requires agent_id")


@dataclass(frozen=True, slots=True)
class DelegationGrant:
    tenant_id: UUID
    grantor_principal_id: UUID
    delegate_principal_id: UUID
    tool_name: str
    resource_prefix: str
    purpose: str
    expires_at: datetime
    delegation_id: UUID = field(default_factory=uuid4)
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    revoked_at: datetime | None = None

    def __post_init__(self) -> None:
        if any(not value.strip() for value in (self.tool_name, self.resource_prefix, self.purpose)):
            raise ValueError("delegation tool, resource scope, and purpose are required")
        if self.expires_at.tzinfo is None or self.created_at.tzinfo is None:
            raise ValueError("delegation timestamps must be timezone-aware")
        if self.expires_at <= self.created_at:
            raise ValueError("delegation must be short-lived and expire after issuance")
        if self.grantor_principal_id == self.delegate_principal_id:
            raise ValueError("self-delegation is not permitted")

    def revoke(self, *, at: datetime | None = None) -> "DelegationGrant":
        return replace(self, revoked_at=at or datetime.now(UTC))

    def authorizes(
        self,
        *,
        tenant_id: UUID,
        principal_id: UUID,
        tool_name: str,
        resource: str,
        purpose: str,
        at: datetime | None = None,
    ) -> bool:
        now = at or datetime.now(UTC)
        return (
            self.revoked_at is None
            and now < self.expires_at
            and tenant_id == self.tenant_id
            and principal_id == self.delegate_principal_id
            and tool_name == self.tool_name
            and resource.startswith(self.resource_prefix)
            and purpose == self.purpose
        )


@dataclass(frozen=True, slots=True)
class TemporaryAuthorization:
    tenant_id: UUID
    principal_id: UUID
    scope: str
    reason: str
    expires_at: datetime
    authorization_id: UUID = field(default_factory=uuid4)
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    reviewed_by: UUID | None = None
    reviewed_at: datetime | None = None

    def __post_init__(self) -> None:
        if not self.scope.strip() or not self.reason.strip():
            raise ValueError("temporary authorization scope and reason are required")
        if self.expires_at.tzinfo is None or self.expires_at <= self.created_at:
            raise ValueError("temporary authorization requires a future timezone-aware expiry")

    def review(self, reviewer: UUID, *, at: datetime | None = None) -> "TemporaryAuthorization":
        if reviewer == self.principal_id:
            raise ValueError("emergency authorization requires independent post-review")
        return replace(self, reviewed_by=reviewer, reviewed_at=at or datetime.now(UTC))
