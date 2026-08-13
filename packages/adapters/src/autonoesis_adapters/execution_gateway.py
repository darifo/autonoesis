"""Concrete governed-tool boundary adapters."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol, cast
from uuid import UUID, uuid4

from autonoesis_domain import Action, DelegationGrant
from autonoesis_runtime import (
    AuthorizationContext,
    CredentialLease,
    ExecutionReservation,
    GatewayAuditRecord,
    ReservationDecision,
    ReservationStatus,
    ResolvedToolVersion,
    ToolReceipt,
    ToolResultStatus,
)
from jsonschema import Draft202012Validator
from sqlalchemy import func, insert, select, text, update
from sqlalchemy.engine import CursorResult
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from autonoesis_adapters.persistence_schema import (
    budget_ledger,
    goals,
    idempotency_records,
    runs,
)


class StaticToolCatalog:
    """Immutable exact-version catalog suitable for a fixed Run snapshot."""

    def __init__(self, definitions: tuple[ResolvedToolVersion, ...]) -> None:
        self._definitions = {(item.tool_name, item.version): item for item in definitions}

    async def resolve(self, tool_name: str, version: str) -> ResolvedToolVersion:
        try:
            return self._definitions[(tool_name, version)]
        except KeyError as exc:
            raise LookupError(f"tool version {tool_name}@{version} is not registered") from exc


class JsonSchemaValidator:
    async def validate(self, schema: dict[str, Any], value: dict[str, Any]) -> None:
        Draft202012Validator.check_schema(schema)
        errors = sorted(Draft202012Validator(schema).iter_errors(value), key=lambda item: item.path)
        if errors:
            raise ValueError(f"tool input schema rejected parameters: {errors[0].message}")


class InMemoryDelegationStore:
    """Live delegation decisions; revoke takes effect on the next gateway call."""

    def __init__(self) -> None:
        self._grants: dict[str, DelegationGrant | tuple[str, str]] = {}

    def grant(self, delegation_id: str, tool_name: str, resource_prefix: str) -> None:
        """Compatibility helper for unit fixtures without an authenticated principal."""
        self._grants[delegation_id] = (tool_name, resource_prefix)

    def grant_scoped(self, grant: DelegationGrant) -> None:
        self._grants[str(grant.delegation_id)] = grant

    def revoke(self, delegation_id: str) -> None:
        grant = self._grants.get(delegation_id)
        if isinstance(grant, DelegationGrant):
            self._grants[delegation_id] = grant.revoke()
        else:
            self._grants.pop(delegation_id, None)

    async def authorize(
        self, context: AuthorizationContext, action: Action, tool: ResolvedToolVersion
    ) -> bool:
        if context.delegation_id is None:
            return "platform_admin" in context.roles
        grant = self._grants.get(context.delegation_id)
        if isinstance(grant, DelegationGrant):
            return grant.authorizes(
                tenant_id=UUID(context.tenant_id),
                principal_id=UUID(context.principal_id),
                tool_name=tool.tool_name,
                resource=action.resource_scope,
                purpose=context.purpose,
            )
        return bool(
            grant and grant[0] == tool.tool_name and action.resource_scope.startswith(grant[1])
        )


class PostgreSQLDelegationStore:
    """Authoritative, execution-time lookup; decisions are never cached."""

    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self._sessions = sessions

    async def grant(self, grant: DelegationGrant) -> None:
        async with self._sessions.begin() as session:
            await session.execute(
                text("SELECT set_config('app.tenant_id', :tenant_id, true)"),
                {"tenant_id": str(grant.tenant_id)},
            )
            await session.execute(
                text(
                    "INSERT INTO delegations "
                    "(id, tenant_id, grantor_principal_id, delegate_principal_id, tool_name, "
                    "resource_prefix, purpose, expires_at, created_at) VALUES "
                    "(:id, :tenant_id, :grantor, :delegate, :tool, :resource, :purpose, "
                    ":expires_at, :created_at)"
                ),
                {
                    "id": str(grant.delegation_id),
                    "tenant_id": str(grant.tenant_id),
                    "grantor": str(grant.grantor_principal_id),
                    "delegate": str(grant.delegate_principal_id),
                    "tool": grant.tool_name,
                    "resource": grant.resource_prefix,
                    "purpose": grant.purpose,
                    "expires_at": grant.expires_at,
                    "created_at": grant.created_at,
                },
            )

    async def revoke(self, tenant_id: UUID, delegation_id: UUID) -> None:
        async with self._sessions.begin() as session:
            await session.execute(
                text("SELECT set_config('app.tenant_id', :tenant_id, true)"),
                {"tenant_id": str(tenant_id)},
            )
            result = await session.execute(
                text(
                    "UPDATE delegations SET revoked_at = now() "
                    "WHERE tenant_id = :tenant_id AND id = :id AND revoked_at IS NULL"
                ),
                {"tenant_id": str(tenant_id), "id": str(delegation_id)},
            )
            if cast(CursorResult[Any], result).rowcount != 1:
                raise LookupError("active delegation was not found")

    async def authorize(
        self, context: AuthorizationContext, action: Action, tool: ResolvedToolVersion
    ) -> bool:
        if context.delegation_id is None:
            return "platform_admin" in context.roles
        async with self._sessions.begin() as session:
            await session.execute(
                text("SELECT set_config('app.tenant_id', :tenant_id, true)"),
                {"tenant_id": context.tenant_id},
            )
            result = await session.execute(
                text(
                    "SELECT EXISTS (SELECT 1 FROM delegations WHERE tenant_id = :tenant_id "
                    "AND id = :id AND delegate_principal_id = :principal_id "
                    "AND tool_name = :tool AND :resource LIKE resource_prefix || '%' "
                    "AND purpose = :purpose AND revoked_at IS NULL AND expires_at > now())"
                ),
                {
                    "tenant_id": context.tenant_id,
                    "id": context.delegation_id,
                    "principal_id": context.principal_id,
                    "tool": tool.tool_name,
                    "resource": action.resource_scope,
                    "purpose": context.purpose,
                },
            )
            return bool(result.scalar_one())


class EphemeralCredentialBroker:
    """Returns only an opaque, short-lived credential reference."""

    def __init__(self, ttl: timedelta = timedelta(minutes=5)) -> None:
        self._ttl = ttl

    async def issue(
        self, context: AuthorizationContext, action: Action, tool: ResolvedToolVersion
    ) -> CredentialLease:
        del context, action
        return CredentialLease(
            reference=f"lease://{uuid4()}",
            scope=tool.credential_scope,
            expires_at=datetime.now(UTC) + self._ttl,
        )


class EgressToolAdapter(Protocol):
    async def execute(self, action: Action, credential: CredentialLease) -> ToolReceipt: ...

    async def verify(self, action: Action, receipt: ToolReceipt) -> bool: ...


class RegistryControlledEgress:
    """Allow egress only through an exact tool-version/provider registration."""

    def __init__(self, adapters: dict[tuple[str, str, str], EgressToolAdapter]) -> None:
        self._adapters = dict(adapters)

    async def execute(
        self, action: Action, tool: ResolvedToolVersion, credential: CredentialLease
    ) -> ToolReceipt:
        if credential.expires_at <= datetime.now(UTC):
            raise PermissionError("egress credential expired before use")
        if credential.scope != tool.credential_scope:
            raise PermissionError("egress credential scope differs from tool definition")
        adapter = self._resolve(tool)
        return await adapter.execute(action, credential)

    async def verify(self, action: Action, tool: ResolvedToolVersion, receipt: ToolReceipt) -> bool:
        return await self._resolve(tool).verify(action, receipt)

    def _resolve(self, tool: ResolvedToolVersion) -> EgressToolAdapter:
        try:
            return self._adapters[(tool.tool_name, tool.version, tool.provider)]
        except KeyError as exc:
            raise LookupError("tool is not registered in the controlled egress boundary") from exc


@dataclass(slots=True)
class _MemoryReservation:
    request: ExecutionReservation
    reservation_id: str
    receipt: ToolReceipt | None = None


class InMemoryAtomicExecutionReservations:
    """Deterministic model of the database atomic reservation semantics."""

    def __init__(self, limit: int = 10_000) -> None:
        self.limit = limit
        self.used: dict[tuple[str, str], int] = {}
        self._records: dict[tuple[str, str], _MemoryReservation] = {}
        self._by_id: dict[str, _MemoryReservation] = {}
        self._lock = asyncio.Lock()

    async def reserve(self, request: ExecutionReservation) -> ReservationDecision:
        key = (request.tenant_id, request.idempotency_key)
        async with self._lock:
            existing = self._records.get(key)
            if existing is not None:
                if existing.request.request_digest != request.request_digest:
                    return ReservationDecision(ReservationStatus.CONFLICT)
                if existing.receipt is None:
                    return ReservationDecision(ReservationStatus.IN_PROGRESS)
                if existing.receipt.status in {
                    ToolResultStatus.ACCEPTED,
                    ToolResultStatus.UNKNOWN,
                }:
                    return ReservationDecision(ReservationStatus.UNKNOWN, existing.reservation_id)
                return ReservationDecision(
                    ReservationStatus.CACHED, existing.reservation_id, existing.receipt
                )
            usage_key = (request.tenant_id, request.run_id)
            used = self.used.get(usage_key, 0)
            if used + request.cost_units > self.limit:
                return ReservationDecision(ReservationStatus.BUDGET_EXHAUSTED)
            reservation_id = str(uuid4())
            record = _MemoryReservation(request, reservation_id)
            self._records[key] = record
            self._by_id[reservation_id] = record
            self.used[usage_key] = used + request.cost_units
            return ReservationDecision(ReservationStatus.ACQUIRED, reservation_id)

    async def complete(self, tenant_id: str, reservation_id: str, receipt: ToolReceipt) -> None:
        del tenant_id
        async with self._lock:
            record = self._by_id[reservation_id]
            if record.receipt is not None and record.receipt != receipt:
                raise RuntimeError("execution reservation is already completed")
            record.receipt = receipt


class InMemoryGatewayAudit:
    def __init__(self) -> None:
        self.records: list[GatewayAuditRecord] = []

    async def record(self, item: GatewayAuditRecord) -> None:
        self.records.append(item)


class PostgreSQLAtomicExecutionReservations:
    """Serializable-by-key budget and idempotency reservation on PostgreSQL."""

    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        bind = sessions.kw.get("bind")
        if bind is None or bind.dialect.name != "postgresql":
            raise ValueError("atomic execution reservations require PostgreSQL")
        self._sessions = sessions

    async def reserve(self, request: ExecutionReservation) -> ReservationDecision:
        async with self._sessions.begin() as session:
            await session.execute(select(func.set_config("app.tenant_id", request.tenant_id, True)))
            # The authoritative unique constraint is Tenant + Key; the advisory lock must use
            # the same identity so different Tool versions race to a normalized conflict instead
            # of leaking a database uniqueness error.
            lock_identity = f"{request.tenant_id}:{request.idempotency_key}"
            await session.execute(
                text("SELECT pg_advisory_xact_lock(hashtextextended(:identity, 0))"),
                {"identity": lock_identity},
            )
            existing = (
                (
                    await session.execute(
                        select(idempotency_records).where(
                            idempotency_records.c.tenant_id == request.tenant_id,
                            idempotency_records.c.idempotency_key == request.idempotency_key,
                        )
                    )
                )
                .mappings()
                .one_or_none()
            )
            if existing is not None:
                return self._existing_decision(dict(existing), request)

            run_row = (
                await session.execute(
                    select(runs.c.goal_id)
                    .where(
                        runs.c.tenant_id == request.tenant_id,
                        runs.c.id == request.run_id,
                    )
                    .with_for_update()
                )
            ).one_or_none()
            if run_row is None:
                raise LookupError("reservation Run does not exist in the tenant")
            contract = await session.scalar(
                select(goals.c.contract).where(
                    goals.c.tenant_id == request.tenant_id,
                    goals.c.id == run_row.goal_id,
                )
            )
            if not isinstance(contract, dict):
                raise LookupError("reservation Goal does not exist in the tenant")
            if contract["budget_limit"]["unit"] != "cost_units":
                raise ValueError("tool execution requires a cost_units Goal budget")
            limit = int(contract["budget_limit"]["amount"])
            used = int(
                await session.scalar(
                    select(func.coalesce(func.sum(budget_ledger.c.amount), 0)).where(
                        budget_ledger.c.tenant_id == request.tenant_id,
                        budget_ledger.c.run_id == request.run_id,
                        budget_ledger.c.unit == "cost_units",
                    )
                )
                or 0
            )
            if used + request.cost_units > limit:
                return ReservationDecision(ReservationStatus.BUDGET_EXHAUSTED)

            now = datetime.now(UTC)
            reservation_id = str(uuid4())
            await session.execute(
                insert(idempotency_records).values(
                    id=reservation_id,
                    tenant_id=request.tenant_id,
                    run_id=request.run_id,
                    action_id=request.action_id,
                    tool_name=request.tool_name,
                    tool_version=request.tool_version,
                    idempotency_key=request.idempotency_key,
                    request_digest=request.request_digest,
                    cost_units=request.cost_units,
                    external_id=None,
                    status="pending",
                    response=None,
                    optimistic_version=1,
                    created_at=now,
                )
            )
            await session.execute(
                insert(budget_ledger).values(
                    id=str(uuid4()),
                    tenant_id=request.tenant_id,
                    run_id=request.run_id,
                    category="tool_execution",
                    amount=request.cost_units,
                    unit="cost_units",
                    reference=f"tool-reservation:{reservation_id}",
                    optimistic_version=1,
                    created_at=now,
                )
            )
            return ReservationDecision(ReservationStatus.ACQUIRED, reservation_id)

    async def complete(self, tenant_id: str, reservation_id: str, receipt: ToolReceipt) -> None:
        status = {
            "succeeded": "completed",
            "failed": "failed",
            "rejected": "failed",
            "unknown": "unknown",
            "accepted": "accepted",
        }[receipt.status.value]
        async with self._sessions.begin() as session:
            await session.execute(select(func.set_config("app.tenant_id", tenant_id, True)))
            result = await session.execute(
                update(idempotency_records)
                .where(
                    idempotency_records.c.id == reservation_id,
                    idempotency_records.c.tenant_id == tenant_id,
                    idempotency_records.c.status == "pending",
                )
                .values(
                    status=status,
                    external_id=receipt.external_id or None,
                    response={"output": list(receipt.output), "status": receipt.status.value},
                    optimistic_version=idempotency_records.c.optimistic_version + 1,
                    updated_at=datetime.now(UTC),
                )
            )
            if not isinstance(result, CursorResult) or result.rowcount != 1:
                raise RuntimeError("execution reservation was already finalized")

    @staticmethod
    def _existing_decision(
        row: dict[str, Any], request: ExecutionReservation
    ) -> ReservationDecision:
        if row["request_digest"] != request.request_digest:
            return ReservationDecision(ReservationStatus.CONFLICT)
        if row["tool_version"] not in {None, request.tool_version}:
            return ReservationDecision(ReservationStatus.CONFLICT)
        if row["status"] == "pending":
            return ReservationDecision(ReservationStatus.IN_PROGRESS, row["id"])
        if row["status"] in {"unknown", "accepted"}:
            return ReservationDecision(ReservationStatus.UNKNOWN, row["id"])
        response = row["response"] or {}
        receipt_status = "succeeded" if row["status"] == "completed" else "failed"
        receipt = ToolReceipt(
            row["external_id"] or "",
            ToolResultStatus(receipt_status),
            tuple(tuple(item) for item in response.get("output", ())),
        )
        return ReservationDecision(ReservationStatus.CACHED, row["id"], receipt)
