# Distributed Tracing — OpenTelemetry Design Spec

**Issue**: [#103 — Implement distributed tracing (OpenTelemetry)](https://github.com/omniscient/markethawk/issues/103)  
**Date**: 2026-05-28  
**Status**: Pending Review

---

## Overview

MarketHawk has 13+ Docker services. A single scan triggered from the frontend traverses the FastAPI backend, dispatches Celery tasks, makes Polygon API calls (via DB reads from pre-synced aggregates), and writes scanner events — but today there is no way to see this flow as a single unit. Debugging a slow scan requires correlating timestamps across Seq log streams by hand.

This spec adds OpenTelemetry distributed tracing to the main backend + Celery worker/beat processes: auto-instrumentation for FastAPI, SQLAlchemy, and Celery; targeted manual spans for four key business methods; Seq log correlation via `trace_id` injection; and a Jaeger all-in-one container for the trace UI.

---

## Requirements

1. Every FastAPI HTTP request produces a trace with spans for all SQL queries it triggers.
2. When a request dispatches a Celery task, the trace context propagates so the task's spans appear as children of the HTTP span in the same trace.
3. The core scanner path (`run_universe_scan` → `ScannerService.run_pre_market_scan()`) shows per-ticker latency via child spans.
4. Batch enrichment cost (`_get_batch_enrichment_data()`) is visible as a distinct span.
5. Alert evaluation (`evaluate_scanner_alerts` → rule matching → notification dispatch) has two distinct child spans.
6. Every Seq log entry emitted during a traced operation carries the `trace_id` as a structured property, enabling log↔trace correlation.
7. Tracing is a no-op when `OTEL_EXPORTER_OTLP_ENDPOINT` is unset — no code paths blocked, no imports failing, no config required to disable it.
8. Jaeger UI is accessible at `http://localhost:16686` in development.
9. Scope is limited to `backend` (API) + `celery-worker` + `celery-beat` containers. The `live-scanner` and `tweet-monitor` are deferred to follow-up issues.

---

## Architecture

### Tracing backend: Jaeger all-in-one

`jaegertracing/all-in-one` is a single Docker container that bundles collector, storage, query engine, and UI. It accepts OTLP natively (since v1.35) over gRPC on port 4317. No Grafana, no collector sidecar, no agent required. The backend sends spans directly to `http://jaeger:4317` via the OTel SDK's standard OTLP exporter.

If the team later adopts Grafana (e.g., alongside Prometheus from issue #95), the backend instrumentation code is unchanged — only the `OTEL_EXPORTER_OTLP_ENDPOINT` target changes from Jaeger to Grafana Tempo. Zipkin is not used because its Python OTel exporter is less maintained than the OTLP path.

### SDK initialization

OTel is initialized once in `main.py`'s `create_app()` function, before any middleware or router registration. Initialization is conditional on `OTEL_EXPORTER_OTLP_ENDPOINT` being set; when unset, the OTel SDK defaults to its built-in no-op tracer with zero overhead.

```python
# backend/app/main.py — inside create_app()
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.instrumentation.sqlalchemy import SQLAlchemyInstrumentor
from opentelemetry.instrumentation.celery import CeleryInstrumentor

def _setup_otel(app: FastAPI) -> None:
    endpoint = settings.OTEL_EXPORTER_OTLP_ENDPOINT
    if not endpoint:
        return  # no-op tracer by default

    provider = TracerProvider()
    provider.add_span_processor(
        BatchSpanProcessor(OTLPSpanExporter(endpoint=endpoint))
    )
    trace.set_tracer_provider(provider)

    FastAPIInstrumentor.instrument_app(app)
    SQLAlchemyInstrumentor().instrument(engine=engine)
    CeleryInstrumentor().instrument()
```

The Celery instrumentor patches `apply_async` to inject the current trace context into task headers, and wraps task execution to extract that context and create a child span. This is the mechanism behind requirement 2 — no additional code in task bodies is needed for propagation.

### Trace_id injection into Seq logs

A `logging.Filter` subclass reads the current OTel span at log-emit time and adds `trace_id` and `span_id` as extra fields. Because Seq receives structured JSON (CLEF format via `SeqErrorTracker`), these fields appear as filterable properties.

```python
class OtelTraceIdFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        span = trace.get_current_span()
        ctx = span.get_span_context()
        record.trace_id = format(ctx.trace_id, "032x") if ctx.is_valid else ""
        record.span_id = format(ctx.span_id, "016x") if ctx.is_valid else ""
        return True
```

Attached to the root logger in `create_app()` immediately after `logging.basicConfig()`. This populates `trace_id` on every log record emitted during a traced operation; log records outside any span get an empty string (harmless).

### Manual spans

Four methods receive explicit `tracer.start_as_current_span()` calls. These are the only code changes in the services layer:

| Method | File | Span name | Key attributes |
|--------|------|-----------|----------------|
| `run_universe_scan` (Celery task) | `tasks/scanning.py` | `scanner.universe_scan` | `universe_id`, `scanner_type`, `scan_id` |
| `ScannerService.run_pre_market_scan()` (per-ticker loop) | `services/scanner.py` | `scanner.evaluate_ticker` | `ticker`, `scanner_type` |
| `ScannerService._get_batch_enrichment_data()` | `services/scanner.py` | `scanner.batch_enrichment` | `ticker_count` |
| `evaluate_scanner_alerts` (match + dispatch) | `tasks/scanning.py` | `alerts.evaluate`, `alerts.dispatch` | `event_id`, `rules_matched` |

The per-ticker span is a child span created inside the existing `for ticker in tickers` loop — one span per ticker, naturally capturing which tickers are slow.

### Docker composition

```yaml
# docker-compose.yml addition
jaeger:
  image: jaegertracing/all-in-one:1.57
  container_name: markethawk-jaeger
  restart: unless-stopped
  ports:
    - "127.0.0.1:16686:16686"  # Jaeger UI
    - "4317:4317"               # OTLP gRPC receiver (backend → jaeger)
  environment:
    COLLECTOR_OTLP_ENABLED: "true"
  networks:
    - stockscanner-network
```

The `backend`, `celery-worker`, and `celery-beat` service definitions gain:

```yaml
environment:
  OTEL_EXPORTER_OTLP_ENDPOINT: http://jaeger:4317
  OTEL_SERVICE_NAME: markethawk-backend  # or markethawk-worker
```

The `OTEL_SERVICE_NAME` distinguishes API spans from worker spans in the Jaeger UI.

---

## Files Changed

| File | Change |
|------|--------|
| `backend/requirements.txt` | Add `opentelemetry-api`, `opentelemetry-sdk`, `opentelemetry-exporter-otlp-proto-grpc`, `opentelemetry-instrumentation-fastapi`, `opentelemetry-instrumentation-sqlalchemy`, `opentelemetry-instrumentation-celery` |
| `backend/app/core/config.py` | Add `OTEL_EXPORTER_OTLP_ENDPOINT: str = ""` and `OTEL_SERVICE_NAME: str = "markethawk"` to `Settings` |
| `backend/app/main.py` | Add `_setup_otel()` call in `create_app()`, add `OtelTraceIdFilter` and attach to root logger |
| `backend/app/services/scanner.py` | Add manual spans in `run_pre_market_scan()` (per-ticker) and `_get_batch_enrichment_data()` |
| `backend/app/tasks/scanning.py` | Add manual spans in `run_universe_scan` and `evaluate_scanner_alerts` |
| `docker-compose.yml` | Add `jaeger` service; add `OTEL_EXPORTER_OTLP_ENDPOINT` + `OTEL_SERVICE_NAME` to `backend`, `celery-worker`, `celery-beat` |
| `ENV_VARIABLES.md` | Document `OTEL_EXPORTER_OTLP_ENDPOINT` and `OTEL_SERVICE_NAME` |
| `CLAUDE.md` | Add Jaeger UI `http://localhost:16686` to the Service Ports table |

---

## Alternatives Considered

### A: Auto-instrumentation only (no manual spans)

Simpler — zero service-layer code changes. Auto-instrumentation produces HTTP request spans and individual SQL query spans. Rejected because it cannot attribute latency to specific tickers within a batch scan, and it won't show the business-level split between alert rule matching and notification dispatch. The issue's explicit goal of tracing "scanner run → Polygon API calls → database writes" cannot be satisfied without per-ticker spans.

### B: Auto-instrumentation + targeted manual spans (chosen)

Bounded scope (4 methods, 2 files) with high diagnostic value. The per-ticker child span in `run_pre_market_scan()` is the single most actionable trace for the scanner's core use case. The logging filter adds Seq correlation for free.

### C: Grafana Tempo + Grafana stack

Higher operational value long-term (unified logs + metrics + traces in one UI) but requires two additional containers (Tempo + Grafana) before any tracing value is delivered. The OTel SDK's OTLP exporter is backend-agnostic — switching from Jaeger to Tempo later requires only changing `OTEL_EXPORTER_OTLP_ENDPOINT`, not any application code. Deferred until Prometheus (#95) is implemented.

### D: Custom OTEL_ENABLED flag (like SEQ_URL pattern)

Rejected. The OTel SDK's no-op tracer is its first-class "disabled" state. Adding a MarketHawk-specific `OTEL_ENABLED` flag would duplicate that mechanism unnecessarily. `OTEL_EXPORTER_OTLP_ENDPOINT=""` is the OTel-standard way to disable export; any operator familiar with OTel knows this.

---

## Open Questions (non-blocking)

1. **Sampling rate**: Jaeger all-in-one defaults to 100% sampling. For high-frequency ticker scans (a scan run that evaluates hundreds of tickers will produce thousands of spans), a head-based probability sampler (e.g., 10%) may be worth adding once volume is observed. Can be added without code changes via `OTEL_TRACES_SAMPLER=parentbased_traceidratio` and `OTEL_TRACES_SAMPLER_ARG=0.1` env vars.

2. **Live-scanner OTel**: The live-scanner is a bare asyncio process (no ASGI lifespan hook). Instrumenting its 5-second IBKR bar callbacks requires careful sampling design. Deferred to a follow-up issue.

3. **Tweet-monitor OTel**: Separate FastAPI deployment with its own SQLAlchemy engine. Straightforward once the pattern is established here, but out of scope. Deferred to a follow-up issue.

4. **Frontend trace propagation**: Browser → API trace linking (via `traceparent` header injection in Axios) is not in scope. Would require a frontend instrumentation package and CORS header changes.

---

## Assumptions

- `ASSUMPTION`: Jaeger all-in-one's in-memory storage is acceptable for development. Traces are ephemeral (lost on container restart). Badger/Elasticsearch backends can be added in production if persistence is needed.
- `ASSUMPTION`: The `opentelemetry-instrumentation-sqlalchemy` package is compatible with SQLAlchemy 2.0's async engine. This needs verification against the OTel contrib package version matrix before implementation.
- `ASSUMPTION`: Celery context propagation via `opentelemetry-instrumentation-celery` works with the Redis broker (`settings.REDIS_URL`). The instrumentor injects context into task headers using W3C TraceContext format — this is broker-agnostic.
- `ASSUMPTION`: Port 4317 (OTLP gRPC) is available on the host. The existing service port table uses 4003 and 4004 (IBKR socat), so no conflict.
