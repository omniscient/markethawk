# Implementation Plan: Prometheus Metrics + Grafana Dashboards (Issue #95)

**Date**: 2026-05-28  
**Goal**: Add full application metrics layer — FastAPI HTTP instrumentation, custom domain counters/histograms, Celery task metrics, Prometheus scrape service, and Grafana dashboards with infrastructure alerting.  
**Spec**: `Docs/superpowers/specs/2026-05-27-prometheus-metrics-grafana-design.md`

---

## Architecture

```
Browser → grafana:3001 → prometheus:9090 → backend:8000/metrics
                                           (aggregates backend + celery-worker via shared PROMETHEUS_MULTIPROC_DIR tmpfs volume)
```

- `prometheus-client` multiprocess mode shares metrics across backend and celery-worker processes via a tmpfs named volume mounted at `/tmp/prometheus_multiproc`
- `prometheus-fastapi-instrumentator` instruments HTTP automatically; domain metrics are emitted from service/task code
- Grafana dashboards and alerting rules are provisioned as files in `grafana/provisioning/`
- Grafana alert webhook fires to `POST /api/alerts/infrastructure` → `NotificationDispatcher`

---

## Tech Stack

| Component | Library/Version |
|-----------|----------------|
| Metrics client | `prometheus-client==0.21.1` |
| FastAPI auto-instrumentation | `prometheus-fastapi-instrumentator==7.1.0` |
| Prometheus | `prom/prometheus:v2.53.0` |
| Grafana | `grafana/grafana:11.1.0` |

---

## File Structure

| File | Action |
|------|--------|
| `backend/requirements.txt` | Add 2 dependencies |
| `backend/app/core/metrics.py` | New — all metric definitions |
| `backend/app/main.py` | Add Instrumentator, /metrics route, pool metrics task |
| `backend/app/tasks/scanning.py` | Instrument 4 Celery tasks |
| `backend/app/tasks/sync.py` | Instrument key sync tasks |
| `backend/app/tasks/quality.py` | Instrument quality task |
| `backend/app/tasks/trading.py` | Instrument 3 trading tasks |
| `backend/app/services/scanner.py` | Emit scanner_events_total, scan_duration_seconds |
| `backend/app/services/liquidity_hunt.py` | Emit scanner_events_total, scan_duration_seconds |
| `backend/app/providers/massive.py` | Emit polygon_api_calls_total |
| `backend/app/providers/ibkr.py` | Set ibkr_connection_status gauge |
| `backend/app/routers/live_data.py` | Track active_websocket_connections (3 endpoints) |
| `backend/app/routers/alerts.py` | Add POST /api/alerts/infrastructure |
| `backend/tests/core/__init__.py` | New — package init |
| `backend/tests/core/test_metrics_module.py` | New — metrics registry unit tests |
| `backend/tests/api/test_metrics.py` | New — /metrics endpoint tests |
| `backend/tests/api/test_alerts_infrastructure.py` | New — infrastructure webhook tests |
| `docker-compose.yml` | Add prometheus + grafana services, prometheus_multiproc tmpfs volume, env vars on backend + celery-worker only |
| `monitoring/prometheus/prometheus.yml` | New — Prometheus scrape config |
| `grafana/provisioning/datasources/prometheus.yaml` | New — Grafana datasource |
| `grafana/provisioning/dashboards/dashboards.yaml` | New — dashboard discovery |
| `grafana/provisioning/dashboards/api-overview.json` | New — HTTP metrics dashboard |
| `grafana/provisioning/dashboards/scanner-performance.json` | New — scanner metrics dashboard |
| `grafana/provisioning/dashboards/celery-tasks.json` | New — Celery throughput dashboard |
| `grafana/provisioning/dashboards/infrastructure.json` | New — DB pool + WS + IBKR dashboard |
| `grafana/provisioning/alerting/contact-points.yaml` | New — webhook contact point |
| `grafana/provisioning/alerting/notification-policies.yaml` | New — default routing policy |
| `grafana/provisioning/alerting/rules.yaml` | New — 3 threshold alert rules |
| `.env.example` | Add GRAFANA_ADMIN_PASSWORD |
| `ENV_VARIABLES.md` | Document new env var |
| `CLAUDE.md` | Add Prometheus + Grafana to service port table |

---

## Tasks

---

### Task 1: Add Python dependencies

**Files**: `backend/requirements.txt`, `backend/tests/core/__init__.py`, `backend/tests/core/test_metrics_module.py`

#### TDD Steps

**Write failing test** — first create the package init:
```bash
mkdir -p backend/tests/core
touch backend/tests/core/__init__.py
```

Create `backend/tests/core/test_metrics_module.py`:
```python
"""Unit tests for the metrics registry module."""


def test_prometheus_client_importable():
    import prometheus_client
    assert prometheus_client is not None


def test_instrumentator_importable():
    from prometheus_fastapi_instrumentator import Instrumentator
    assert Instrumentator is not None
```

**Verify test fails**:
```bash
docker-compose exec backend python -m pytest tests/core/test_metrics_module.py -v 2>&1 | tail -20
# Expected: ModuleNotFoundError: No module named 'prometheus_client'
```

**Implement** — add to `backend/requirements.txt` after the `# Development` block:
```
# Metrics
prometheus-client==0.21.1
prometheus-fastapi-instrumentator==7.1.0
```

**Rebuild and verify test passes**:
```bash
docker-compose build backend
docker-compose up -d backend
docker-compose exec backend python -m pytest tests/core/test_metrics_module.py -v 2>&1 | tail -10
# Expected: 2 passed
```

**Commit**:
```bash
git add backend/requirements.txt backend/tests/core/__init__.py backend/tests/core/test_metrics_module.py
git commit -m "feat(metrics): add prometheus-client and prometheus-fastapi-instrumentator dependencies"
```

---

### Task 2: Create metrics registry module

**Files**: `backend/app/core/metrics.py`, `backend/tests/core/test_metrics_module.py`

#### TDD Steps

**Write failing tests** — extend `backend/tests/core/test_metrics_module.py`:
```python
from prometheus_client import REGISTRY


def test_all_metric_names_registered():
    from app.core.metrics import (
        scanner_events_total,
        scan_duration_seconds,
        polygon_api_calls_total,
        ibkr_connection_status,
        celery_tasks_total,
        celery_task_duration_seconds,
        active_websocket_connections,
        db_pool_size,
        db_pool_checked_out,
        db_pool_overflow,
    )
    assert scanner_events_total._name == "scanner_events_total"
    assert scan_duration_seconds._name == "scan_duration_seconds"
    assert polygon_api_calls_total._name == "polygon_api_calls_total"
    assert ibkr_connection_status._name == "ibkr_connection_status"
    assert celery_tasks_total._name == "celery_tasks_total"
    assert celery_task_duration_seconds._name == "celery_task_duration_seconds"
    assert active_websocket_connections._name == "active_websocket_connections"
    assert db_pool_size._name == "db_pool_size"
    assert db_pool_checked_out._name == "db_pool_checked_out"
    assert db_pool_overflow._name == "db_pool_overflow"


def test_scanner_events_counter_incrementable():
    from app.core.metrics import scanner_events_total
    # Use REGISTRY.get_sample_value (public API, stable across multiprocess modes)
    label_vals = {"scanner_type": "pre_market_volume_spike"}
    before = REGISTRY.get_sample_value("scanner_events_total_total", label_vals) or 0.0
    scanner_events_total.labels(scanner_type="pre_market_volume_spike").inc()
    after = REGISTRY.get_sample_value("scanner_events_total_total", label_vals) or 0.0
    assert after == before + 1


def test_ibkr_connection_status_settable():
    from app.core.metrics import ibkr_connection_status
    ibkr_connection_status.set(1)
    assert REGISTRY.get_sample_value("ibkr_connection_status") == 1.0
    ibkr_connection_status.set(0)
    assert REGISTRY.get_sample_value("ibkr_connection_status") == 0.0
```

**Verify tests fail**:
```bash
docker-compose exec backend python -m pytest tests/core/test_metrics_module.py -v 2>&1 | tail -15
# Expected: ImportError: cannot import name 'scanner_events_total' from 'app.core.metrics'
```

**Implement** — create `backend/app/core/metrics.py`:
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
    ["task_name", "status"],
)

celery_task_duration_seconds = Histogram(
    "celery_task_duration_seconds",
    "Celery task execution duration in seconds",
    ["task_name"],
    buckets=[0.1, 0.5, 1, 5, 10, 30, 60, 300],
)

active_websocket_connections = Gauge(
    "active_websocket_connections",
    "Number of active WebSocket connections from frontend clients",
)

