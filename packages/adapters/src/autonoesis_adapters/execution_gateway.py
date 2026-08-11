"""Concrete governed-tool boundary adapters."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol
from uuid import uuid4

from autonoesis_domain import Action
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
        self._grants: set[tuple[str, str, str]] = set()

    def grant(self, delegation_id: str, tool_name: str, resource_prefix: str) -> None:
        self._grants.add((delegation_id, tool_name, resource_prefix))

    def revoke(self, delegation_id: str) -> None:
        self._grants = {grant for grant in self._grants if grant[0] != delegation_id}

    async def authorize(
        self, context: AuthorizationContext, action: Action, tool: ResolvedToolVersion
    ) -> bool:
        if context.delegation_id is None:
            return "platform_admin" in context.roles
        return any(
            delegation_id == context.delegation_id
            and tool_name == tool.tool_name
            and action.resource_scope.startswith(prefix)
            for delegation_id, tool_name, prefix in self._grants
        )


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
