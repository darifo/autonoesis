"""Canonical tenant namespaces for every non-relational runtime surface."""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum
from uuid import UUID


class IsolationRiskPool(StrEnum):
    READ = "read"
    WRITE = "write"
    HIGH_RISK = "high-risk"

    @classmethod
    def from_risk_tier(cls, risk_tier: str) -> IsolationRiskPool:
        normalized = risk_tier.strip().lower()
        if normalized in {"critical", "high"}:
            return cls.HIGH_RISK
        if normalized in {"medium", "write"}:
            return cls.WRITE
        return cls.READ


@dataclass(frozen=True, slots=True)
class TenantNamespaces:
    """Derive stable, non-overlapping names from one validated Tenant ID."""

    tenant_id: UUID
    prefix: str = "autonoesis"

    def __post_init__(self) -> None:
        if re.fullmatch(r"[a-z][a-z0-9-]{0,31}", self.prefix) is None:
            raise ValueError("namespace prefix must be a bounded DNS-safe label")

    @property
    def tenant_token(self) -> str:
        return self.tenant_id.hex

    def object_prefix(self, resource: str) -> str:
        return f"tenants/{self.tenant_id}/{self._label(resource)}/"

    def cache_key(self, logical_key: str) -> str:
        return f"{self.prefix}:tenant:{self.tenant_id}:{self._label(logical_key, separator=':')}"

    def search_index(self, logical_name: str) -> str:
        return f"{self.prefix}-t-{self.tenant_token}-{self._label(logical_name)}"

    def vector_collection(self, logical_name: str) -> str:
        return f"{self.prefix}_t_{self.tenant_token}_{self._label(logical_name, separator='_')}"

    def message_topic(self, logical_name: str) -> str:
        return f"{self.prefix}.tenant.{self.tenant_id}.{self._label(logical_name, separator='.')}"

    def workflow_namespace(self, risk_pool: IsolationRiskPool) -> str:
        return f"{self.prefix}-t-{self.tenant_token}-{risk_pool.value}"

    def workflow_task_queue(self, risk_pool: IsolationRiskPool) -> str:
        return f"{self.prefix}-t-{self.tenant_token}-{risk_pool.value}"

    def workflow_id(self, run_id: UUID) -> str:
        return f"tenant-{self.tenant_token}-goal-run-{run_id}"

    def worker_pool(self, risk_pool: IsolationRiskPool) -> str:
        return f"{self.prefix}/tenant/{self.tenant_id}/{risk_pool.value}"

    def telemetry_attributes(self) -> dict[str, str]:
        return {"autonoesis.tenant.id": str(self.tenant_id)}

    def evaluation_dataset(self, logical_name: str) -> str:
        return f"{self.prefix}/tenants/{self.tenant_id}/evaluations/{self._label(logical_name)}"

    def audit_export_prefix(self) -> str:
        return self.object_prefix("audit-exports")

    def resource_registry(self, logical_name: str, risk_pool: IsolationRiskPool) -> dict[str, str]:
        """Return the complete physical namespace contract persisted by control planes."""

        label = self._label(logical_name)
        return {
            "object": self.object_prefix(logical_name),
            "cache": self.cache_key(logical_name),
            "search": self.search_index(logical_name),
            "vector": self.vector_collection(logical_name),
            "topic": self.message_topic(logical_name),
            "workflow": self.workflow_namespace(risk_pool),
            "telemetry": f"{self.prefix}/tenants/{self.tenant_id}/telemetry/{label}",
            "evaluation_dataset": self.evaluation_dataset(logical_name),
            "audit_export": self.audit_export_prefix(),
        }

    @staticmethod
    def _label(value: str, *, separator: str = "-") -> str:
        normalized = re.sub(r"[^a-z0-9]+", separator, value.strip().lower()).strip(separator)
        if not normalized or len(normalized) > 80:
            raise ValueError("logical namespace name must be non-empty and at most 80 characters")
        return normalized


@dataclass(frozen=True, slots=True)
class TenantTelemetryRecord:
    """An exportable signal that cannot exist without explicit tenant ownership."""

    tenant_id: UUID
    signal_type: str
    trace_id: str
    payload: dict[str, object]

    def __post_init__(self) -> None:
        if self.signal_type not in {"trace", "log", "metric"} or not self.trace_id.strip():
            raise ValueError("telemetry requires a supported signal type and trace identity")

    def for_export(self, requested_tenant: UUID) -> dict[str, object]:
        if requested_tenant != self.tenant_id:
            raise LookupError("telemetry record was not found")
        return {
            "tenant_id": str(self.tenant_id),
            "signal_type": self.signal_type,
            "trace_id": self.trace_id,
            "payload": self.payload,
            "attributes": TenantNamespaces(self.tenant_id).telemetry_attributes(),
        }