db_pool_size = Gauge("db_pool_size", "SQLAlchemy connection pool configured size")
db_pool_checked_out = Gauge("db_pool_checked_out", "Connections currently checked out from pool")
db_pool_overflow = Gauge("db_pool_overflow", "Overflow connections beyond pool_size")
```

**Verify tests pass**:
```bash
docker-compose exec backend python -m pytest tests/core/test_metrics_module.py -v 2>&1 | tail -15
# Expected: 5 passed
```

**Commit**:
```bash
git add backend/app/core/metrics.py backend/tests/core/test_metrics_module.py
git commit -m "feat(metrics): add metrics registry module with all custom metric definitions"
```

---

### Task 3: FastAPI instrumentation and /metrics endpoint

**Files**: `backend/app/main.py`, `backend/tests/api/test_metrics.py`

#### TDD Steps

**Write failing test** — create `backend/tests/api/test_metrics.py`:
```python
"""Integration tests for the /metrics endpoint."""
from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)


def test_metrics_endpoint_returns_200():
    response = client.get("/metrics")
    assert response.status_code == 200


def test_metrics_endpoint_returns_prometheus_format():
    response = client.get("/metrics")
    assert "text/plain" in response.headers["content-type"]
    assert b"# TYPE" in response.content


def test_metrics_endpoint_not_in_openapi_schema():
    response = client.get("/openapi.json")
    assert "/metrics" not in response.json().get("paths", {})
```

**Verify test fails**:
```bash
docker-compose exec backend python -m pytest tests/api/test_metrics.py -v 2>&1 | tail -15
# Expected: 404 on GET /metrics
```

**Implement** — edit `backend/app/main.py`.

Add these imports at the top of the file (after the existing imports):
```python
import asyncio
import os
from fastapi import Response
from prometheus_fastapi_instrumentator import Instrumentator
from prometheus_client import generate_latest, CollectorRegistry, REGISTRY
```

In `lifespan()`, after `websocket_manager.start()` and before `yield`:
```python
    from app.core.metrics import db_pool_size, db_pool_checked_out, db_pool_overflow

    async def _update_pool_metrics():
        while True:
            try:
                pool = engine.pool
                db_pool_size.set(pool.size())
                db_pool_checked_out.set(pool.checkedout())
                db_pool_overflow.set(pool.overflow())
            except Exception:
                pass
            await asyncio.sleep(15)

    _pool_task = asyncio.create_task(_update_pool_metrics())
    logging.info("DB pool metrics background task started")
```

In `lifespan()`, in the shutdown section after `engine.dispose()`:
```python
    _pool_task.cancel()
```

In `create_app()`, after all `app.include_router(...)` calls and before the `importlib.import_module(...)` block:
```python
    # Instrument all routes with Prometheus HTTP metrics (no .expose() — we add our own /metrics)
    Instrumentator().instrument(app)

    @app.get("/metrics", include_in_schema=False)
    def prometheus_metrics():
        if os.environ.get("PROMETHEUS_MULTIPROC_DIR"):
            from prometheus_client.multiprocess import MultiProcessCollector
            reg = CollectorRegistry()
            MultiProcessCollector(reg)
        else:
            reg = REGISTRY
        return Response(
            content=generate_latest(reg),
            media_type="text/plain; version=0.0.4; charset=utf-8",
        )
```

**Verify tests pass**:
```bash
docker-compose restart backend
docker-compose exec backend python -m pytest tests/api/test_metrics.py -v 2>&1 | tail -15
# Expected: 3 passed
```

**Validate live**:
```bash
curl -s http://localhost:8000/metrics | head -30
# Expected: # HELP and # TYPE lines
```

**Commit**:
```bash
git add backend/app/main.py backend/tests/api/test_metrics.py
git commit -m "feat(metrics): add FastAPI Prometheus instrumentation and /metrics endpoint with pool metrics background task"
```

---

### Task 4: Docker Compose — Prometheus + Grafana services, tmpfs multiprocess volume

**Files**: `docker-compose.yml`, `monitoring/prometheus/prometheus.yml`

**Design note**: `PROMETHEUS_MULTIPROC_DIR` is set **only** on `backend` and `celery-worker`. The `live-scanner`, `celery-beat`, and `forecast-worker` containers are intentionally excluded because:
- They have no instrumented metrics in this feature
- Setting the env var without mounting the volume would cause crashes
- Without the env var, `prometheus_client` operates normally in single-process mode without writing to any directory

The volume uses a local tmpfs driver so stale metric files from previous container runs are not accumulated on disk.

#### TDD Steps

No unit tests. Validation is functional.

**Implement** — edit `docker-compose.yml`:

1. In the `backend` service `environment` block, add:
```yaml
      PROMETHEUS_MULTIPROC_DIR: /tmp/prometheus_multiproc
```

2. In the `backend` service `volumes` block, add:
```yaml
      - prometheus_multiproc:/tmp/prometheus_multiproc
```

3. In the `celery-worker` service `environment` block, add:
```yaml
      PROMETHEUS_MULTIPROC_DIR: /tmp/prometheus_multiproc
```

4. In the `celery-worker` service `volumes` block, add:
```yaml
      - prometheus_multiproc:/tmp/prometheus_multiproc
```

5. After the `seq` service block, add:
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

  grafana:
    image: grafana/grafana:11.1.0
    container_name: stockscanner-grafana
    ports:
      - "3001:3000"
    environment:
      GF_SECURITY_ADMIN_PASSWORD: ${GRAFANA_ADMIN_PASSWORD:-admin}
      GF_USERS_ALLOW_SIGN_UP: "false"
    volumes:
      - grafana_data:/var/lib/grafana
      - ./grafana/provisioning:/etc/grafana/provisioning:ro
    depends_on:
      - prometheus
    networks:
      - stockscanner-network
    restart: unless-stopped
```

6. In the `volumes:` section, add:
```yaml
  prometheus_multiproc:
    driver: local
    driver_opts:
      type: tmpfs
      device: tmpfs
      o: size=256m
  prometheus_data:
  grafana_data:
```

**Create** directory and file `monitoring/prometheus/prometheus.yml`:
```bash
mkdir -p monitoring/prometheus
```
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

**Apply and validate**:
```bash
docker-compose up -d --force-recreate backend celery-worker prometheus grafana
docker-compose ps | grep -E "prometheus|grafana|backend|celery"
# Expected: all Up
curl -s http://localhost:9090/-/ready
# Expected: Prometheus Server is Ready.
curl -s "http://localhost:9090/api/v1/targets" | python -m json.tool | grep "markethawk_backend"
# Expected: "job": "markethawk_backend"
docker-compose exec backend ls /tmp/prometheus_multiproc
# Expected: directory exists
```

**Commit**:
```bash
git add docker-compose.yml monitoring/prometheus/prometheus.yml
git commit -m "feat(metrics): add Prometheus and Grafana services with tmpfs multiprocess metrics volume"
```

---

### Task 5: Celery task instrumentation — scanning.py

**Files**: `backend/app/tasks/scanning.py`

#### TDD Steps

**Write test** — create `backend/tests/tasks/test_metrics_instrumentation.py`:
```python
"""Verify that Celery tasks can be called with metrics instrumentation present."""
from unittest.mock import patch, MagicMock


def test_scanning_imports_metrics_without_error():
    """Ensure scanning.py imports metrics module without raising."""
    import app.tasks.scanning  # noqa: F401
    from app.core.metrics import celery_tasks_total, celery_task_duration_seconds
    assert celery_tasks_total is not None
    assert celery_task_duration_seconds is not None
```

**Verify test passes** (import-level smoke test — no failure expected, confirms no import-time crash):
```bash
docker-compose exec backend python -m pytest tests/tasks/test_metrics_instrumentation.py -v 2>&1 | tail -10
```

**Implement** — edit `backend/app/tasks/scanning.py`.

Add import at the top (after existing imports):
```python
import time as _time
from app.core.metrics import celery_tasks_total, celery_task_duration_seconds
```

**Wrap `evaluate_scanner_alerts`** — replace the existing `db: Session = SessionLocal()` and full `try/except/finally` body with:
```python
    _task_name = "evaluate_scanner_alerts"
    _start = _time.monotonic()
    db: Session = SessionLocal()
    try:
        event = db.query(ScannerEvent).filter(ScannerEvent.id == scanner_event_id).first()
        if not event:
            logger.warning(f"evaluate_scanner_alerts: ScannerEvent id={scanner_event_id} not found.")
            return

        matching_rules = AlertRuleService.get_matching_rules(event, db)
        if not matching_rules:
            return

        logger.info(
            f"🔔 {len(matching_rules)} alert rule(s) matched "
            f"event={scanner_event_id} ticker={event.ticker} type={event.scanner_type}"
        )

        for rule in matching_rules:
            try:
                NotificationDispatcher.dispatch(rule, event, db)
            except Exception as exc:
                logger.error(f"❌ Dispatch failed for rule {rule.id}: {exc}")

            if rule.auto_trade and rule.trading_strategy_id:
                from app.tasks.trading import execute_auto_trade
                execute_auto_trade.delay(
                    rule_id=rule.id,
                    scanner_event_id=scanner_event_id,
                )
                logger.info(
                    f"🤖 Auto-trade queued for rule={rule.id} "
                    f"strategy={rule.trading_strategy_id} ticker={event.ticker}"
                )

        celery_tasks_total.labels(task_name=_task_name, status="success").inc()
    except Exception as e:
        celery_tasks_total.labels(task_name=_task_name, status="failure").inc()
        logger.error(f"❌ evaluate_scanner_alerts failed for event {scanner_event_id}: {e}")
        db.rollback()
        raise self.retry(exc=e, countdown=30)
    finally:
        celery_task_duration_seconds.labels(task_name=_task_name).observe(
            _time.monotonic() - _start
        )
        db.close()
```

