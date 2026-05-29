"""
OpenTelemetry tracing utilities.

Initialization is conditional on OTEL_EXPORTER_OTLP_ENDPOINT being set.
When the endpoint is empty the OTel SDK's built-in no-op tracer is used —
no spans are created, no imports fail, and there is zero overhead.
"""

import logging
from typing import Optional

from opentelemetry import trace


class OtelTraceIdFilter(logging.Filter):
    """Injects trace_id and span_id into every log record emitted during a traced operation."""

    def filter(self, record: logging.LogRecord) -> bool:
        span = trace.get_current_span()
        ctx = span.get_span_context()
        if ctx.is_valid:
            record.trace_id = format(ctx.trace_id, "032x")
            record.span_id = format(ctx.span_id, "016x")
        else:
            record.trace_id = ""
            record.span_id = ""
        return True


def setup_otel(endpoint: str, service_name: str, engine: Optional[object]) -> None:
    """Configure the global OTel TracerProvider.

    When *endpoint* is empty this function returns immediately, leaving the
    default no-op tracer in place.  Auto-instrumentation for FastAPI,
    SQLAlchemy, and Celery is applied inline; callers must pass the FastAPI
    app via ``instrument_app`` after calling this function.
    """
    if not endpoint:
        return

    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import BatchSpanProcessor
    from opentelemetry.sdk.resources import Resource
    from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
    from opentelemetry.instrumentation.sqlalchemy import SQLAlchemyInstrumentor
    from opentelemetry.instrumentation.celery import CeleryInstrumentor

    resource = Resource.create({"service.name": service_name})
    provider = TracerProvider(resource=resource)
    provider.add_span_processor(
        BatchSpanProcessor(OTLPSpanExporter(endpoint=endpoint, insecure=True))
    )
    trace.set_tracer_provider(provider)

    if engine is not None:
        SQLAlchemyInstrumentor().instrument(engine=engine)

    CeleryInstrumentor().instrument()


def instrument_fastapi(app: object) -> None:
    """Apply FastAPI auto-instrumentation to *app* (only when OTel is active)."""
    from opentelemetry.sdk.trace import TracerProvider

    if not isinstance(trace.get_tracer_provider(), TracerProvider):
        return

    from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
    FastAPIInstrumentor.instrument_app(app)  # type: ignore[arg-type]
