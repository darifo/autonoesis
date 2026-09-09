"""OpenTelemetry wiring and redacting structured logging for platform processes.

Every process (API, Worker, gateways, repository) shares this module so spans,
trace↔correlation linkage, and JSON logs behave identically. Telemetry stays
optional: without an OTLP endpoint the tracer is a no-op and processes run
uninstrumented, never failing startup or tests.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any

from opentelemetry import trace
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor, SpanExporter
from opentelemetry.trace import Span

_SENSITIVE_KEY = re.compile(
    r"(?i)(password|passwd|secret|token|api[_-]?key|authorization|credential|cookie|"
    r"private[_-]?key|session[_-]?id|bearer|aws[_-]?access|aws[_-]?secret)"
)
# Long homogeneous blobs: hex/base64-ish material that should never reach logs.
_BLOB = re.compile(r"^[A-Za-z0-9+/=_-]{40,}$")

_REDACTED = "[redacted]"


def redact_value(value: Any) -> Any:
    """Recursively scrub secrets and credential-shaped blobs from log payloads."""
    if isinstance(value, dict):
        return {
            key: _REDACTED if _SENSITIVE_KEY.search(str(key)) else redact_value(item)
            for key, item in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [redact_value(item) for item in value]
    if isinstance(value, str) and _BLOB.fullmatch(value):
        return _REDACTED
    return value


class JsonRedactingFormatter(logging.Formatter):
    """Emit one JSON object per record with secrets redacted and context attached."""

    def __init__(self, service: str, *, tenant_field: str = "tenant_id") -> None:
        super().__init__()
        self._service = service
        self._tenant_field = tenant_field

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": self.formatTime(record, datefmt="%Y-%m-%dT%H:%M:%S%z"),
            "level": record.levelname,
            "service": self._service,
            "logger": record.name,
            "message": record.getMessage(),
        }
        span_context = trace.get_current_span().get_span_context()
        if span_context.is_valid:
            payload["trace_id"] = format(span_context.trace_id, "032x")
            payload["span_id"] = format(span_context.span_id, "016x")
        contextual = {
            key: value
            for key, value in {
                "tenant_id": getattr(record, "tenant_id", None),
                "correlation_id": getattr(record, "correlation_id", None),
                "event_type": getattr(record, "event_type", None),
            }.items()
            if value is not None
        }
        payload.update(contextual)
        extra = getattr(record, "structured", None)
        if isinstance(extra, dict):
            payload["details"] = redact_value(extra)
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False, default=str)


def configure_json_logging(service: str, *, level: int = logging.INFO) -> None:
    """Route root logging through the redacting JSON formatter (idempotent)."""
    root = logging.getLogger()
    for handler in list(root.handlers):
        root.removeHandler(handler)
    handler = logging.StreamHandler()
    handler.setFormatter(JsonRedactingFormatter(service))
    root.addHandler(handler)
    root.setLevel(level)


def configure_telemetry(
    service_name: str,
    otlp_endpoint: str | None,
    *,
    exporter: SpanExporter | None = None,
) -> TracerProvider | None:
    """Install a global TracerProvider; absent endpoint leaves tracing off.

    Tests may pass an in-memory exporter to observe spans without a collector.
    """
    if not otlp_endpoint and exporter is None:
        return None
    provider = TracerProvider(resource=Resource.create({"service.name": service_name}))
    if exporter is not None:
        from opentelemetry.sdk.trace.export import SimpleSpanProcessor

        provider.add_span_processor(SimpleSpanProcessor(exporter))
    else:
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter

        assert otlp_endpoint is not None
        provider.add_span_processor(
            BatchSpanProcessor(OTLPSpanExporter(endpoint=f"{otlp_endpoint.rstrip('/')}/v1/traces"))
        )
    trace.set_tracer_provider(provider)
    return provider


class _SyncSpanProcessor(BatchSpanProcessor):
    """Test-friendly synchronous export of finished spans."""

    def __init__(self, exporter: SpanExporter) -> None:
        super().__init__(exporter, schedule_delay_millis=0)


def tracer(name: str = "autonoesis") -> Any:
    return trace.get_tracer(name)


def span_attributes(
    *,
    tenant_id: Any = None,
    correlation_id: Any = None,
    **extra: Any,
) -> dict[str, Any]:
    attributes = dict(extra)
    if tenant_id is not None:
        attributes["autonoesis.tenant.id"] = str(tenant_id)
    if correlation_id is not None:
        attributes["autonoesis.correlation.id"] = str(correlation_id)
    return attributes


def link_span_to_correlation(span: Span, correlation_id: Any) -> None:
    if correlation_id is not None:
        span.set_attribute("autonoesis.correlation.id", str(correlation_id))


__all__ = [
    "JsonRedactingFormatter",
    "configure_json_logging",
    "configure_telemetry",
    "link_span_to_correlation",
    "redact_value",
    "span_attributes",
    "tracer",
]