**Wrap `run_range_scan`** — add at the very start of the function body (before `task_id = run_range_scan.request.id`):
```python
    _task_name = "run_range_scan"
    _start = _time.monotonic()
```

Replace the existing `except Exception as e:` handler block with:
```python
    except Exception as e:
        celery_tasks_total.labels(task_name=_task_name, status="failure").inc()
        logger.error(f"run_range_scan {task_id} failed: {e}")
        r.publish(channel, json.dumps({
            "status": "failed",
            "error": str(e),
        }))
```

Replace the existing `finally:` block with:
```python
    finally:
        celery_task_duration_seconds.labels(task_name=_task_name).observe(
            _time.monotonic() - _start
        )
        r.delete(f"scan:{ticker}:range")
        db.close()
```

Add `celery_tasks_total.labels(task_name=_task_name, status="success").inc()` immediately before the `finally:` block (after `logger.info(f"run_range_scan {task_id}: completed, ...")`).

**Wrap `run_liquidity_hunt_scheduled`** — add at the start of the function body (before `db: Session = SessionLocal()`):
```python
    _task_name = "run_liquidity_hunt_scheduled"
    _start = _time.monotonic()
```

Add `celery_tasks_total.labels(task_name=_task_name, status="success").inc()` after the inner `for cfg in configs:` loop completes (before `except`).

Replace the existing `except Exception as exc:` handler with:
```python
    except Exception as exc:
        celery_tasks_total.labels(task_name=_task_name, status="failure").inc()
        logger.exception("run_liquidity_hunt_scheduled failed: %s", exc)
        raise self.retry(exc=exc)
```

Replace the existing `finally:` block with:
```python
    finally:
        celery_task_duration_seconds.labels(task_name=_task_name).observe(
            _time.monotonic() - _start
        )
        db.close()
```

**Wrap `run_universe_scan`** — add at the very start of the function body (before `task_id = self.request.id`):
```python
    _task_name = "run_universe_scan"
    _perf_start = _time.monotonic()
```

Add `celery_tasks_total.labels(task_name=_task_name, status="success").inc()` immediately after the `logger.info("run_universe_scan %s completed: ...")` call in the normal completion path.

In the outer `except Exception as exc:` handler, add after `_publish({"type": "failed", "error": str(exc)})`:
```python
        celery_tasks_total.labels(task_name=_task_name, status="failure").inc()
```

In the `finally:` block, add before `db.close()`:
```python
        celery_task_duration_seconds.labels(task_name=_task_name).observe(
            _time.monotonic() - _perf_start
        )
```

**Verify no regressions**:
```bash
docker-compose exec backend python -m pytest tests/tasks/ tests/api/test_scanner.py -v 2>&1 | tail -20
```

**Commit**:
```bash
git add backend/app/tasks/scanning.py backend/tests/tasks/test_metrics_instrumentation.py
git commit -m "feat(metrics): instrument Celery scanning tasks with celery_tasks_total and celery_task_duration_seconds"
```

---

### Task 6: Celery task instrumentation — sync.py and quality.py

**Files**: `backend/app/tasks/sync.py`, `backend/app/tasks/quality.py`

#### TDD Steps

**Implement `sync.py`** — add import after existing imports:
```python
import time as _time
from app.core.metrics import celery_tasks_total, celery_task_duration_seconds
```

In `sync_tickers_batch`, add at the start of the function body (before `db: Session = SessionLocal()`):
```python
    _task_name = "sync_tickers_batch"
    _start = _time.monotonic()
```

In the success path (after `logger.info("✅ Ticker sync page ...")` or equivalent success log), add:
```python
            celery_tasks_total.labels(task_name=_task_name, status="success").inc()
```

In the `except Exception as e:` handler (the terminal one after all retries), add before `raise`:
```python
        celery_tasks_total.labels(task_name=_task_name, status="failure").inc()
```

In the `finally:` block (if one exists), or add a `finally:` block after the outermost try/except, add:
```python
        celery_task_duration_seconds.labels(task_name=_task_name).observe(
            _time.monotonic() - _start
        )
        db.close()
```

**Implement `quality.py`** — add import after existing imports:
```python
import time as _time
from app.core.metrics import celery_tasks_total, celery_task_duration_seconds
```

In `analyze_universe_quality`, add at the start (before `db: Session = SessionLocal()`):
```python
    _task_name = "analyze_universe_quality"
    _start = _time.monotonic()
```

After `logger.info(f"✅ Quality analysis complete ...")`:
```python
        celery_tasks_total.labels(task_name=_task_name, status="success").inc()
```

In the existing `except Exception as e:` handler, add:
```python
        celery_tasks_total.labels(task_name=_task_name, status="failure").inc()
```

In the existing `finally:` block, add before `db.close()`:
```python
        celery_task_duration_seconds.labels(task_name=_task_name).observe(
            _time.monotonic() - _start
        )
```

**Verify no regressions**:
```bash
docker-compose exec backend python -m pytest tests/ -v --ignore=tests/live_scanner -x 2>&1 | tail -20
```

**Commit**:
```bash
git add backend/app/tasks/sync.py backend/app/tasks/quality.py
git commit -m "feat(metrics): instrument sync and quality Celery tasks"
```

---

### Task 7: Celery task instrumentation — trading.py

**Files**: `backend/app/tasks/trading.py`

The spec requires all tasks in `scanning.py`, `sync.py`, `trading.py`, and `quality.py` to be instrumented. This task covers `execute_auto_trade`, `submit_approved_order`, and `poll_auto_trade_fills`.

#### TDD Steps

**Implement** — add import after existing imports:
```python
import time as _time
from app.core.metrics import celery_tasks_total, celery_task_duration_seconds
```

**Wrap `execute_auto_trade`** — add at the start of the function body (before `db: Session = SessionLocal()`):
```python
    _task_name = "execute_auto_trade"
    _start = _time.monotonic()
```

After `logger.info(f"✅ execute_auto_trade: order id=...")` (success path), add:
```python
        celery_tasks_total.labels(task_name=_task_name, status="success").inc()
```

Replace the existing `except Exception as exc:` handler with:
```python
    except Exception as exc:
        celery_tasks_total.labels(task_name=_task_name, status="failure").inc()
        logger.error(f"❌ execute_auto_trade failed rule={rule_id} event={scanner_event_id}: {exc}")
        db.rollback()
        raise self.retry(exc=exc, countdown=15)
```

Replace the existing `finally:` block with:
```python
    finally:
        celery_task_duration_seconds.labels(task_name=_task_name).observe(
            _time.monotonic() - _start
        )
        db.close()
```

**Wrap `submit_approved_order`** — add at the start (before `db: Session = SessionLocal()`):
```python
    _task_name = "submit_approved_order"
    _start = _time.monotonic()
```

After `logger.info(f"✅ submit_approved_order: order {order_id} submitted, ...")`:
```python
        celery_tasks_total.labels(task_name=_task_name, status="success").inc()
```

Replace the `except Exception as exc:` handler with:
```python
    except Exception as exc:
        celery_tasks_total.labels(task_name=_task_name, status="failure").inc()
        logger.error(f"❌ submit_approved_order failed order={order_id}: {exc}")
        db.rollback()
        raise self.retry(exc=exc, countdown=15)
```

Replace the `finally:` block with:
```python
    finally:
        celery_task_duration_seconds.labels(task_name=_task_name).observe(
            _time.monotonic() - _start
        )
        db.close()
```

**Wrap `poll_auto_trade_fills`** — add at the start (before `db: Session = SessionLocal()`):
```python
    _task_name = "poll_auto_trade_fills"
    _start = _time.monotonic()
```

Add `celery_tasks_total.labels(task_name=_task_name, status="success").inc()` immediately before the existing `finally:` block.

Replace the `except Exception as exc:` handler with:
```python
    except Exception as exc:
        celery_tasks_total.labels(task_name=_task_name, status="failure").inc()
        logger.error(f"❌ poll_auto_trade_fills error: {exc}")
        db.rollback()
```

