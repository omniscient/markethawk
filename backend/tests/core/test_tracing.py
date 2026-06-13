"""Unit tests for OpenTelemetry tracing utilities."""
import logging


def test_otel_config_defaults():
    from app.core.config import Settings
    fields = Settings.model_fields
    assert fields["OTEL_EXPORTER_OTLP_ENDPOINT"].default == ""
    assert fields["OTEL_SERVICE_NAME"].default == "markethawk"


def test_otel_trace_id_filter_no_active_span():
    """Filter produces empty trace_id/span_id when no OTel span is active."""
    from app.core.tracing import OtelTraceIdFilter

    f = OtelTraceIdFilter()
    record = logging.LogRecord(
        name="test", level=logging.INFO, pathname="", lineno=0,
        msg="hello", args=(), exc_info=None,
    )
    result = f.filter(record)
    assert result is True
    assert record.trace_id == ""
    assert record.span_id == ""


def test_otel_trace_id_filter_with_active_span():
    """Filter populates trace_id/span_id fields when a span is active."""
    from opentelemetry.sdk.trace import TracerProvider

    from app.core.tracing import OtelTraceIdFilter

    provider = TracerProvider()
    tracer = provider.get_tracer("test")

    f = OtelTraceIdFilter()
    with tracer.start_as_current_span("test-span"):
        record = logging.LogRecord(
            name="test", level=logging.INFO, pathname="", lineno=0,
            msg="hello", args=(), exc_info=None,
        )
        result = f.filter(record)

    assert result is True
    assert len(record.trace_id) == 32
    assert len(record.span_id) == 16


def test_setup_otel_noop_when_endpoint_empty(monkeypatch):
    """_setup_otel() is a no-op when OTEL_EXPORTER_OTLP_ENDPOINT is empty."""
    from opentelemetry import trace as otel_trace

    from app.core.tracing import setup_otel

    # Reset any SDK provider set by app startup or a prior test run
    monkeypatch.setattr(otel_trace, "_TRACER_PROVIDER", None)

    setup_otel(endpoint="", service_name="test", engine=None)
    # The global tracer provider should remain the default (ProxyTracerProvider or NoOpTracerProvider)
    provider = otel_trace.get_tracer_provider()
    # Just verify we can get a tracer without error and it's not an SDK TracerProvider
    from opentelemetry.sdk.trace import TracerProvider as SDKProvider
    assert not isinstance(provider, SDKProvider)


def test_setup_otel_registers_sdk_provider(monkeypatch):
    """_setup_otel() registers an SDK TracerProvider when endpoint is set."""
    from opentelemetry import trace as otel_trace
    from opentelemetry.sdk.trace import TracerProvider as SDKProvider

    from app.core.tracing import setup_otel

    # Use a fake endpoint — we don't actually connect
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://fake-jaeger:4317")

    setup_otel(endpoint="http://fake-jaeger:4317", service_name="test-svc", engine=None)
    provider = otel_trace.get_tracer_provider()
    assert isinstance(provider, SDKProvider)

    # Restore default provider so other tests are not affected
    otel_trace._TRACER_PROVIDER = None
