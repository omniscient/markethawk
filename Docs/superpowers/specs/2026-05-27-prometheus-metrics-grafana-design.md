# Prometheus Metrics and Grafana Dashboards Design

**Date**: 2026-05-27  
**Status**: Draft  
**Scope**: Add Prometheus instrumentation to FastAPI and Celery workers, provision Prometheus + Grafana services in Docker Compose, and ship pre-configured dashboards and alerting rules as code.

---

## Overview

MarketHawk currently has zero application metrics — no request rate, no latency percentiles, no scan throughput, no database or Celery visibility. The architecture audit scored Metrics at 0/5. Performance degradation, capacity issues, and usage patterns are invisible until they cause failures.

This spec adds a complete metrics layer:

1. **FastAPI instrumentation** — auto HTTP metrics + custom domain counters/histograms
2. **Celery task instrumentation** — counters/histograms emitted directly from task code
3. **Prometheus service** — scrapes all metrics endpoints on the internal Docker network
4. **Grafana service** — pre-configured dashboards and alerting rules provisioned from files in the repo
5. **Infrastructure alerting** — three threshold rules wired through the existing `NotificationDispatcher`

---

## Requirements

From the Q&A brainstorming:

- FastAPI HTTP metrics (request rate, latency p50/p95/p99, error rate) via `prometheus-fastapi-instrumentator`
- Custom business metrics: `scanner_events_total`, `scan_duration_seconds`, `polygon_api_calls_total`, `ibkr_connection_status`, `celery_tasks_total`, `active_websocket_connections`
- DB pool metrics using `engine.pool` (available immediately from SQLAlchemy's default QueuePool); will be re-evaluated after #85 tunes pool size
- Celery metrics emitted from inside task code using `prometheus_client` directly (no sidecar exporter)
- `/metrics` endpoint exposed on `backend:8000` on the internal Docker network only — not a new port
- Prometheus scrapes `http://backend:8000/metrics` using Docker DNS
- Grafana dashboards committed as JSON provisioning files under `grafana/provisioning/`
- Alerting implemented via Grafana's built-in alerting (no Alertmanager container) — threshold rules fire a webhook to a new `POST /api/alerts/infrastructure` FastAPI endpoint that routes to the existing `NotificationDispatcher`
- Prometheus on port **9090**, Grafana on port **3001**

Out of scope:
- Full Prometheus Alertmanager deployment (deferred)
- Distributed tracing (separate feature)
- Per-user or per-universe metrics dimensions (future)
- Celery queue depth metrics from Redis (sidecar approach — deferred)

---

## Architecture

```
                         stockscanner-network
                         ┌────────────────────────────────────────────┐
                         │                                            │
  Browser                │  frontend:3333                             │
  http://localhost:3001 ──> grafana:3001 ──HTTP──> prometheus:9090    │
  http://localhost:9090 ──> prometheus:9090                           │
                         │       │                                    │
                         │       │ scrape http://backend:8000/metrics │
                         │       └─────────────> backend:8000         │
                         │                           │                │
                         │  celery-worker ──> same DB/Redis           │
                         │  (metrics emitted to same /metrics         │
                         │   via shared prometheus_client registry)   │
                         │                                            │
                         │  prometheus:9090 scrape config:            │
                         │   - job: markethawk_backend                │
                         │     target: backend:8000                   │
                         └────────────────────────────────────────────┘
```

### Metrics endpoint

The `/metrics` endpoint is added to the FastAPI app on port 8000. Prometheus scrapes it on the internal Docker network using `http://backend:8000/metrics`. No host-side port mapping is added for metrics — the endpoint is not directly accessible from the host machine except through existing port 8000.

Note: The Celery worker process shares the same Python codebase as the backend. Since `prometheus_client` uses a global registry and the `/metrics` endpoint is on the backend process only, Celery worker metrics are written to that shared registry only from within the **worker process**. The worker does not need its own `/metrics` endpoint — it pushes metrics via the `prometheus_client.push_to_gateway` pattern OR (preferred, simpler) we rely on the fact that both backend and celery-worker import the same metric objects. Because they run in **separate processes**, we need a `multiprocess` approach.

**Correction**: `prometheus_client` in multiprocess mode requires `PROMETHEUS_MULTIPROC_DIR` to be set and shared across all processes. All backend-derived containers (backend, celery-worker) mount a shared tmpfs volume for this directory. The `/metrics` endpoint uses `generate_latest(CollectorRegistry())` with multiprocess collectors.

---

## Implementation Plan

### 1. Python dependencies (`backend/requirements.txt`)

```
prometheus-client==0.21.1
prometheus-fastapi-instrumentator==7.1.0
```

### 2. Metrics registry setup (`backend/app/core/metrics.py`)

New module that defines all custom metrics. This is imported at startup to register metrics with the multiprocess collector. All metric objects are module-level singletons.

```python
from prometheus_client import Counter, Gauge, Histogram

scanner_events_total = Counter(
    "scanner_events_total",
    "Total scanner events emitted",
    ["scanner_type"],
)

scan_duration_seconds = Histogram(
    "scan_duration_seconds",
    "Duration of a scanner run in seconds",
    ["scanner_type"],
    buckets=[0.5, 1, 2, 5, 10, 30, 60, 120, 300],
)

polygon_api_calls_total = Counter(
    "polygon_api_calls_total",
    "Total calls made to the Polygon.io API",
    ["endpoint"],
)

ibkr_connection_status = Gauge(
    "ibkr_connection_status",
    "IBKR connection status (1=connected, 0=disconnected)",
)

celery_tasks_total = Counter(
    "celery_tasks_total",
    "Total Celery tasks executed",
    ["task_name", "status"],  # status: success | failure
)

celery_task_duration_seconds = Histogram(
    "celery_task_duration_seconds",
    "Celery task execution duration",
    ["task_name"],
    buckets=[0.1, 0.5, 1, 5, 10, 30, 60, 300],
)

active_websocket_connections = Gauge(
    "active_websocket_connections",
    "Number of active WebSocket connections",
)

db_pool_size = Gauge("db_pool_size", "SQLAlchemy connection pool size")
db_pool_checked_out = Gauge("db_pool_checked_out", "Connections currently in use")
db_pool_overflow = Gauge("db_pool_overflow", "Overflow connections beyond pool_size")
# TODO(#85): pool_size and max_overflow will be tuned after connection pooling lands
```

### 3. FastAPI instrumentation (`backend/app/main.py`)

```python
from prometheus_fastapi_instrumentator import Instrumentator
from prometheus_client import make_asgi_app, REGISTRY
import os

# In create_app(), after middleware:
if os.environ.get("PROMETHEUS_MULTIPROC_DIR"):
    from prometheus_client.multiprocess import MultiProcessCollector
    from prometheus_client import CollectorRegistry
    registry = CollectorRegistry()
    MultiProcessCollector(registry)
else:
    registry = REGISTRY

Instrumentator().instrument(app).expose(app, endpoint="/metrics")
```

Mount a periodic background task (every 15s) in `lifespan()` to refresh DB pool gauges:

```python
async def _update_pool_metrics():
    while True:
        pool = engine.pool
        db_pool_size.set(pool.size())
        db_pool_checked_out.set(pool.checked_out())
        db_pool_overflow.set(pool.overflow())
        await asyncio.sleep(15)
```

### 4. Celery task instrumentation (`backend/app/tasks/`)

All tasks in `scanning.py`, `sync.py`, `trading.py`, and `quality.py` wrap their body with a context manager:

```python
from app.core.metrics import celery_tasks_total, celery_task_duration_seconds

@celery_app.task(bind=True, name="app.tasks.run_universe_scan")
def run_universe_scan(self, ...):
    task_name = "run_universe_scan"
    with celery_task_duration_seconds.labels(task_name=task_name).time():
        try:
            # ... task body ...
            celery_tasks_total.labels(task_name=task_name, status="success").inc()
        except Exception:
            celery_tasks_total.labels(task_name=task_name, status="failure").inc()
            raise
```

Custom `scanner_events_total` and `scan_duration_seconds` are incremented in `services/scanner.py` at `ScannerService.run_pre_market_scan()` / `run_oversold_bounce_scan()`.

`polygon_api_calls_total` is incremented in `providers/massive.py` at each Polygon API call site.

`ibkr_connection_status` is set in `providers/ibkr.py` and updated in the `live-scanner` container's connection lifecycle.

`active_websocket_connections` is updated in `services/websocket_manager.py` on connect/disconnect events.

### 5. Multiprocess directory

Add a named volume `prometheus_multiproc` and mount it at `/tmp/prometheus_multiproc` in `backend` and `celery-worker` containers. Set env var `PROMETHEUS_MULTIPROC_DIR=/tmp/prometheus_multiproc`.

### 6. Prometheus service (`monitoring/prometheus/`)

**`monitoring/prometheus/prometheus.yml`**:

```yaml
global:
  scrape_interval: 15s
  evaluation_interval: 15s

scrape_configs:
  - job_name: markethawk_backend
    static_configs:
      - targets: ["backend:8000"]
    metrics_path: /metrics
```

**`docker-compose.yml`** addition:

```yaml
prometheus:
  image: prom/prometheus:v2.53.0
  container_name: stockscanner-prometheus
  volumes:
    - ./monitoring/prometheus/prometheus.yml:/etc/prometheus/prometheus.yml:ro
    - prometheus_data:/prometheus
  command:
    - '--config.file=/etc/prometheus/prometheus.yml'
    - '--storage.tsdb.path=/prometheus'
    - '--storage.tsdb.retention.time=15d'
  ports:
    - "9090:9090"
  networks:
    - stockscanner-network
  restart: unless-stopped
```

### 7. Grafana service (`grafana/provisioning/`)

**Directory structure**:

```
grafana/
  provisioning/
    datasources/
      prometheus.yaml        # auto-configure Prometheus datasource
    dashboards/
      dashboards.yaml        # discovery config
      api-overview.json      # HTTP request rate, latency, error rate
      scanner-performance.json   # scan duration, events, failures
      celery-tasks.json      # task throughput by type/status
      infrastructure.json    # DB pool, WebSocket connections, IBKR status
```

**`grafana/provisioning/datasources/prometheus.yaml`**:

```yaml
apiVersion: 1
datasources:
  - name: Prometheus
    type: prometheus
    url: http://prometheus:9090
    isDefault: true
    editable: false
```

**`docker-compose.yml`** addition:

```yaml
grafana:
  image: grafana/grafana:11.1.0
  container_name: stockscanner-grafana
  ports:
    - "3001:3000"
  environment:
    GF_SECURITY_ADMIN_PASSWORD: ${GRAFANA_ADMIN_PASSWORD:-admin}
    GF_USERS_ALLOW_SIGN_UP: "false"
    GF_ALERTING_ENABLED: "true"
  volumes:
    - grafana_data:/var/lib/grafana
    - ./grafana/provisioning:/etc/grafana/provisioning:ro
  depends_on:
    - prometheus
  networks:
    - stockscanner-network
  restart: unless-stopped
```

### 8. Alerting rules

Three alerting rules defined in Grafana:

| Rule | Condition | Severity | Action |
|------|-----------|----------|--------|
| API error rate | `rate(http_requests_total{status=~"5.."}[5m]) / rate(http_requests_total[5m]) > 0.05` | Warning | Webhook → `/api/alerts/infrastructure` |
| Scan failure rate | `rate(celery_tasks_total{task_name=~"run_.*", status="failure"}[15m]) / rate(celery_tasks_total{task_name=~"run_.*"}[15m]) > 0.20` | Critical | Webhook → `/api/alerts/infrastructure` |
| DB pool exhaustion | `db_pool_checked_out / (db_pool_size + db_pool_overflow) > 0.90` | Warning | Webhook → `/api/alerts/infrastructure` |

New FastAPI endpoint `POST /api/alerts/infrastructure` (in `routers/alerts.py`) receives Grafana webhook payloads and routes them through the existing `NotificationDispatcher`. No Alertmanager container is needed.

---

## Approaches Considered

### Option A (Chosen): Direct `prometheus_client` + multiprocess mode

Instrument directly in FastAPI and Celery task code. Use `PROMETHEUS_MULTIPROC_DIR` for cross-process metric aggregation. Single `/metrics` endpoint on the backend.

- **Pro**: No extra containers, consistent with existing code style, easy to add domain metrics
- **Con**: Requires multiprocess dir volume coordination; Celery task instrumentation is manual per-task

### Option B: Celery sidecar exporter (`danihodovic/celery-exporter`)

Separate container reads task state from Redis broker and exposes Celery metrics independently.

- **Pro**: No changes to task code; works across distributed workers
- **Con**: Extra container + Redis polling overhead; can't expose custom domain metrics (scanner events, polygon calls); diverges from existing logging patterns

### Option C: StatsD push

Push metrics to a StatsD aggregator, scrape StatsD exporter.

- **Pro**: Fire-and-forget from task code
- **Con**: Two extra containers (StatsD + exporter); more infrastructure than the value gained

**Option A wins** for this single-developer, single-host deployment: simpler, fewer containers, direct domain metric access.

---

## Alternatives Considered (Alerting)

**Prometheus Alertmanager**: Separate container with its own routing config. Powerful for multi-team setups. Overkill here — the existing `NotificationDispatcher` already handles multi-channel routing (email, push, webhooks).

**Decision**: Grafana built-in alerting + webhook to existing alert infrastructure keeps routing logic centralized and avoids a third monitoring container.

---

## Open Questions (non-blocking)

1. Should `ibkr_connection_status` also be scraped from the `live-scanner` container (which has its own IBKR client)? The live scanner runs as a separate process with no `/metrics` endpoint. Could be added in a follow-up by exposing a simple HTTP server in `live_scanner/main.py`.

2. Should Grafana have anonymous read-only access enabled for easier local development (no login), or keep auth required?

3. Should `GRAFANA_ADMIN_PASSWORD` be added to `.env.example` and `ENV_VARIABLES.md`?

---

## Assumptions

- **[Assumption]** The `prometheus_client` multiprocess mode is the correct approach for sharing metrics between the backend and celery-worker processes that share the same codebase and Docker volume mounts.
- **[Assumption]** Port 3001 for Grafana and 9090 for Prometheus are available — confirmed against current `docker-compose.yml`.
- **[Assumption]** `engine.pool` on the async SQLAlchemy engine (asyncpg driver) exposes `.size()`, `.checked_out()`, and `.overflow()` methods. Should be verified — async engines use `AsyncAdaptedQueuePool`.
- **[Assumption]** The existing `NotificationDispatcher` in `backend/app/services/alert_service.py` can be called from the new `POST /api/alerts/infrastructure` endpoint without changes to its interface.
- **[Assumption]** DB pool metrics from `engine.pool` are sufficient for this issue; deeper pool tuning (pool_size, max_overflow) is deferred to #85.

---

## Files Changed

| File | Change |
|------|--------|
| `backend/requirements.txt` | Add `prometheus-client`, `prometheus-fastapi-instrumentator` |
| `backend/app/core/metrics.py` | New — all custom metric definitions |
| `backend/app/main.py` | Add `Instrumentator` setup, `/metrics` endpoint, pool metrics background task |
| `backend/app/tasks/scanning.py` | Instrument `run_universe_scan`, `run_range_scan`, `run_liquidity_hunt_scheduled` |
| `backend/app/tasks/sync.py` | Instrument key sync tasks |
| `backend/app/tasks/quality.py` | Instrument quality analysis tasks |
| `backend/app/services/scanner.py` | Emit `scanner_events_total`, `scan_duration_seconds` |
| `backend/app/providers/massive.py` | Emit `polygon_api_calls_total` |
| `backend/app/providers/ibkr.py` | Set `ibkr_connection_status` gauge |
| `backend/app/services/websocket_manager.py` | Update `active_websocket_connections` gauge |
| `backend/app/routers/alerts.py` | Add `POST /api/alerts/infrastructure` endpoint |
| `docker-compose.yml` | Add `prometheus`, `grafana` services; add `prometheus_multiproc` volume; add env vars to `backend` + `celery-worker` |
| `monitoring/prometheus/prometheus.yml` | New — Prometheus scrape config |
| `grafana/provisioning/datasources/prometheus.yaml` | New — Grafana datasource |
| `grafana/provisioning/dashboards/dashboards.yaml` | New — dashboard discovery config |
| `grafana/provisioning/dashboards/api-overview.json` | New — HTTP request metrics dashboard |
| `grafana/provisioning/dashboards/scanner-performance.json` | New — scanner metrics dashboard |
| `grafana/provisioning/dashboards/celery-tasks.json` | New — Celery task throughput dashboard |
| `grafana/provisioning/dashboards/infrastructure.json` | New — DB pool + WebSocket + IBKR dashboard |
| `.env.example` | Add `GRAFANA_ADMIN_PASSWORD` |
| `ENV_VARIABLES.md` | Document new env var |
| `CLAUDE.md` | Add Prometheus (9090) and Grafana (3001) to service port table |