Replace the `finally:` block with:
```python
    finally:
        celery_task_duration_seconds.labels(task_name=_task_name).observe(
            _time.monotonic() - _start
        )
        db.close()
```

**Verify no regressions**:
```bash
docker-compose exec backend python -m pytest tests/tasks/ -v 2>&1 | tail -15
```

**Commit**:
```bash
git add backend/app/tasks/trading.py
git commit -m "feat(metrics): instrument trading Celery tasks (execute_auto_trade, submit_approved_order, poll_auto_trade_fills)"
```

---

### Task 8: Scanner service instrumentation

**Files**: `backend/app/services/scanner.py`, `backend/app/services/liquidity_hunt.py`

**Goal**: Emit `scanner_events_total` and `scan_duration_seconds` when scanner runs complete.

#### TDD Steps

**Implement** — edit `backend/app/services/scanner.py`.

Add imports after existing imports (before `_ET = ...`):
```python
import time as _time
from app.core.metrics import scanner_events_total, scan_duration_seconds
```

Find `run_pre_market_scan_for_date` (the static method that produces events for a ticker+date). At the very start of its body, add:
```python
        _scan_start = _time.monotonic()
        _scanner_type = "pre_market_volume_spike"
```

Just before the `return results` statement, add:
```python
        scan_duration_seconds.labels(scanner_type=_scanner_type).observe(
            _time.monotonic() - _scan_start
        )
        for _ in results:
            scanner_events_total.labels(scanner_type=_scanner_type).inc()
```

Apply the same pattern to `run_oversold_bounce_scan_for_date` with `_scanner_type = "oversold_bounce"`.

**Edit `backend/app/services/liquidity_hunt.py`** — add imports:
```python
import time as _time
from app.core.metrics import scanner_events_total, scan_duration_seconds
```

Find the function that produces liquidity hunt events for a single ticker+date (e.g. `run_liquidity_hunt_scan_for_date`). At the start of its body:
```python
    _scan_start = _time.monotonic()
    _scanner_type = "liquidity_hunt"
```

Just before `return results`:
```python
    scan_duration_seconds.labels(scanner_type=_scanner_type).observe(
        _time.monotonic() - _scan_start
    )
    for _ in results:
        scanner_events_total.labels(scanner_type=_scanner_type).inc()
```

**Verify tests**:
```bash
docker-compose exec backend python -m pytest tests/services/test_scanner_service_methods.py tests/services/test_liquidity_hunt.py -v 2>&1 | tail -20
```

**Commit**:
```bash
git add backend/app/services/scanner.py backend/app/services/liquidity_hunt.py
git commit -m "feat(metrics): emit scanner_events_total and scan_duration_seconds from scanner service"
```

---

### Task 9: Polygon provider instrumentation

**Files**: `backend/app/providers/massive.py`

**Goal**: Emit `polygon_api_calls_total` on every Polygon HTTP call.

#### TDD Steps

**Implement** — edit `backend/app/providers/massive.py`.

Add import after existing imports:
```python
from app.core.metrics import polygon_api_calls_total
```

In `get_bars()`, add at the start of the method body (before any conditional):
```python
        polygon_api_calls_total.labels(endpoint="aggs").inc()
```

In `get_snapshots()`, add:
```python
        polygon_api_calls_total.labels(endpoint="snapshots").inc()
```

In `get_ticker_details()`, add:
```python
        polygon_api_calls_total.labels(endpoint="ticker_details").inc()
```

For any other methods in `MassiveDataProvider` that call `self._client` (search for `self._client.`), add the corresponding increment with a descriptive endpoint label (e.g. `"tickers"`, `"news"`, `"reference_tickers"`).

**Verify** no regression in provider tests:
```bash
docker-compose exec backend python -m pytest tests/providers/ -v 2>&1 | tail -20
```

**Commit**:
```bash
git add backend/app/providers/massive.py
git commit -m "feat(metrics): instrument Polygon API calls with polygon_api_calls_total counter"
```

---

### Task 10: IBKR provider instrumentation

**Files**: `backend/app/providers/ibkr.py`

**Goal**: Set `ibkr_connection_status` gauge to 1 when connected, 0 when disconnected.

#### TDD Steps

**Implement** — edit `backend/app/providers/ibkr.py`.

Add import after existing imports (after the `IB_INSYNC_AVAILABLE` block):
```python
from app.core.metrics import ibkr_connection_status
```

In `connect()`, after the `self._connected = True` assignment (successful connection, ~line 412):
```python
                ibkr_connection_status.set(1)
                logger.info("IBKRDataProvider: Connected to TWS/Gateway.")
```

In `connect()`, after the `self._connected = False` assignment in the failure branch (~line 424):
```python
                ibkr_connection_status.set(0)
```

In `disconnect()`, after `self._connected = False` (~line 446):
```python
        ibkr_connection_status.set(0)
```

In `_get_connection()`, after `success = await self.connect()` where `success` is False:
```python
        if not success:
            ibkr_connection_status.set(0)
            return None
```

**Verify** no regression in IBKR provider tests:
```bash
docker-compose exec backend python -m pytest tests/providers/test_ibkr_provider.py -v 2>&1 | tail -20
```

**Commit**:
```bash
git add backend/app/providers/ibkr.py
git commit -m "feat(metrics): set ibkr_connection_status gauge on IBKR connect/disconnect lifecycle"
```

---

### Task 11: WebSocket connection tracking

**Files**: `backend/app/routers/live_data.py`

**Goal**: Increment `active_websocket_connections` gauge when a frontend client connects to any of the three WebSocket endpoints; decrement on disconnect.

#### TDD Steps

**Implement** — edit `backend/app/routers/live_data.py`.

Add import at the top (after existing imports):
```python
from app.core.metrics import active_websocket_connections
```

In `stock_live_websocket()` — after `await websocket.accept()`:
```python
    active_websocket_connections.inc()
```
In its `finally:` block (after `await redis_client.close()`):
```python
        active_websocket_connections.dec()
```

In `watchlist_live_websocket()` — after `await websocket.accept()`:
```python
    active_websocket_connections.inc()
```
In its `finally:` block (after `await redis_client.close()`):
```python
        active_websocket_connections.dec()
```

In `scan_task_websocket()` — after `await websocket.accept()`:
```python
    active_websocket_connections.inc()
```
In its `finally:` block (after the `pubsub.unsubscribe` + `redis_client.close()` calls):
```python
        active_websocket_connections.dec()
```

**Verify** live_data tests still pass:
```bash
docker-compose exec backend python -m pytest tests/api/test_live_data.py -v 2>&1 | tail -15
```

**Commit**:
```bash
git add backend/app/routers/live_data.py
git commit -m "feat(metrics): track active WebSocket connections across all 3 WS endpoints"
```

---

### Task 12: Infrastructure alert webhook endpoint

**Files**: `backend/app/routers/alerts.py`, `backend/tests/api/test_alerts_infrastructure.py`

**Goal**: Add `POST /api/alerts/infrastructure` that accepts Grafana webhook payloads and dispatches via `NotificationDispatcher`.

**Design note**: The synthetic `ScannerEvent` created here is never persisted to the database. Its `id` is set to `None` so that `AlertDeliveryLog.scanner_event_id` (which is nullable) stores NULL — valid, and avoids any FK constraint issues. `AlertDeliveryLog.scanner_event_id` is declared `nullable=True` in the model.

#### TDD Steps

**Write failing test** — create `backend/tests/api/test_alerts_infrastructure.py`:
```python
"""Tests for the Grafana infrastructure alert webhook endpoint."""
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session
from app.main import app

client = TestClient(app)


GRAFANA_WEBHOOK_PAYLOAD = {
    "version": "1",
    "groupKey": "{}:{alertname=\"HighAPIErrorRate\"}",
    "status": "firing",
    "receiver": "markethawk-backend",
    "groupLabels": {"alertname": "HighAPIErrorRate"},
    "commonLabels": {"alertname": "HighAPIErrorRate", "severity": "warning"},
    "commonAnnotations": {"summary": "API error rate exceeded 5%"},
    "externalURL": "http://grafana:3000",
    "alerts": [
        {
            "status": "firing",
            "labels": {"alertname": "HighAPIErrorRate", "severity": "warning"},
            "annotations": {"summary": "API error rate exceeded 5%"},
            "startsAt": "2026-05-28T10:00:00Z",
            "endsAt": "0001-01-01T00:00:00Z",
            "generatorURL": "http://grafana:3000/alerting/abc123/edit",
            "fingerprint": "abc123def456",
            "silenceURL": "",
            "dashboardURL": "",
            "panelURL": "",
            "values": {"B": 0.08},
            "valueString": "[ var='B' labels={} value=0.08 ]",
        }
    ],
    "title": "[FIRING:1] HighAPIErrorRate",
    "message": "API error rate exceeded 5%",
    "truncatedAlerts": 0,
}


def test_infrastructure_alert_accepts_grafana_payload(db: Session):
    response = client.post("/api/alerts/infrastructure", json=GRAFANA_WEBHOOK_PAYLOAD)
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "received"
    assert "alert_count" in data


def test_infrastructure_alert_returns_200_on_resolved(db: Session):
    payload = {**GRAFANA_WEBHOOK_PAYLOAD, "status": "resolved"}
    response = client.post("/api/alerts/infrastructure", json=payload)
    assert response.status_code == 200
    assert response.json()["status"] == "received"


def test_infrastructure_alert_rejects_missing_status(db: Session):
    response = client.post("/api/alerts/infrastructure", json={"alerts": []})
    assert response.status_code == 422
```

