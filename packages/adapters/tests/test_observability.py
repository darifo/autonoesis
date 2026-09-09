"""Tests for telemetry, redaction, FinOps phases, and event-driven SLOs."""

import logging
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

import pytest
from autonoesis_adapters import InMemoryPlatformStore
from autonoesis_adapters.observability import (
    AuditEventSloProjector,
    CostPhase,
    CostPhaseLedger,
)
from autonoesis_adapters.telemetry import (
    JsonRedactingFormatter,
    configure_telemetry,
    redact_value,
)
from autonoesis_application import AuditEvent
from autonoesis_evolution import SLI
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter


class TestRedaction:
    def test_sensitive_keys_and_blobs_are_redacted(self) -> None:
        payload = {
            "api_key": "abcdefghij",
            "Authorization": "Bearer xyz",
            "nested": {"password": "hunter2", "safe": "value"},
            "items": ["plain", "a" * 64],
            "count": 7,
        }
        redacted = redact_value(payload)
        assert redacted["api_key"] == "[redacted]"
        assert redacted["Authorization"] == "[redacted]"
        assert redacted["nested"]["password"] == "[redacted]"
        assert redacted["nested"]["safe"] == "value"
        assert redacted["items"][1] == "[redacted]"
        assert redacted["count"] == 7

    def test_json_formatter_emits_redacted_structured_output(self) -> None:
        formatter = JsonRedactingFormatter("test-service")
        record = logging.LogRecord(
            name="autonoesis.test",
            level=logging.INFO,
            pathname=__file__,
            lineno=1,
            msg="executed action",
            args=(),
            exc_info=None,
        )
        record.structured = {"tool": "records", "secret_token": "abcdef"}
        output = formatter.format(record)
        assert '"service": "test-service"' in output
        assert '"secret_token": "[redacted]"' in output
        assert '"tool": "records"' in output


class TestTelemetrySpans:
    def test_repository_facts_create_spans(self) -> None:
        exporter = InMemorySpanExporter()
        configure_telemetry("test", None, exporter=exporter)

        async def scenario() -> None:
            from autonoesis_adapters.persistence import create_repository
            from autonoesis_capability import parse_manifest

            engine, repository = create_repository("sqlite+aiosqlite://")
            from autonoesis_adapters.persistence_schema import metadata

            async with engine.begin() as connection:
                await connection.run_sync(metadata.create_all)
            try:
                await repository.install_pack(
                    uuid4(),
                    parse_manifest(
                        {
                            "api_version": "autonoesis/v1alpha1",
                            "pack_id": "span-pack",
                            "version": "1.0.0",
                            "python_entry_point": "span_pack.plugin:create",
                            "goal_types": [
                                {
                                    "goal_type": "span-pack.run",
                                    "input_schema": {"type": "object"},
                                    "agent": "a",
                                    "evaluation_suite": "s",
                                    "default_policy": "p",
                                    "default_budget": 1,
                                }
                            ],
                            "skills": [],
                            "tools": [],
                            "policies": ["p"],
                            "evaluation_suites": ["s"],
                        }
                    ),
                )
            finally:
                await engine.dispose()

        import asyncio

        asyncio.run(scenario())
        names = [span.name for span in exporter.get_finished_spans()]
        assert "autonoesis.fact.capability_pack.installed" in names

    def test_configure_telemetry_without_endpoint_is_a_noop(self) -> None:
        assert configure_telemetry("test", None) is None


class TestCostPhaseLedger:
    @pytest.mark.asyncio
    async def test_phases_persist_and_summarize(self) -> None:
        store = InMemoryPlatformStore()
        tenant, run = uuid4(), uuid4()
        ledger = CostPhaseLedger(store)
        await ledger.estimate(tenant, run, 100, "estimate:plan-1")
        await ledger.reserve(tenant, run, 60, "reserve:reservation-1")
        await ledger.settle(tenant, run, 55, "settle:receipt-1")
        await ledger.retry_waste(tenant, run, 5, "waste:attempt-2")

        summary = await ledger.summarize_run(tenant, run)
        assert summary == {"estimate": 100, "reserve": 60, "settle": 55, "retry_waste": 5}

    @pytest.mark.asyncio
    async def test_legacy_gateway_entries_count_as_reserves(self) -> None:
        store = InMemoryPlatformStore()
        tenant, run = uuid4(), uuid4()
        from autonoesis_domain import BudgetAmount, BudgetUnit

        await store.record_budget_entry(
            tenant, run, "tool_execution", BudgetAmount(30, BudgetUnit.COST_UNITS), "r:1"
        )
        summary = await CostPhaseLedger(store).summarize_run(tenant, run)
        assert summary["reserve"] == 30

    @pytest.mark.asyncio
    async def test_invalid_entries_are_rejected(self) -> None:
        store = InMemoryPlatformStore()
        ledger = CostPhaseLedger(store)
        tenant, run = uuid4(), uuid4()
        with pytest.raises(ValueError, match="non-negative"):
            await ledger.record(tenant, run, CostPhase.SETTLE, -1, "r:x")
        with pytest.raises(ValueError, match="reference"):
            await ledger.record(tenant, run, CostPhase.SETTLE, 1, "  ")


class TestAuditEventSloProjector:
    @staticmethod
    def _event(tenant: UUID, event_type: str, when: datetime) -> AuditEvent:
        return AuditEvent(
            tenant_id=tenant,
            actor_id=uuid4(),
            principal_id=uuid4(),
            event_type=event_type,
            object_type="outcome",
            object_id=str(uuid4()),
            correlation_id=uuid4(),
            details={},
            created_at=when,
        )

    @pytest.mark.asyncio
    async def test_projects_real_event_counts_into_weighted_measurements(self) -> None:
        tenant = uuid4()
        now = datetime.now(UTC)
        events: list[Any] = []
        for _ in range(9):
            events.append(self._event(tenant, "outcome.recorded", now))
        for _ in range(6):
            events.append(self._event(tenant, "outcome.verified", now))
        for _ in range(4):
            events.append(self._event(tenant, "action.governed_execution_recorded", now))
        events.append(self._event(tenant, "action.reconciled", now))
        # Outside the window: must never contribute to the measurement.
        events.append(self._event(tenant, "outcome.recorded", now - timedelta(days=90)))

        async def list_events(tenant_id: UUID) -> tuple[Any, ...]:
            return tuple(events) if tenant_id == tenant else ()

        registry = await AuditEventSloProjector(list_events).project(tenant, now=now)
        budget = await registry.compute_budget(SLI.OUTCOME_SUCCESS_RATE, now)
        assert budget.consumed == pytest.approx(max(0.0, 0.95 - 6 / 9))
        unknown = await registry.compute_budget(SLI.ACTION_UNKNOWN_RATE, now)
        assert unknown.consumed == pytest.approx(max(0.0, 0.25 - 0.01))

    @pytest.mark.asyncio
    async def test_no_events_yield_full_budgets_not_fabricated_values(self) -> None:
        async def list_events(_: UUID) -> tuple[Any, ...]:
            return ()

        registry = await AuditEventSloProjector(list_events).project(uuid4())
        budget = await registry.compute_budget(SLI.OUTCOME_SUCCESS_RATE)
        assert budget.consumed == 0.0
        assert budget.remaining == pytest.approx(0.05)