**Verify tests fail** (404 — endpoint doesn't exist yet):
```bash
docker-compose exec backend python -m pytest tests/api/test_alerts_infrastructure.py -v 2>&1 | tail -15
```

**Implement** — edit `backend/app/routers/alerts.py`.

Add one import at the top (only `BaseModel` is new; `Optional`, `List`, `Dict`, `Any` are already imported):
```python
from pydantic import BaseModel
```

Add the following before the final `@router.delete(...)` block:
```python
# ──────────────────────────────────────────────────────────────────────────────
# Infrastructure Alerts — Grafana webhook receiver
# ──────────────────────────────────────────────────────────────────────────────

class _GrafanaAlert(BaseModel):
    status: str
    labels: Dict[str, Any] = {}
    annotations: Dict[str, Any] = {}
    startsAt: Optional[str] = None
    endsAt: Optional[str] = None
    generatorURL: Optional[str] = None
    fingerprint: Optional[str] = None
    silenceURL: Optional[str] = None
    dashboardURL: Optional[str] = None
    panelURL: Optional[str] = None
    values: Optional[Dict[str, Any]] = None
    valueString: Optional[str] = None


class _GrafanaWebhookPayload(BaseModel):
    version: Optional[str] = None
    groupKey: Optional[str] = None
    status: str
    receiver: Optional[str] = None
    groupLabels: Dict[str, Any] = {}
    commonLabels: Dict[str, Any] = {}
    commonAnnotations: Dict[str, Any] = {}
    externalURL: Optional[str] = None
    alerts: List[_GrafanaAlert] = []
    title: Optional[str] = None
    message: Optional[str] = None
    truncatedAlerts: Optional[int] = 0


@router.post("/infrastructure")
def receive_infrastructure_alert(
    payload: _GrafanaWebhookPayload,
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    """
    Grafana webhook receiver for infrastructure threshold alerts.
    Dispatches firing alerts through the existing NotificationDispatcher.
    The synthetic ScannerEvent is not persisted (id=None); AlertDeliveryLog.scanner_event_id
    is nullable so this does not cause a FK constraint violation.
    """
    firing_alerts = [a for a in payload.alerts if a.status == "firing"]

    if firing_alerts and payload.status == "firing":
        from app.models.scanner_event import ScannerEvent
        from app.services.alert_service import NotificationDispatcher
        from app.models.alert_rule import AlertRule

        summary = payload.message or payload.title or "Infrastructure alert fired"
        alert_name = payload.commonLabels.get("alertname", "InfrastructureAlert")
        severity = payload.commonLabels.get("severity", "warning")

        # id=None → AlertDeliveryLog.scanner_event_id stores NULL (column is nullable=True)
        synthetic_event = ScannerEvent(
            id=None,
            ticker="SYSTEM",
            event_date=date.today(),
            scanner_type="infrastructure",
            summary=f"[{alert_name}] {summary}",
            severity=severity,
            indicators={"values": firing_alerts[0].values or {}},
            criteria_met={},
            metadata_={
                "grafana_alert_name": alert_name,
                "generator_url": firing_alerts[0].generatorURL or "",
                "firing_count": len(firing_alerts),
            },
        )

        active_rules = (
            db.query(AlertRule)
            .filter(AlertRule.is_active == True)
            .all()
        )
        for rule in active_rules:
            types = rule.scanner_types or []
            if not types or "infrastructure" in types:
                try:
                    NotificationDispatcher.dispatch(rule, synthetic_event, db)
                except Exception as exc:
                    logger.error(
                        f"Failed to dispatch infrastructure alert via rule {rule.id}: {exc}"
                    )

        logger.info(
            f"Infrastructure alert received: {alert_name} severity={severity} "
            f"firing={len(firing_alerts)} alerts"
        )

    return {"status": "received", "alert_count": len(payload.alerts)}
```

**Verify tests pass**:
```bash
docker-compose restart backend
docker-compose exec backend python -m pytest tests/api/test_alerts_infrastructure.py -v 2>&1 | tail -15
# Expected: 3 passed
```

**Validate live**:
```bash
curl -s -X POST http://localhost:8000/api/alerts/infrastructure \
  -H "Content-Type: application/json" \
  -d '{"status":"firing","alerts":[{"status":"firing","labels":{"alertname":"TestAlert"},"annotations":{},"startsAt":"2026-05-28T10:00:00Z"}],"commonLabels":{"alertname":"TestAlert","severity":"warning"},"commonAnnotations":{}}' \
  | python -m json.tool
# Expected: {"status": "received", "alert_count": 1}
```

**Commit**:
```bash
git add backend/app/routers/alerts.py backend/tests/api/test_alerts_infrastructure.py
git commit -m "feat(metrics): add POST /api/alerts/infrastructure Grafana webhook receiver"
```

---

### Task 13: Grafana provisioning — datasource and dashboards

**Files**: all `grafana/provisioning/` files

#### TDD Steps

No unit tests. Validation is that Grafana loads the provisioned dashboards without errors.

**Create** `grafana/provisioning/datasources/prometheus.yaml`:
```yaml
apiVersion: 1
datasources:
  - name: Prometheus
    type: prometheus
    uid: prometheus
    url: http://prometheus:9090
    isDefault: true
    editable: false
    jsonData:
      timeInterval: "15s"
```

**Create** `grafana/provisioning/dashboards/dashboards.yaml`:
```yaml
apiVersion: 1
providers:
  - name: markethawk
    orgId: 1
    folder: MarketHawk
    type: file
    disableDeletion: false
    updateIntervalSeconds: 30
    options:
      path: /etc/grafana/provisioning/dashboards
      foldersFromFilesStructure: false
```

**Create** `grafana/provisioning/dashboards/api-overview.json`:
```json
{
  "annotations": {"list": []},
  "editable": true,
  "fiscalYearStartMonth": 0,
  "graphTooltip": 0,
  "id": null,
  "links": [],
  "panels": [
    {
      "datasource": {"type": "prometheus", "uid": "prometheus"},
      "fieldConfig": {
        "defaults": {
          "color": {"mode": "palette-classic"},
          "custom": {"drawStyle": "line", "fillOpacity": 0, "lineWidth": 1, "showPoints": "auto", "spanNulls": false}
        },
        "overrides": []
      },
      "gridPos": {"h": 8, "w": 12, "x": 0, "y": 0},
      "id": 1,
      "options": {"legend": {"calcs": [], "displayMode": "list", "placement": "bottom", "showLegend": true}, "tooltip": {"mode": "single", "sort": "none"}},
      "targets": [
        {
          "datasource": {"type": "prometheus", "uid": "prometheus"},
          "expr": "sum(rate(http_requests_total[5m])) by (handler, method)",
          "refId": "A",
          "legendFormat": "{{method}} {{handler}}"
        }
      ],
      "title": "HTTP Request Rate (req/s)",
      "type": "timeseries"
    },
    {
      "datasource": {"type": "prometheus", "uid": "prometheus"},
      "fieldConfig": {
        "defaults": {
          "color": {"mode": "palette-classic"},
          "custom": {"drawStyle": "line", "fillOpacity": 0, "lineWidth": 1, "showPoints": "auto"},
          "unit": "s"
        },
        "overrides": []
      },
      "gridPos": {"h": 8, "w": 12, "x": 12, "y": 0},
      "id": 2,
      "options": {"legend": {"calcs": [], "displayMode": "list", "placement": "bottom", "showLegend": true}, "tooltip": {"mode": "single", "sort": "none"}},
      "targets": [
        {
          "datasource": {"type": "prometheus", "uid": "prometheus"},
          "expr": "histogram_quantile(0.50, sum(rate(http_request_duration_seconds_bucket[5m])) by (le, handler))",
          "refId": "A",
          "legendFormat": "p50 {{handler}}"
        },
        {
          "datasource": {"type": "prometheus", "uid": "prometheus"},
          "expr": "histogram_quantile(0.95, sum(rate(http_request_duration_seconds_bucket[5m])) by (le, handler))",
          "refId": "B",
          "legendFormat": "p95 {{handler}}"
        },
        {
          "datasource": {"type": "prometheus", "uid": "prometheus"},
          "expr": "histogram_quantile(0.99, sum(rate(http_request_duration_seconds_bucket[5m])) by (le, handler))",
          "refId": "C",
          "legendFormat": "p99 {{handler}}"
        }
      ],
      "title": "HTTP Latency Percentiles",
      "type": "timeseries"
    },
    {
      "datasource": {"type": "prometheus", "uid": "prometheus"},
      "fieldConfig": {
        "defaults": {
          "color": {"mode": "palette-classic"},
          "custom": {"drawStyle": "line", "fillOpacity": 0, "lineWidth": 2, "showPoints": "auto"},
          "unit": "percentunit"
        },
        "overrides": []
      },
      "gridPos": {"h": 8, "w": 12, "x": 0, "y": 8},
      "id": 3,
      "options": {"legend": {"calcs": [], "displayMode": "list", "placement": "bottom", "showLegend": true}, "tooltip": {"mode": "single", "sort": "none"}},
      "targets": [
        {
          "datasource": {"type": "prometheus", "uid": "prometheus"},
          "expr": "sum(rate(http_requests_total{status_code=~\"5..\"}[5m])) / sum(rate(http_requests_total[5m]))",
          "refId": "A",
          "legendFormat": "5xx error rate"
        }
      ],
      "title": "HTTP 5xx Error Rate",
      "type": "timeseries"
    },
    {
      "datasource": {"type": "prometheus", "uid": "prometheus"},
      "fieldConfig": {
        "defaults": {
          "color": {"mode": "palette-classic"},
          "custom": {"drawStyle": "line", "fillOpacity": 0, "lineWidth": 1, "showPoints": "auto"}
        },
        "overrides": []
      },
      "gridPos": {"h": 8, "w": 12, "x": 12, "y": 8},
      "id": 4,
      "options": {"legend": {"calcs": [], "displayMode": "list", "placement": "bottom", "showLegend": true}, "tooltip": {"mode": "single", "sort": "none"}},
      "targets": [
        {
          "datasource": {"type": "prometheus", "uid": "prometheus"},
          "expr": "sum(rate(http_requests_total[5m])) by (status_code)",
          "refId": "A",
          "legendFormat": "HTTP {{status_code}}"
        }
      ],
      "title": "HTTP Requests by Status Code",
      "type": "timeseries"
    }
  ],
  "refresh": "30s",
  "schemaVersion": 39,
  "tags": ["markethawk", "api"],
  "time": {"from": "now-1h", "to": "now"},
  "timepicker": {},
  "timezone": "browser",
  "title": "API Overview",
  "uid": "mh-api-overview",
  "version": 1
}
```

**Create** `grafana/provisioning/dashboards/scanner-performance.json`:
```json
{
  "annotations": {"list": []},
  "editable": true,
  "graphTooltip": 0,
  "id": null,
  "links": [],
  "panels": [
    {
      "datasource": {"type": "prometheus", "uid": "prometheus"},
      "fieldConfig": {
        "defaults": {
          "color": {"mode": "palette-classic"},
          "custom": {"drawStyle": "line", "fillOpacity": 0, "lineWidth": 1, "showPoints": "auto"}
        },
        "overrides": []
      },
      "gridPos": {"h": 8, "w": 12, "x": 0, "y": 0},
      "id": 1,
      "options": {"legend": {"calcs": [], "displayMode": "list", "placement": "bottom", "showLegend": true}, "tooltip": {"mode": "single", "sort": "none"}},
      "targets": [
        {
          "datasource": {"type": "prometheus", "uid": "prometheus"},
          "expr": "rate(scanner_events_total_total[5m])",
          "refId": "A",
          "legendFormat": "{{scanner_type}}"
        }
      ],
      "title": "Scanner Events Rate (events/s)",
      "type": "timeseries"
    },
    {
      "datasource": {"type": "prometheus", "uid": "prometheus"},
      "fieldConfig": {
        "defaults": {
          "color": {"mode": "palette-classic"},
          "custom": {"drawStyle": "line", "fillOpacity": 0, "lineWidth": 1, "showPoints": "auto"},
          "unit": "s"
        },
        "overrides": []
      },
      "gridPos": {"h": 8, "w": 12, "x": 12, "y": 0},
      "id": 2,
      "options": {"legend": {"calcs": [], "displayMode": "list", "placement": "bottom", "showLegend": true}, "tooltip": {"mode": "single", "sort": "none"}},
      "targets": [
        {
          "datasource": {"type": "prometheus", "uid": "prometheus"},
          "expr": "histogram_quantile(0.95, rate(scan_duration_seconds_bucket[10m]))",
          "refId": "A",
          "legendFormat": "p95 {{scanner_type}}"
        },
        {
          "datasource": {"type": "prometheus", "uid": "prometheus"},
          "expr": "histogram_quantile(0.50, rate(scan_duration_seconds_bucket[10m]))",
          "refId": "B",
          "legendFormat": "p50 {{scanner_type}}"
        }
      ],
      "title": "Scan Duration Percentiles",
      "type": "timeseries"
    },
    {
      "datasource": {"type": "prometheus", "uid": "prometheus"},
      "fieldConfig": {
        "defaults": {
          "color": {"mode": "palette-classic"},
          "custom": {"drawStyle": "bars", "fillOpacity": 80, "lineWidth": 0, "showPoints": "never"}
        },
        "overrides": []
      },
      "gridPos": {"h": 8, "w": 24, "x": 0, "y": 8},
      "id": 3,
      "options": {"legend": {"calcs": ["sum"], "displayMode": "list", "placement": "bottom", "showLegend": true}, "tooltip": {"mode": "single", "sort": "none"}},
      "targets": [
        {
          "datasource": {"type": "prometheus", "uid": "prometheus"},
          "expr": "increase(scanner_events_total_total[1h])",
          "refId": "A",
          "legendFormat": "{{scanner_type}}"
        }
      ],
      "title": "Scanner Events — Hourly Total",
      "type": "timeseries"
    }
  ],
  "refresh": "30s",
  "schemaVersion": 39,
  "tags": ["markethawk", "scanner"],
  "time": {"from": "now-6h", "to": "now"},
  "timepicker": {},
  "timezone": "browser",
  "title": "Scanner Performance",
  "uid": "mh-scanner-perf",
  "version": 1
}
```

**Create** `grafana/provisioning/dashboards/celery-tasks.json`:
```json
{
  "annotations": {"list": []},
  "editable": true,
  "graphTooltip": 0,
  "id": null,
  "links": [],
  "panels": [
    {
      "datasource": {"type": "prometheus", "uid": "prometheus"},
      "fieldConfig": {
        "defaults": {
          "color": {"mode": "palette-classic"},
          "custom": {"drawStyle": "line", "fillOpacity": 0, "lineWidth": 1, "showPoints": "auto"}
        },
        "overrides": []
      },
      "gridPos": {"h": 8, "w": 12, "x": 0, "y": 0},
      "id": 1,
      "options": {"legend": {"calcs": [], "displayMode": "list", "placement": "bottom", "showLegend": true}, "tooltip": {"mode": "single", "sort": "none"}},
      "targets": [
        {
          "datasource": {"type": "prometheus", "uid": "prometheus"},
          "expr": "rate(celery_tasks_total_total{status=\"success\"}[5m])",
          "refId": "A",
          "legendFormat": "success: {{task_name}}"
        },
        {
          "datasource": {"type": "prometheus", "uid": "prometheus"},
          "expr": "rate(celery_tasks_total_total{status=\"failure\"}[5m])",
          "refId": "B",
          "legendFormat": "failure: {{task_name}}"
        }
      ],
      "title": "Celery Task Rate by Status",
      "type": "timeseries"
    },
    {
      "datasource": {"type": "prometheus", "uid": "prometheus"},
      "fieldConfig": {
        "defaults": {
          "color": {"mode": "palette-classic"},
          "custom": {"drawStyle": "line", "fillOpacity": 0, "lineWidth": 1, "showPoints": "auto"},
          "unit": "s"
        },
        "overrides": []
      },
      "gridPos": {"h": 8, "w": 12, "x": 12, "y": 0},
      "id": 2,
      "options": {"legend": {"calcs": [], "displayMode": "list", "placement": "bottom", "showLegend": true}, "tooltip": {"mode": "single", "sort": "none"}},
      "targets": [
        {
          "datasource": {"type": "prometheus", "uid": "prometheus"},
          "expr": "histogram_quantile(0.95, rate(celery_task_duration_seconds_bucket[10m]))",
          "refId": "A",
          "legendFormat": "p95 {{task_name}}"
        },
        {
          "datasource": {"type": "prometheus", "uid": "prometheus"},
          "expr": "histogram_quantile(0.50, rate(celery_task_duration_seconds_bucket[10m]))",
          "refId": "B",
          "legendFormat": "p50 {{task_name}}"
        }
      ],
      "title": "Celery Task Duration Percentiles",
      "type": "timeseries"
    },
    {
      "datasource": {"type": "prometheus", "uid": "prometheus"},
      "fieldConfig": {
        "defaults": {
          "color": {"mode": "palette-classic"},
          "custom": {"drawStyle": "line", "fillOpacity": 0, "lineWidth": 2, "showPoints": "auto"},
          "unit": "percentunit"
        },
        "overrides": []
      },
      "gridPos": {"h": 8, "w": 24, "x": 0, "y": 8},
      "id": 3,
      "options": {"legend": {"calcs": [], "displayMode": "list", "placement": "bottom", "showLegend": true}, "tooltip": {"mode": "single", "sort": "none"}},
      "targets": [
        {
          "datasource": {"type": "prometheus", "uid": "prometheus"},
          "expr": "rate(celery_tasks_total_total{task_name=~\"run_.*\",status=\"failure\"}[15m]) / rate(celery_tasks_total_total{task_name=~\"run_.*\"}[15m])",
          "refId": "A",
          "legendFormat": "failure rate {{task_name}}"
        }
      ],
      "title": "Celery Scan Task Failure Rate",
      "type": "timeseries"
    }
  ],
  "refresh": "30s",
  "schemaVersion": 39,
  "tags": ["markethawk", "celery"],
  "time": {"from": "now-6h", "to": "now"},
  "timepicker": {},
  "timezone": "browser",
  "title": "Celery Tasks",
  "uid": "mh-celery-tasks",
  "version": 1
}
```

**Create** `grafana/provisioning/dashboards/infrastructure.json`:
```json
{
  "annotations": {"list": []},
  "editable": true,
  "graphTooltip": 0,
  "id": null,
  "links": [],
  "panels": [
    {
      "datasource": {"type": "prometheus", "uid": "prometheus"},
      "fieldConfig": {
        "defaults": {
          "color": {"mode": "palette-classic"},
          "custom": {"drawStyle": "line", "fillOpacity": 10, "lineWidth": 1, "showPoints": "auto"}
        },
        "overrides": []
      },
      "gridPos": {"h": 8, "w": 12, "x": 0, "y": 0},
      "id": 1,
      "options": {"legend": {"calcs": ["last"], "displayMode": "list", "placement": "bottom", "showLegend": true}, "tooltip": {"mode": "single", "sort": "none"}},
      "targets": [
        {
          "datasource": {"type": "prometheus", "uid": "prometheus"},
          "expr": "db_pool_size",
          "refId": "A",
          "legendFormat": "pool size"
        },
        {
          "datasource": {"type": "prometheus", "uid": "prometheus"},
          "expr": "db_pool_checked_out",
          "refId": "B",
          "legendFormat": "checked out"
        },
        {
          "datasource": {"type": "prometheus", "uid": "prometheus"},
          "expr": "db_pool_overflow",
          "refId": "C",
          "legendFormat": "overflow"
        }
      ],
      "title": "DB Connection Pool",
      "type": "timeseries"
    },
    {
      "datasource": {"type": "prometheus", "uid": "prometheus"},
      "fieldConfig": {
        "defaults": {
          "color": {"mode": "palette-classic"},
          "custom": {"drawStyle": "line", "fillOpacity": 10, "lineWidth": 1, "showPoints": "auto"},
          "unit": "percentunit",
          "thresholds": {
            "mode": "absolute",
            "steps": [
              {"color": "green", "value": null},
              {"color": "yellow", "value": 0.7},
              {"color": "red", "value": 0.9}
            ]
          }
        },
        "overrides": []
      },
      "gridPos": {"h": 8, "w": 12, "x": 12, "y": 0},
      "id": 2,
      "options": {"legend": {"calcs": ["last"], "displayMode": "list", "placement": "bottom", "showLegend": true}, "tooltip": {"mode": "single", "sort": "none"}},
      "targets": [
        {
          "datasource": {"type": "prometheus", "uid": "prometheus"},
          "expr": "db_pool_checked_out / (db_pool_size + db_pool_overflow)",
          "refId": "A",
          "legendFormat": "pool utilization"
        }
      ],
      "title": "DB Pool Utilization",
      "type": "timeseries"
    },
    {
      "datasource": {"type": "prometheus", "uid": "prometheus"},
      "fieldConfig": {
        "defaults": {
          "color": {"mode": "palette-classic"},
          "custom": {"drawStyle": "line", "fillOpacity": 10, "lineWidth": 1, "showPoints": "auto"}
        },
        "overrides": []
      },
      "gridPos": {"h": 8, "w": 12, "x": 0, "y": 8},
      "id": 3,
      "options": {"legend": {"calcs": ["last"], "displayMode": "list", "placement": "bottom", "showLegend": true}, "tooltip": {"mode": "single", "sort": "none"}},
      "targets": [
        {
          "datasource": {"type": "prometheus", "uid": "prometheus"},
          "expr": "active_websocket_connections",
          "refId": "A",
          "legendFormat": "active WS connections"
        }
      ],
      "title": "Active WebSocket Connections",
      "type": "timeseries"
    },
    {
      "datasource": {"type": "prometheus", "uid": "prometheus"},
      "fieldConfig": {
        "defaults": {
          "color": {"mode": "thresholds"},
          "mappings": [
            {
              "options": {
                "0": {"color": "red", "index": 1, "text": "Disconnected"},
                "1": {"color": "green", "index": 0, "text": "Connected"}
              },
              "type": "value"
            }
          ],
          "thresholds": {"mode": "absolute", "steps": [{"color": "red", "value": null}, {"color": "green", "value": 1}]}
        },
        "overrides": []
      },
      "gridPos": {"h": 8, "w": 12, "x": 12, "y": 8},
      "id": 4,
      "options": {"colorMode": "background", "graphMode": "none", "justifyMode": "center", "orientation": "auto", "reduceOptions": {"calcs": ["lastNotNull"], "fields": "", "values": false}, "textMode": "auto"},
      "targets": [
        {
          "datasource": {"type": "prometheus", "uid": "prometheus"},
          "expr": "ibkr_connection_status",
          "refId": "A",
          "legendFormat": "IBKR Status"
        }
      ],
      "title": "IBKR Connection Status",
      "type": "stat"
    },
    {
      "datasource": {"type": "prometheus", "uid": "prometheus"},
      "fieldConfig": {
        "defaults": {
          "color": {"mode": "palette-classic"},
          "custom": {"drawStyle": "line", "fillOpacity": 0, "lineWidth": 1, "showPoints": "auto"}
        },
        "overrides": []
      },
      "gridPos": {"h": 8, "w": 24, "x": 0, "y": 16},
      "id": 5,
      "options": {"legend": {"calcs": [], "displayMode": "list", "placement": "bottom", "showLegend": true}, "tooltip": {"mode": "single", "sort": "none"}},
      "targets": [
        {
          "datasource": {"type": "prometheus", "uid": "prometheus"},
          "expr": "rate(polygon_api_calls_total_total[5m])",
          "refId": "A",
          "legendFormat": "{{endpoint}}"
        }
      ],
      "title": "Polygon API Call Rate",
      "type": "timeseries"
    }
  ],
  "refresh": "30s",
  "schemaVersion": 39,
  "tags": ["markethawk", "infrastructure"],
  "time": {"from": "now-1h", "to": "now"},
  "timepicker": {},
  "timezone": "browser",
  "title": "Infrastructure",
  "uid": "mh-infrastructure",
  "version": 1
}
```

**Validate**:
```bash
docker-compose restart grafana
# Wait 15s for provisioning to run
curl -s -u admin:admin http://localhost:3001/api/dashboards/uid/mh-api-overview | python -m json.tool | grep '"title"'
# Expected: "title": "API Overview"
curl -s -u admin:admin http://localhost:3001/api/dashboards/uid/mh-scanner-perf | python -m json.tool | grep '"title"'
# Expected: "title": "Scanner Performance"
curl -s -u admin:admin http://localhost:3001/api/dashboards/uid/mh-celery-tasks | python -m json.tool | grep '"title"'
# Expected: "title": "Celery Tasks"
curl -s -u admin:admin http://localhost:3001/api/dashboards/uid/mh-infrastructure | python -m json.tool | grep '"title"'
# Expected: "title": "Infrastructure"
```

**Commit**:
```bash
git add grafana/provisioning/datasources/ grafana/provisioning/dashboards/
git commit -m "feat(metrics): provision Grafana datasource and 4 dashboards (API, scanner, Celery, infrastructure)"
```

---

### Task 14: Grafana alerting rules provisioning

**Files**: `grafana/provisioning/alerting/contact-points.yaml`, `grafana/provisioning/alerting/notification-policies.yaml`, `grafana/provisioning/alerting/rules.yaml`

#### TDD Steps

No unit tests. Validation: Grafana loads rules without errors.

**Create** `grafana/provisioning/alerting/contact-points.yaml`:
```yaml
apiVersion: 1
contactPoints:
  - orgId: 1
    name: markethawk-backend
    receivers:
      - uid: markethawk-webhook
        type: webhook
        settings:
          url: http://backend:8000/api/alerts/infrastructure
          httpMethod: POST
        disableResolveMessage: false
```

**Create** `grafana/provisioning/alerting/notification-policies.yaml`:
```yaml
apiVersion: 1
policies:
  - orgId: 1
    receiver: markethawk-backend
    group_by: ["alertname"]
    group_wait: 30s
    group_interval: 5m
    repeat_interval: 4h
```

**Create** `grafana/provisioning/alerting/rules.yaml`:
```yaml
apiVersion: 1
groups:
  - name: markethawk-infrastructure
    orgId: 1
    folder: MarketHawk Alerts
    interval: 1m
    rules:
      - uid: mh-api-error-rate
        title: High API Error Rate
        condition: B
        data:
          - refId: A
            relativeTimeRange:
              from: 300
              to: 0
            datasourceUid: prometheus
            model:
              expr: "sum(rate(http_requests_total{status_code=~\"5..\"}[5m])) / sum(rate(http_requests_total[5m]))"
              instant: true
              refId: A
          - refId: B
            relativeTimeRange:
              from: 300
              to: 0
            datasourceUid: "__expr__"
            model:
              type: classic_conditions
              refId: B
              conditions:
                - evaluator:
                    type: gt
                    params: [0.05]
                  operator:
                    type: and
                  query:
                    params: [A]
                  reducer:
                    type: last
                  type: query
        noDataState: NoData
        execErrState: Error
        for: 5m
        annotations:
          summary: "API 5xx error rate exceeded 5% over the last 5 minutes"
        labels:
          severity: warning
        isPaused: false

      - uid: mh-scan-failure-rate
        title: High Scan Failure Rate
        condition: B
        data:
          - refId: A
            relativeTimeRange:
              from: 900
              to: 0
            datasourceUid: prometheus
            model:
              expr: "rate(celery_tasks_total_total{task_name=~\"run_.*\",status=\"failure\"}[15m]) / rate(celery_tasks_total_total{task_name=~\"run_.*\"}[15m])"
              instant: true
              refId: A
          - refId: B
            relativeTimeRange:
              from: 900
              to: 0
            datasourceUid: "__expr__"
            model:
              type: classic_conditions
              refId: B
              conditions:
                - evaluator:
                    type: gt
                    params: [0.20]
                  operator:
                    type: and
                  query:
                    params: [A]
                  reducer:
                    type: last
                  type: query
        noDataState: NoData
        execErrState: Error
        for: 15m
        annotations:
          summary: "Scan task failure rate exceeded 20% over the last 15 minutes"
        labels:
          severity: critical
        isPaused: false

      - uid: mh-db-pool-exhaustion
        title: DB Pool Near Exhaustion
        condition: B
        data:
          - refId: A
            relativeTimeRange:
              from: 300
              to: 0
            datasourceUid: prometheus
            model:
              expr: "db_pool_checked_out / (db_pool_size + db_pool_overflow)"
              instant: true
              refId: A
          - refId: B
            relativeTimeRange:
              from: 300
              to: 0
            datasourceUid: "__expr__"
            model:
              type: classic_conditions
              refId: B
              conditions:
                - evaluator:
                    type: gt
                    params: [0.90]
                  operator:
                    type: and
                  query:
                    params: [A]
                  reducer:
                    type: last
                  type: query
        noDataState: NoData
        execErrState: Error
        for: 5m
        annotations:
          summary: "DB connection pool utilization exceeded 90%"
        labels:
          severity: warning
        isPaused: false
```

**Validate**:
```bash
docker-compose restart grafana
curl -s -u admin:admin http://localhost:3001/api/v1/provisioning/alert-rules | python -m json.tool | grep '"title"'
# Expected: "title": "High API Error Rate", "High Scan Failure Rate", "DB Pool Near Exhaustion"
curl -s -u admin:admin http://localhost:3001/api/v1/provisioning/contact-points | python -m json.tool | grep '"name"'
# Expected: "name": "markethawk-backend"
```

**Commit**:
```bash
git add grafana/provisioning/alerting/
git commit -m "feat(metrics): provision Grafana alerting rules and webhook contact point for infrastructure alerts"
```

---

### Task 15: Environment config and documentation updates

**Files**: `.env.example`, `ENV_VARIABLES.md`, `CLAUDE.md`

#### TDD Steps

No tests. Straightforward documentation updates.

**Edit `.env.example`** — add after the `# OPTIONAL: Dark Factory` section:
```bash
# =============================================================================
# OPTIONAL: Monitoring (Prometheus + Grafana)
# =============================================================================
# Grafana admin password (default: admin — change in production).
# GRAFANA_ADMIN_PASSWORD=change_me_grafana_password
```

**Edit `ENV_VARIABLES.md`** — add a row in the optional variables table:
```
| `GRAFANA_ADMIN_PASSWORD` | `admin` | Grafana web UI admin password. Set a strong value in production. Applied via docker-compose to the `grafana` container. |
```

**Edit `CLAUDE.md`** — update the service port table to add two rows:
```markdown
| Prometheus  | http://localhost:9090         |
| Grafana     | http://localhost:3001         |
```

**Commit**:
```bash
git add .env.example ENV_VARIABLES.md CLAUDE.md
git commit -m "docs: add GRAFANA_ADMIN_PASSWORD and document Prometheus/Grafana service ports"
```

---

## End-to-End Validation Checklist

Run through this checklist after all 15 tasks are complete:

```bash
# 1. All containers healthy
docker-compose ps
# Expected: backend, celery-worker, prometheus, grafana all Up

# 2. /metrics endpoint returns data
curl -s http://localhost:8000/metrics | grep -c "# TYPE"
# Expected: >= 10

# 3. Prometheus scrapes successfully
curl -s "http://localhost:9090/api/v1/query?query=up{job='markethawk_backend'}" \
  | python -m json.tool | grep '"value"'
# Expected: "value": [timestamp, "1"]

# 4. All 4 dashboards provisioned
curl -s -u admin:admin http://localhost:3001/api/search?type=dash-db | python -m json.tool | grep '"title"'
# Expected: "API Overview", "Scanner Performance", "Celery Tasks", "Infrastructure"

# 5. Infrastructure alert endpoint works
curl -s -X POST http://localhost:8000/api/alerts/infrastructure \
  -H "Content-Type: application/json" \
  -d '{"status":"firing","alerts":[{"status":"firing","labels":{"alertname":"Test"},"annotations":{},"startsAt":"2026-05-28T10:00:00Z"}],"commonLabels":{"alertname":"Test","severity":"warning"},"commonAnnotations":{}}' \
  | python -m json.tool
# Expected: {"status": "received", "alert_count": 1}

# 6. Backend tests pass
docker-compose exec backend python -m pytest tests/api/test_metrics.py tests/api/test_alerts_infrastructure.py tests/core/test_metrics_module.py -v 2>&1 | tail -20
# Expected: all passed
```

---

## Corrections Applied (Architect Review Cycle 1)

1. **Added Task 7 (`trading.py`)** — spec requires all 4 task files to be instrumented; `execute_auto_trade`, `submit_approved_order`, and `poll_auto_trade_fills` are now covered.

2. **Fixed tmpfs volume** — `prometheus_multiproc` now uses `driver: local` with `driver_opts: type: tmpfs` instead of a named persistent volume, preventing stale file accumulation.

3. **Explicit non-inclusion of `live-scanner`, `celery-beat`, `forecast-worker`** — documented in Task 4. These containers intentionally do not get `PROMETHEUS_MULTIPROC_DIR`; without the env var, `prometheus_client` operates in single-process mode and writes nothing to disk.

4. **Fixed FK violation** — `ScannerEvent(id=None)` instead of `id=-1`. `AlertDeliveryLog.scanner_event_id` is `nullable=True` in the model, so `NULL` is valid.

5. **Added `backend/tests/core/__init__.py`** creation step in Task 1.

6. **Added `scan_task_websocket`** to Task 11 WebSocket tracking (3 endpoints total: `stock_live_websocket`, `watchlist_live_websocket`, `scan_task_websocket`).

7. **Used `REGISTRY.get_sample_value()`** (public API) instead of `._value.get()` internals in test assertions.

8. **Fixed Pydantic import** — only `BaseModel` is added to `alerts.py`; `Optional`, `List`, `Dict`, `Any` were already imported from `typing`.
