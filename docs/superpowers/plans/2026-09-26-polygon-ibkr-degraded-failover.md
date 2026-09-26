# Polygon↔IBKR Degraded-Feed Failover for Pre-Market Scans — Implementation Plan

**Issue:** #388
**Spec:** `docs/superpowers/specs/2026-09-16-polygon-ibkr-degraded-failover-design.md`
**Date:** 2026-09-26

## Goal

Implement the Hybrid failover posture (spec §3.1) for #388. Full-universe scans on today's
pre-market data are **alert-and-degrade, never switch providers**. The Active Watchlist
(IBKR-sourced) gets no new failover logic; this plan only documents it. The per-ticker Polygon
chart stream gets detection and a UI badge, but no fallback.

Concretely:

1. A cross-process, Redis-backed rolling-window health record for Polygon, fed by every REST call
   through `MassiveDataProvider` plus per-process circuit-breaker state changes.
2. Four new Prometheus gauges (`provider_request_latency_p95_seconds`, `provider_error_rate`,
   `provider_circuit_breaker_state`, `polygon_ws_connected`) refreshed at scrape time. A fifth
   gauge (`scan_provider_gap_severity`) lets the "empty-but-green" class page.
3. Pre-market scan ingestion diagnostics (`no_premarket_data` / `no_history` / `evaluated` /
   `errors` counts plus the freshest pre-market bar timestamp). These are threaded back to
   `_run_universe_scan_logic` through an opt-in `diagnostics_out` orchestrator kwarg.
4. `_run_universe_scan_logic` re-evaluates degradation at completion, and before each live day,
   and writes it into `ScannerRun.data_degraded` plus `quality_gate.issues[]` (`code=provider_gap`,
   `detail.subtype="live_degradation"`). Breaker-open and error-rate conditions stop the scan.
5. API: `/scanner/history` and `/scanner/runs/{id}/status` expose `data_degraded` and
   `live_provider_gaps`. `/scanner/history` gains `universe_id` / `scanner_type` / `data_degraded`
   filters.
6. UI: a degraded banner in the Scanner `ResultsPanel`, and a "Live feed unavailable — showing
   last known data" badge on `StockDetailPage`.
7. Grafana alert rules and dashboard panels, ADR-0013, a runbook section in
   `deployment-guide.md`, and updates to `ARCHITECTURE.md` and `ENV_VARIABLES.md`.

## Architecture

```
MassiveDataProvider (_get_bars_impl / _get_ticker_details_impl / _fetch_snapshots_raw / extras)
   │  with track_provider_call("polygon", endpoint): …          (any process)
   ▼
app/core/provider_health.py ──► Redis  mh:provider_health:polygon:calls:<minute>   (HINCRBY, TTL)
   ▲                                     mh:provider_health:polygon:breaker         (HSET host:pid)
   │ HealthRecordingListener.state_change (pybreaker listener on POLYGON_BREAKER, per process)
   │
   ├── get_provider_health("polygon") → ProviderHealthSnapshot (error rate 5m, p95 15m,
   │        worst breaker state across processes + local POLYGON_BREAKER fast path)
   │
   ├── refresh_provider_health_gauges()  ← called by backend GET /metrics at scrape time
   │
   └── app/services/provider_degradation.py (pure): snapshot + pre-market diagnostics
            → ProviderGapFinding[] → apply_provider_gaps(run) → quality_gate / data_degraded
                 ▲
app/tasks/scanning.py::_run_universe_scan_logic  (pre-day check → abort; completion check)
                 ▲ diagnostics_out
app/services/pre_market_scan.py::run_pre_market_scan  (counts + max_premarket_bar_ts)
```

**Design decisions this plan makes (the spec left them to the plan phase):**

| Decision | Choice | Why |
|---|---|---|
| Module location for the health record | `app/core/provider_health.py` | Infra concern, next to `cache.py`/`circuit_breakers.py`/`metrics.py`; keeps `core` from importing `services`. |
| Redis layout | Per-minute hash buckets (`total`, `errors`, `lat_<i>` histogram counts), TTL = max window + 2 min | O(1) memory regardless of call volume; one pipelined round trip per Polygon call. Redis stays ephemeral-only, per memory `[AVOID] Do not introduce Redis for durable state`. |
| Redis outage handling | After any Redis error, skip health writes for 30 s (`_REDIS_BACKOFF_SECONDS`) | Without this, a Redis outage would add socket-timeout latency (up to 1 s) to every Polygon call during bulk syncs. |
| Gauge refresh | At scrape time in the backend `/metrics` handler; `multiprocess_mode="livemostrecent"` | Values stay current even when no Polygon calls happen. Only the API process sets these gauges, so "most recent" is the correct aggregation. |
| Breaker-state staleness | Entries older than the 5-min error window are ignored. `open` entries older than `POLYGON_CB_RESET_TIMEOUT` read as `half-open`. | pybreaker only leaves `open` on the next call attempt. An idle process must not pin the signal at "open" forever. |
| Error rate / p95 minimum sample | Both report `0`/`None` below `PROVIDER_HEALTH_MIN_CALLS` (20) | Keeps 1-of-2 failures from tripping the alert or aborting a scan. |
| Failure class → severity/action | See the table directly below | Encodes spec §3.2. |
| Where the live checks apply | Only to "live session days": `event_date` = today's ET date and now ≥ 04:00 ET. Historical-range scans are untouched. | A live Polygon outage only affects today's freshly ingested data. Historical gaps remain the domain of `_compute_data_degraded` and the existing `quality_gate` evidence. |
| Distinguishing new issues from existing `provider_gap` issues | `detail.subtype = "live_degradation"` | `_build_assessment` **already emits** `provider_gap` with `subtype` ∈ {`absent`,`partial`,`structural`} (`services/quality_gate.py:315-415`). The spec's claim that `provider_gap` is "not yet emitted" is out of date. The UI and API filter on the new subtype so historical report gaps don't light up the live banner. |
| Diagnostics hand-off | `ScannerDescriptor.supports_diagnostics` flag + optional `diagnostics_out` kwarg on `scan_orchestrator.run` | This is the house `diagnostics_out` style (`liquidity_hunt.py`, `pocket_pivot.py`). Other scanners' `_run` adapters don't change, and `test_run_dispatches_to_registered_fn`'s exact-kwargs assertion still holds. |
| Per-ticker stream status transport | A `{"type":"feed_status","polygon_ws_connected":…}` frame on the existing ticker WS, sent on connect and on change (polled every 5 s) | This is the "small status field on the ticker WS payload" option in spec §3.7. It needs no new endpoint and the state lives in the same process as the stream. |
| `polygon_ws_connected` when the stream is disabled by config | `-1` (alert only fires on `== 0`); the UI badge is hidden | A dev stack with `LIVE_WEBSOCKET_ENABLED=false` must not page forever. |
| `polygon_ws_connected` true-ness | `StockWebSocketManager.run_client` now resets `_connected=False` in a `finally:` block | Today `_connected` stays `True` if `client.run()` returns without raising, which would hide a dropped stream. |
| Paging the "empty responses" class | New `scan_provider_gap_severity{scanner_type}` gauge + Grafana rule `pre-market-scan-provider-gap` | The table requires a page for this class, but healthy-200 outages are invisible to the provider gauges. |
| Latency alert | Separate `warning`-severity rule `polygon-latency-elevated` | Spec §3.6 lists latency in the alert, while §3.2 says latency means "no page". A warning-severity rule satisfies both. |

**Failure class → posture (encoded in `provider_degradation.py`):**

| Failure class (spec §3.2) | Finding `reason` | Severity | Scan action |
|---|---|---|---|
| Circuit breaker open in any process | `breaker_open` | blocker | Stop: `status="failed"`, error message, `data_degraded=True`, page |
| 429s / error rate ≥ `POLYGON_HEALTH_ERROR_RATE_THRESHOLD` (0.25, ≥20 calls, 5 min) | `error_rate` | blocker | Stop (same as above) |
| Elevated latency (p95 ≥ `POLYGON_HEALTH_LATENCY_P95_THRESHOLD_SECONDS`, 5 s, 15 min) | `latency` | warning | Continue; mark degraded; no page |
| Empty/null on healthy 200: no pre-market minute bars today (≥ 04:10 ET) | `no_fresh_premarket_bars` | blocker | Complete; mark degraded; page via `scan_provider_gap_severity` |
| Empty/null on healthy 200: freshest bar older than `PREMARKET_BAR_STALENESS_MINUTES` (10) during 04:00–09:30 ET | `stale_premarket_bars` | blocker | Complete; mark degraded; page |
| Partial coverage: `evaluated / (evaluated + no_premarket_data) < PREMARKET_MIN_COVERAGE_RATIO` (0.5, deliberately lenient because ordinary pre-open sparsity leaves many tickers with no trades; env-tunable) | `partial_coverage` | warning | Complete; mark degraded; `coverage_ratio` in `detail` |

## Tech Stack

- **Backend:** FastAPI, SQLAlchemy 2.0 (sync), Pydantic v2, `redis` 7.4 (sync client via
  `app/core/cache.get_redis`), `pybreaker` 1.4 listener API, `prometheus-client` 0.21.1
  (`livemostrecent`/`mostrecent` multiprocess modes, verified present), pytest + `fakeredis` 2.28.
- **Frontend:** React 18 + TypeScript, React Query, Tailwind, Vitest + Testing Library.
- **Ops:** Grafana provisioning YAML/JSON, Markdown docs.

## File Structure

| File | Change |
|---|---|
| `backend/app/core/config.py` | +7 env-tunable settings (health windows, thresholds, pre-market staleness/coverage) |
| `backend/app/core/metrics.py` | +5 gauges |
| `backend/app/core/provider_health.py` | **New.** Redis rolling-window record, `track_provider_call`, `get_provider_health`, `refresh_provider_health_gauges`, `worker_id` |
| `backend/app/core/circuit_breakers.py` | `HealthRecordingListener`, attached to `POLYGON_BREAKER` |
| `backend/app/providers/massive.py` | Wrap each Polygon REST call in `track_provider_call` |
| `backend/app/services/provider_degradation.py` | **New.** Pure finding logic + `apply_provider_gaps` + `live_provider_gaps` + `severity_level` |
| `backend/app/services/scan_orchestrator.py` | `ScannerDescriptor.supports_diagnostics`; `run(..., diagnostics_out=None)` |
| `backend/app/services/pre_market_scan.py` | `counts` buckets + `max_premarket_bar_ts` → `diagnostics_out`; register with `supports_diagnostics=True` |
| `backend/app/tasks/scanning.py` | Pre-day abort check, completion finalize, gauge reset + set, NYSE holiday resolution, `detail.phase`, `data_degraded` in `completed` payload |
| `backend/app/schemas/scanner.py` | `data_degraded` + `live_provider_gaps` on `ScannerRunResponse` and `ScannerRunStatusResponse` |
| `backend/app/routers/scanner.py` | `/history` filters + projection; `/runs/{id}/status` projection |
| `backend/app/services/websocket_manager.py` | `feed_status()`; reset `_connected` when the client thread exits |
| `backend/app/routers/live_data.py` | `feed_status` frame on connect and on change |
| `backend/app/main.py` | `/metrics` refreshes provider-health gauges before export |
| `backend/tests/conftest.py` | Autouse fixture isolating provider-health Redis writes |
| `backend/tests/core/test_provider_health_config.py` | **New** |
| `backend/tests/core/test_metrics_module.py` | +1 test for the new gauges |
| `backend/tests/core/test_provider_health.py` | **New** |
| `backend/tests/providers/test_breaker_health_listener.py` | **New** |
| `backend/tests/providers/test_massive_health_instrumentation.py` | **New** |
| `backend/tests/services/test_provider_degradation.py` | **New** |
| `backend/tests/services/test_scan_orchestrator.py` | +2 tests (diagnostics opt-in) |
| `backend/tests/services/test_pre_market_scan_module.py` | +1 DB test (diagnostics buckets) |
| `backend/tests/tasks/test_scanning_degradation.py` | **New.** Pre-day abort, completion paths, historical no-op |
| `backend/tests/tasks/test_polygon_outage_simulation.py` | **New.** Acceptance: blocked-egress simulation end to end |
| `backend/tests/api/test_scanner_degraded_runs.py` | **New.** API filters and projection |
| `backend/tests/api/test_metrics.py` | +1 test (gauges present at scrape) |
| `backend/tests/services/test_websocket_manager.py` | +2 tests (`feed_status`, `_connected` reset) |
| `backend/tests/api/test_live_feed_status.py` | **New.** Ticker WS sends `feed_status` frame |
| `backend/tests/core/test_grafana_provider_alerts.py` | **New.** Rules and dashboards reference the new metrics |
| `frontend/src/api/scanner/types.ts` | `LiveProviderGap`, `ScannerHistoryFilters`, new optional fields |
| `frontend/src/api/scanner/runs.ts` | `fetchScannerHistory(limit, filters)` |
| `frontend/src/api/scanner/runs.test.ts` | **New** |
| `frontend/src/pages/Scanner/ProviderDegradedBanner.tsx` (+ `.test.tsx`) | **New** |
| `frontend/src/pages/Scanner/ResultsPanel.tsx` | `latestRun` prop → banner |
| `frontend/src/pages/Scanner/index.tsx` | Latest-run query → `ResultsPanel` |
| `frontend/src/hooks/useLiveStockData.ts` (+ test) | Handle the `feed_status` frame; expose `feedAvailable` |
| `frontend/src/pages/StockDetailPage/LiveFeedUnavailableBadge.tsx` (+ `.test.tsx`) | **New** |
| `frontend/src/pages/StockDetailPage/index.tsx` | Render the badge when `feedAvailable === false` |
| `grafana/provisioning/alerting/rules.yaml` | +3 rules |
| `grafana/provisioning/dashboards/infrastructure.json`, `scanner-performance.json` | +panels |
| `docs/adr/0013-polygon-ibkr-hybrid-failover.md` + `docs/adr/README.md` | **New** ADR + index row |
| `deployment-guide.md` | "Pre-Market Data Degradation Runbook" section |
| `ARCHITECTURE.md` | Metrics table rows + `quality_gate.py` note on the `live_degradation` subtype |
| `ENV_VARIABLES.md` | "Provider Health / Degraded-Feed Failover" section |

No DB migration: `ScannerRun.data_degraded` (Boolean) and `ScannerRun.quality_gate` (JSONB) already exist.

## Conventions for every task

- Backend tests run inside the backend container: `docker-compose exec backend python -m pytest <path> -q`.
  From the host with a venv, use `cd backend && python -m pytest <path> -q`. Commands below use the
  container form.
- Frontend checks: `cd frontend && npx vitest run <path>` and `npx tsc --noEmit`.
- Commit after every task with a conventional-commit subject that includes `(#388)`. End each
  message with the `Co-Authored-By` trailer from the session's attribution rules.
- Never let health recording raise into a provider call path. Every Redis touch in
  `provider_health.py` is wrapped.

---

## Task 1: Settings for provider health and pre-market degradation

**Files:** `backend/app/core/config.py`, `backend/tests/core/test_provider_health_config.py` (new)

- [ ] **Step 1: Write the failing test.** Create `backend/tests/core/test_provider_health_config.py`:

```python
"""Defaults for the #388 provider-health / degraded-feed settings (ADR-0013)."""

from app.core.config import settings


def test_provider_health_window_defaults():
    assert settings.PROVIDER_HEALTH_ERROR_WINDOW_SECONDS == 300
    assert settings.PROVIDER_HEALTH_LATENCY_WINDOW_SECONDS == 900
    assert settings.PROVIDER_HEALTH_MIN_CALLS == 20


def test_polygon_health_threshold_defaults():
    assert settings.POLYGON_HEALTH_ERROR_RATE_THRESHOLD == 0.25
    assert settings.POLYGON_HEALTH_LATENCY_P95_THRESHOLD_SECONDS == 5.0


def test_premarket_degradation_defaults():
    assert settings.PREMARKET_BAR_STALENESS_MINUTES == 10
    assert settings.PREMARKET_MIN_COVERAGE_RATIO == 0.5
```

- [ ] **Step 2: Verify it fails.** `docker-compose exec backend python -m pytest tests/core/test_provider_health_config.py -q`
  Expected: 3 failed with `AttributeError: 'Settings' object has no attribute 'PROVIDER_HEALTH_ERROR_WINDOW_SECONDS'`.

- [ ] **Step 3: Implement.** In `backend/app/core/config.py`, directly after the
  `IBKR_CB_RESET_TIMEOUT: int = 120` line (inside `class Settings`), insert:

```python

    # ── Provider health / degraded-feed failover (#388, ADR-0013) ───────
    # Rolling windows for the cross-process Polygon health record in Redis.
    # 5 min error window mirrors the Celery failure-rate alert's [5m]; 15 min
    # latency window mirrors the scanner p95 alert's 900 s range.
    PROVIDER_HEALTH_ERROR_WINDOW_SECONDS: int = 300
    PROVIDER_HEALTH_LATENCY_WINDOW_SECONDS: int = 900
    # Below this many calls in a window, error rate / p95 are reported as 0 / None.
    PROVIDER_HEALTH_MIN_CALLS: int = 20
    # Error rate at/above which Polygon counts as degraded (blocker: scan stops).
    POLYGON_HEALTH_ERROR_RATE_THRESHOLD: float = 0.25
    # Rolling p95 latency at/above which Polygon counts as slow (warning: scan continues).
    POLYGON_HEALTH_LATENCY_P95_THRESHOLD_SECONDS: float = 5.0
    # Pre-market ingestion: freshest minute bar older than this during 04:00–09:30 ET
    # (or no bar at all once this long past 04:00 ET) marks the run degraded.
    PREMARKET_BAR_STALENESS_MINUTES: int = 10
    # Fraction of evaluable tickers that must have pre-market volume; below → warning.
    PREMARKET_MIN_COVERAGE_RATIO: float = 0.5
```

- [ ] **Step 4: Verify it passes.** Same command. Expected: `3 passed`.
- [ ] **Step 5: Commit.** `git add backend/app/core/config.py backend/tests/core/test_provider_health_config.py && git commit -m "feat(config): provider-health and pre-market degradation settings (#388)"`

---

## Task 2: New Prometheus gauges

**Files:** `backend/app/core/metrics.py`, `backend/tests/core/test_metrics_module.py`

- [ ] **Step 1: Write the failing test.** Append to `backend/tests/core/test_metrics_module.py`:

```python


def test_provider_health_gauges_registered():
    """#388: per-provider health gauges + Polygon WS + scan provider-gap severity."""
    from app.core.metrics import (
        polygon_ws_connected,
        provider_circuit_breaker_state,
        provider_error_rate,
        provider_request_latency_p95_seconds,
        scan_provider_gap_severity,
    )

    assert (
        provider_request_latency_p95_seconds._name
        == "provider_request_latency_p95_seconds"
    )
    assert provider_error_rate._name == "provider_error_rate"
    assert provider_circuit_breaker_state._name == "provider_circuit_breaker_state"
    assert polygon_ws_connected._name == "polygon_ws_connected"
    assert scan_provider_gap_severity._name == "scan_provider_gap_severity"
    assert provider_error_rate._labelnames == ("provider",)
    assert scan_provider_gap_severity._labelnames == ("scanner_type",)
    assert provider_error_rate._multiprocess_mode == "livemostrecent"
    assert scan_provider_gap_severity._multiprocess_mode == "mostrecent"
```

- [ ] **Step 2: Verify it fails.** `docker-compose exec backend python -m pytest tests/core/test_metrics_module.py -q`
  Expected: `test_provider_health_gauges_registered` fails with `ImportError: cannot import name 'polygon_ws_connected'`.

- [ ] **Step 3: Implement.** In `backend/app/core/metrics.py`, directly after the
  `ibkr_connection_status = Gauge(...)` block, insert:

```python

# ── Provider health (#388, ADR-0013) ────────────────────────────────────────
# Set only by the API process at scrape time (refresh_provider_health_gauges in
# app/core/provider_health.py) from the cross-process Redis health record, so
# "livemostrecent" is the right multiprocess aggregation.
provider_request_latency_p95_seconds = Gauge(
    "provider_request_latency_p95_seconds",
    "Rolling 15-minute p95 latency of provider REST requests (seconds; 0 = too few calls)",
    ["provider"],
    multiprocess_mode="livemostrecent",
)

provider_error_rate = Gauge(
    "provider_error_rate",
    "Rolling 5-minute provider request error rate (0.0–1.0; 0 = too few calls)",
    ["provider"],
    multiprocess_mode="livemostrecent",
)

provider_circuit_breaker_state = Gauge(
    "provider_circuit_breaker_state",
    "Worst provider circuit-breaker state across processes (0=closed, 1=half-open, 2=open)",
    ["provider"],
    multiprocess_mode="livemostrecent",
)

polygon_ws_connected = Gauge(
    "polygon_ws_connected",
    "Polygon per-ticker WebSocket stream (1=connected, 0=disconnected, -1=disabled by config)",
    multiprocess_mode="livemostrecent",
)

# Set by the Celery worker at the end of each scan that touched a live session day.
# "mostrecent" (not live) so the value survives prefork child recycling.
scan_provider_gap_severity = Gauge(
    "scan_provider_gap_severity",
    "Live provider-gap severity of the most recent scan run (0=none, 1=warning, 2=blocker)",
    ["scanner_type"],
    multiprocess_mode="mostrecent",
)
```

- [ ] **Step 4: Verify it passes.** Same command. Expected: all tests in the file pass.
- [ ] **Step 5: Commit.** `git add backend/app/core/metrics.py backend/tests/core/test_metrics_module.py && git commit -m "feat(metrics): provider health + scan provider-gap gauges (#388)"`

---

## Task 3: `app/core/provider_health.py` — the cross-process health record

**Files:** `backend/app/core/provider_health.py` (new), `backend/tests/conftest.py`,
`backend/tests/core/test_provider_health.py` (new)

- [ ] **Step 1: Add test isolation first** so that no test ever writes health records into the real
  dev Redis. Otherwise test-induced "errors" would fire the live Grafana alert. In
  `backend/tests/conftest.py`, add at the end of the file:

```python


@pytest.fixture(autouse=True)
def _isolate_provider_health_redis(monkeypatch):
    """#388: keep provider-health records out of the real Redis during tests.

    Tests that exercise the health record install a fakeredis via their own
    fixture, which runs after this autouse fixture and overrides it.
    """
    monkeypatch.setattr("app.core.provider_health.get_redis", lambda: None)
    monkeypatch.setattr("app.core.provider_health._redis_backoff_until", 0.0)
```

  (`pytest` is already imported in `tests/conftest.py`; confirm with `grep -n "^import pytest" backend/tests/conftest.py`.)

- [ ] **Step 2: Write the failing tests.** Create `backend/tests/core/test_provider_health.py`:

```python
"""Cross-process provider health record (#388, ADR-0013)."""

import json
import time
from unittest.mock import MagicMock, PropertyMock, patch

import fakeredis
import pytest
from prometheus_client import REGISTRY

from app.core import provider_health as ph

NOW = 1_780_000_020.0  # fixed epoch seconds (20 s into a minute bucket)


@pytest.fixture
def fake_redis(monkeypatch):
    server = fakeredis.FakeRedis(decode_responses=True)
    monkeypatch.setattr(ph, "get_redis", lambda: server)
    monkeypatch.setattr(ph, "_redis_backoff_until", 0.0)
    # get_provider_health ORs in the process-global breaker; never inherit an
    # open breaker from an earlier test.
    ph.POLYGON_BREAKER.close()
    server.flushall()
    yield server
    ph.POLYGON_BREAKER.close()


def _record(n, ok=True, latency=0.05, now=NOW):
    for _ in range(n):
        ph.record_provider_call("polygon", "aggs", ok=ok, latency_s=latency, now=now)


def test_error_rate_over_window(fake_redis):
    _record(15)
    _record(5, ok=False)
    snap = ph.get_provider_health("polygon", now=NOW)
    assert snap.calls_error_window == 20
    assert snap.errors_error_window == 5
    assert snap.error_rate == pytest.approx(0.25)
    assert snap.redis_available is True


def test_error_rate_zero_below_min_calls(fake_redis):
    _record(1)
    _record(1, ok=False)
    snap = ph.get_provider_health("polygon", now=NOW)
    assert snap.errors_error_window == 1
    assert snap.error_rate == 0.0


def test_latency_p95_uses_bucket_upper_bound(fake_redis):
    _record(18, latency=0.05)
    _record(2, latency=3.0)
    snap = ph.get_provider_health("polygon", now=NOW)
    assert snap.latency_p95_seconds == 5.0


def test_latency_p95_fast_calls(fake_redis):
    _record(19, latency=0.05)
    _record(1, latency=3.0)
    snap = ph.get_provider_health("polygon", now=NOW)
    assert snap.latency_p95_seconds == 0.1


def test_latency_overflow_bucket(fake_redis):
    _record(20, latency=45.0)
    snap = ph.get_provider_health("polygon", now=NOW)
    assert snap.latency_p95_seconds == 60.0


def test_old_calls_leave_error_window_but_not_latency_window(fake_redis):
    _record(20, ok=False, latency=3.0, now=NOW - 400)
    snap = ph.get_provider_health("polygon", now=NOW)
    assert snap.calls_error_window == 0
    assert snap.error_rate == 0.0
    assert snap.calls_latency_window == 20
    assert snap.latency_p95_seconds == 5.0


def test_breaker_open_in_other_worker_is_seen(fake_redis):
    fake_redis.hset(
        "mh:provider_health:polygon:breaker",
        "celery-worker:42",
        json.dumps({"state": "open", "ts": NOW - 10}),
    )
    snap = ph.get_provider_health("polygon", now=NOW)
    assert snap.breaker_state == "open"
    assert snap.breaker_open_workers == ["celery-worker:42"]


def test_open_entry_older_than_reset_timeout_reads_half_open(fake_redis):
    fake_redis.hset(
        "mh:provider_health:polygon:breaker",
        "api:7",
        json.dumps({"state": "open", "ts": NOW - 120}),
    )
    snap = ph.get_provider_health("polygon", now=NOW)
    assert snap.breaker_state == "half-open"
    assert snap.breaker_open_workers == []


def test_stale_breaker_entry_ignored(fake_redis):
    fake_redis.hset(
        "mh:provider_health:polygon:breaker",
        "gone:1",
        json.dumps({"state": "open", "ts": NOW - 400}),
    )
    assert ph.get_provider_health("polygon", now=NOW).breaker_state == "closed"


def test_record_breaker_state_writes_worker_entry(fake_redis):
    ph.record_breaker_state("polygon", "open", now=NOW)
    raw = fake_redis.hgetall("mh:provider_health:polygon:breaker")
    assert ph.worker_id() in raw
    assert json.loads(raw[ph.worker_id()])["state"] == "open"


def test_local_breaker_fast_path_without_redis(monkeypatch):
    monkeypatch.setattr(ph, "get_redis", lambda: None)
    breaker_cls = type(ph.POLYGON_BREAKER)
    with patch.object(
        breaker_cls, "current_state", new_callable=PropertyMock, return_value="open"
    ):
        snap = ph.get_provider_health("polygon", now=NOW)
    assert snap.redis_available is False
    assert snap.breaker_state == "open"
    assert snap.breaker_open_workers == [ph.worker_id()]


def test_redis_failure_is_swallowed_and_backs_off(monkeypatch):
    broken = MagicMock()
    broken.pipeline.side_effect = ConnectionError("redis down")
    calls = {"n": 0}

    def _get():
        calls["n"] += 1
        return broken

    monkeypatch.setattr(ph, "get_redis", _get)
    monkeypatch.setattr(ph, "_redis_backoff_until", 0.0)
    ph.record_provider_call("polygon", "aggs", ok=True, latency_s=0.1)  # no raise
    ph.record_provider_call("polygon", "aggs", ok=True, latency_s=0.1)
    assert calls["n"] == 1  # second write skipped during backoff


def test_track_provider_call_records_failure_and_reraises(fake_redis):
    with pytest.raises(ConnectionError):
        with ph.track_provider_call("polygon", "aggs"):
            raise ConnectionError("egress blocked")
    with ph.track_provider_call("polygon", "aggs"):
        pass
    snap = ph.get_provider_health("polygon")
    assert snap.errors_error_window == 1
    assert snap.calls_error_window == 2


def test_track_provider_call_is_failure_predicate(fake_redis):
    with pytest.raises(ValueError):
        with ph.track_provider_call("polygon", "aggs", is_failure=lambda exc: False):
            raise ValueError("NOT_AUTHORIZED")
    snap = ph.get_provider_health("polygon")
    assert snap.errors_error_window == 0
    assert snap.calls_error_window == 1


def test_refresh_gauges_sets_values(fake_redis):
    fake_redis.hset(
        "mh:provider_health:polygon:breaker",
        "w:1",
        json.dumps({"state": "open", "ts": time.time()}),
    )
    ph.refresh_provider_health_gauges(ws_connected=False)
    assert (
        REGISTRY.get_sample_value(
            "provider_circuit_breaker_state", {"provider": "polygon"}
        )
        == 2
    )
    assert REGISTRY.get_sample_value("polygon_ws_connected") == 0
    ph.refresh_provider_health_gauges(ws_connected=None)
    assert REGISTRY.get_sample_value("polygon_ws_connected") == -1
```

- [ ] **Step 3: Verify it fails.** `docker-compose exec backend python -m pytest tests/core/test_provider_health.py -q`
  Expected: collection error `ModuleNotFoundError: No module named 'app.core.provider_health'`. (The
  conftest fixture's string-path `setattr` fails the same way, so every test will fail until
  Step 4. Run only this file here.)

- [ ] **Step 4: Implement.** Create `backend/app/core/provider_health.py`:

```python
"""
Cross-process rolling-window health record for external market-data providers.

#388 / ADR-0013. Every Polygon REST call made through MassiveDataProvider records
its outcome and latency here, and POLYGON_BREAKER state changes are recorded per
process ("hostname:pid") by HealthRecordingListener. State lives in Redis as
TTL-bounded per-minute buckets — ephemeral by design, never durable state — so a
Celery scan can read a signal produced by the API process, the universe
orchestrator, or another worker. (Circuit-breaker state itself is in-process per
worker; see core/circuit_breakers.py.)

Every Redis touch is wrapped: health recording must never break or slow a
provider call. After a Redis error, writes pause for _REDIS_BACKOFF_SECONDS.
"""

import json
import logging
import os
import socket
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Callable, Iterator, List, Optional, Tuple

from app.core.cache import get_redis
from app.core.circuit_breakers import POLYGON_BREAKER
from app.core.config import settings
from app.core.metrics import (
    polygon_ws_connected,
    provider_circuit_breaker_state,
    provider_error_rate,
    provider_request_latency_p95_seconds,
)

logger = logging.getLogger(__name__)

_KEY_PREFIX = "mh:provider_health"
_BUCKET_SECONDS = 60
# Upper bounds (seconds) of the latency histogram buckets; one extra +Inf bucket.
LATENCY_BUCKETS: Tuple[float, ...] = (0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0)
# Reported p95 when the 95th percentile lands in the +Inf bucket (> 30 s).
_OVERFLOW_LATENCY_SECONDS = 60.0
BREAKER_STATE_RANK = {"closed": 0, "half-open": 1, "open": 2}
_BREAKER_KEY_TTL_SECONDS = 3600
_REDIS_BACKOFF_SECONDS = 30.0
_redis_backoff_until = 0.0


def worker_id() -> str:
    """Identify this process in health records and quality-gate detail."""
    return f"{socket.gethostname()}:{os.getpid()}"


def _calls_key(provider: str, bucket_start: int) -> str:
    return f"{_KEY_PREFIX}:{provider}:calls:{bucket_start}"


def _breaker_key(provider: str) -> str:
    return f"{_KEY_PREFIX}:{provider}:breaker"


def _latency_field(latency_s: float) -> str:
    for i, bound in enumerate(LATENCY_BUCKETS):
        if latency_s <= bound:
            return f"lat_{i}"
    return f"lat_{len(LATENCY_BUCKETS)}"


def _writable_redis():
    if time.monotonic() < _redis_backoff_until:
        return None
    return get_redis()


def _note_redis_failure(exc: Exception, what: str) -> None:
    global _redis_backoff_until
    _redis_backoff_until = time.monotonic() + _REDIS_BACKOFF_SECONDS
    logger.warning(
        "provider_health: %s failed; pausing health writes for %.0fs: %s",
        what,
        _REDIS_BACKOFF_SECONDS,
        exc,
    )


def record_provider_call(
    provider: str,
    endpoint: str,
    ok: bool,
    latency_s: float,
    now: Optional[float] = None,
) -> None:
    """Add one request outcome to the current minute bucket. Never raises."""
    r = _writable_redis()
    if r is None:
        return
    ts = time.time() if now is None else now
    bucket_start = int(ts // _BUCKET_SECONDS) * _BUCKET_SECONDS
    key = _calls_key(provider, bucket_start)
    ttl = (
        max(
            settings.PROVIDER_HEALTH_ERROR_WINDOW_SECONDS,
            settings.PROVIDER_HEALTH_LATENCY_WINDOW_SECONDS,
        )
        + 2 * _BUCKET_SECONDS
    )
    try:
        pipe = r.pipeline(transaction=False)
        pipe.hincrby(key, "total", 1)
        if not ok:
            pipe.hincrby(key, "errors", 1)
        pipe.hincrby(key, _latency_field(latency_s), 1)
        pipe.expire(key, ttl)
        pipe.execute()
    except Exception as exc:
        _note_redis_failure(exc, f"record {provider}/{endpoint}")


@contextmanager
def track_provider_call(
    provider: str,
    endpoint: str,
    is_failure: Callable[[BaseException], bool] = lambda exc: True,
) -> Iterator[None]:
    """Time the wrapped provider request and record its outcome.

    Exceptions propagate unchanged. ``is_failure`` lets callers exclude
    permanent, request-specific errors (Polygon NOT_AUTHORIZED plan limits)
    from the error rate — the same exclusion the circuit breaker applies.
    """
    start = time.monotonic()
    try:
        yield
    except Exception as exc:
        record_provider_call(
            provider,
            endpoint,
            ok=not is_failure(exc),
            latency_s=time.monotonic() - start,
        )
        raise
    record_provider_call(
        provider, endpoint, ok=True, latency_s=time.monotonic() - start
    )


def record_breaker_state(
    provider: str, state: str, now: Optional[float] = None
) -> None:
    """Record this process's breaker state ("closed"/"half-open"/"open"). Never raises."""
    r = _writable_redis()
    if r is None:
        return
    ts = time.time() if now is None else now
    try:
        r.hset(
            _breaker_key(provider),
            worker_id(),
            json.dumps({"state": state, "ts": ts}),
        )
        r.expire(_breaker_key(provider), _BREAKER_KEY_TTL_SECONDS)
    except Exception as exc:
        _note_redis_failure(exc, f"record {provider} breaker state")


@dataclass
class ProviderHealthSnapshot:
    provider: str
    calls_error_window: int = 0
    errors_error_window: int = 0
    error_rate: float = 0.0
    calls_latency_window: int = 0
    latency_p95_seconds: Optional[float] = None
    breaker_state: str = "closed"
    breaker_open_workers: List[str] = field(default_factory=list)
    redis_available: bool = True


def _p95_from_buckets(counts: List[int]) -> Optional[float]:
    total = sum(counts)
    if total == 0:
        return None
    target = 0.95 * total
    cumulative = 0
    for i, count in enumerate(counts):
        cumulative += count
        if cumulative >= target:
            if i < len(LATENCY_BUCKETS):
                return LATENCY_BUCKETS[i]
            return _OVERFLOW_LATENCY_SECONDS
    return _OVERFLOW_LATENCY_SECONDS


def _merge_breaker_states(
    raw: Optional[dict], now: float, reset_timeout: float
) -> Tuple[str, List[str]]:
    worst = "closed"
    open_workers: List[str] = []
    for wid, payload in (raw or {}).items():
        try:
            entry = json.loads(payload)
            state = str(entry["state"])
            age = now - float(entry["ts"])
        except (ValueError, KeyError, TypeError):
            continue
        if age > settings.PROVIDER_HEALTH_ERROR_WINDOW_SECONDS:
            continue  # process gone or idle — its state says nothing current
        if state == "open" and age > reset_timeout:
            state = "half-open"  # pybreaker would admit a trial call by now
        if state == "open":
            open_workers.append(wid)
        if BREAKER_STATE_RANK.get(state, 0) > BREAKER_STATE_RANK[worst]:
            worst = state
    return worst, sorted(open_workers)


def get_provider_health(
    provider: str = "polygon", now: Optional[float] = None
) -> ProviderHealthSnapshot:
    """Aggregate the rolling windows + per-process breaker states. Never raises."""
    snap = ProviderHealthSnapshot(provider=provider)
    ts = time.time() if now is None else now
    error_window = settings.PROVIDER_HEALTH_ERROR_WINDOW_SECONDS
    latency_window = settings.PROVIDER_HEALTH_LATENCY_WINDOW_SECONDS
    min_calls = settings.PROVIDER_HEALTH_MIN_CALLS
    current = int(ts // _BUCKET_SECONDS) * _BUCKET_SECONDS
    n_buckets = max(error_window, latency_window) // _BUCKET_SECONDS
    starts = [current - i * _BUCKET_SECONDS for i in range(n_buckets)]

    results = None
    r = get_redis()
    if r is not None:
        try:
            pipe = r.pipeline(transaction=False)
            for start in starts:
                pipe.hgetall(_calls_key(provider, start))
            pipe.hgetall(_breaker_key(provider))
            results = pipe.execute()
        except Exception as exc:
            logger.warning("provider_health: read failed for %s: %s", provider, exc)

    if results is None:
        snap.redis_available = False
    else:
        latency_counts = [0] * (len(LATENCY_BUCKETS) + 1)
        for start, bucket in zip(starts, results[:-1]):
            if not bucket:
                continue
            age = current - start
            total = int(bucket.get("total", 0))
            if age < error_window:
                snap.calls_error_window += total
                snap.errors_error_window += int(bucket.get("errors", 0))
            if age < latency_window:
                snap.calls_latency_window += total
                for i in range(len(latency_counts)):
                    latency_counts[i] += int(bucket.get(f"lat_{i}", 0))
        if snap.calls_error_window >= min_calls:
            snap.error_rate = snap.errors_error_window / snap.calls_error_window
        if snap.calls_latency_window >= min_calls:
            snap.latency_p95_seconds = _p95_from_buckets(latency_counts)
        # Only Polygon is instrumented today, so its reset timeout applies.
        snap.breaker_state, snap.breaker_open_workers = _merge_breaker_states(
            results[-1], ts, settings.POLYGON_CB_RESET_TIMEOUT
        )

    # Fast path: this process's own breaker, readable even without Redis.
    if provider == "polygon" and POLYGON_BREAKER.current_state == "open":
        snap.breaker_state = "open"
        me = worker_id()
        if me not in snap.breaker_open_workers:
            snap.breaker_open_workers.append(me)
    return snap


def refresh_provider_health_gauges(
    ws_connected: Optional[bool], provider: str = "polygon"
) -> ProviderHealthSnapshot:
    """Set the provider-health gauges from a fresh snapshot (called at /metrics scrape).

    ``ws_connected`` is StockWebSocketManager.feed_status(): None when the
    per-ticker stream is disabled by configuration (exported as -1).
    """
    snap = get_provider_health(provider)
    provider_error_rate.labels(provider=provider).set(snap.error_rate)
    provider_request_latency_p95_seconds.labels(provider=provider).set(
        snap.latency_p95_seconds or 0.0
    )
    provider_circuit_breaker_state.labels(provider=provider).set(
        BREAKER_STATE_RANK.get(snap.breaker_state, 0)
    )
    polygon_ws_connected.set(-1 if ws_connected is None else int(ws_connected))
    return snap
```

- [ ] **Step 5: Verify it passes.** `docker-compose exec backend python -m pytest tests/core/test_provider_health.py -q` → `15 passed`.
  Also `docker-compose exec backend python -m pytest tests/core tests/providers -q` → no new failures (the conftest fixture now resolves).
- [ ] **Step 6: Commit.** `git add backend/app/core/provider_health.py backend/tests/conftest.py backend/tests/core/test_provider_health.py && git commit -m "feat(core): cross-process Redis provider health record (#388)"`

---

## Task 4: Record circuit-breaker state changes per process

**Files:** `backend/app/core/circuit_breakers.py`, `backend/tests/providers/test_breaker_health_listener.py` (new)

- [ ] **Step 1: Write the failing test.** Create `backend/tests/providers/test_breaker_health_listener.py`:

```python
"""POLYGON_BREAKER state changes are recorded to the provider-health store (#388)."""

import pybreaker
import pytest

from app.core.circuit_breakers import POLYGON_BREAKER, HealthRecordingListener


def _boom():
    raise RuntimeError("egress blocked")


def test_listener_records_open_state(monkeypatch):
    seen = []
    monkeypatch.setattr(
        "app.core.provider_health.record_breaker_state",
        lambda provider, state, now=None: seen.append((provider, state)),
    )
    breaker = pybreaker.CircuitBreaker(
        fail_max=1, reset_timeout=60, listeners=[HealthRecordingListener("polygon")]
    )
    with pytest.raises(Exception):
        breaker.call(_boom)
    assert ("polygon", "open") in seen


def test_listener_never_raises(monkeypatch):
    def _explode(provider, state, now=None):
        raise ConnectionError("redis down")

    monkeypatch.setattr("app.core.provider_health.record_breaker_state", _explode)
    breaker = pybreaker.CircuitBreaker(
        fail_max=1, reset_timeout=60, listeners=[HealthRecordingListener("polygon")]
    )
    with pytest.raises(pybreaker.CircuitBreakerError):
        breaker.call(_boom)  # listener error must not replace the breaker error
    assert breaker.current_state == "open"


def test_polygon_breaker_has_health_listener():
    assert any(
        isinstance(listener, HealthRecordingListener)
        and listener.provider == "polygon"
        for listener in POLYGON_BREAKER.listeners
    )
```

- [ ] **Step 2: Verify it fails.** `docker-compose exec backend python -m pytest tests/providers/test_breaker_health_listener.py -q`
  Expected: `ImportError: cannot import name 'HealthRecordingListener'`.

- [ ] **Step 3: Implement.** In `backend/app/core/circuit_breakers.py`:
  - Append to the module docstring (before the closing `"""`):

```
POLYGON_BREAKER carries a HealthRecordingListener that mirrors each state change
into the cross-process provider-health record (app/core/provider_health.py, #388)
so a scan running in a different process can see a breaker tripped here.
```

  - After `_non_retryable_provider_error`, add:

```python
class HealthRecordingListener(pybreaker.CircuitBreakerListener):
    """Mirror breaker state changes into the Redis provider-health record.

    The import is lazy because provider_health imports this module (for the
    local POLYGON_BREAKER fast path). Errors are swallowed: a Redis problem
    must never change breaker behaviour.
    """

    def __init__(self, provider: str):
        self.provider = provider

    def state_change(self, cb, old_state, new_state) -> None:
        try:
            from app.core.provider_health import record_breaker_state

            record_breaker_state(self.provider, new_state.name)
        except Exception:
            pass
```

  - Change the `POLYGON_BREAKER` constructor to add `listeners=[HealthRecordingListener("polygon")],`
    after `exclude=[_non_retryable_provider_error],`. Leave `IBKR_BREAKER` unchanged: IBKR is out
    of scope for stock-scan health (ADR-0013).

- [ ] **Step 4: Verify it passes.** Run the new test file (3 passed), then `tests/providers/test_polygon_breaker.py tests/providers/test_circuit_breakers.py` → all still pass.
- [ ] **Step 5: Commit.** `git add backend/app/core/circuit_breakers.py backend/tests/providers/test_breaker_health_listener.py && git commit -m "feat(core): record Polygon breaker state per process (#388)"`

---

## Task 5: Instrument every Polygon REST call in `MassiveDataProvider`

**Files:** `backend/app/providers/massive.py`, `backend/tests/providers/test_massive_health_instrumentation.py` (new)

- [ ] **Step 1: Write the failing test.** Create `backend/tests/providers/test_massive_health_instrumentation.py`:

```python
"""Every Polygon REST call feeds the provider-health record (#388)."""

from unittest.mock import MagicMock

import pytest

from app.core.circuit_breakers import POLYGON_BREAKER
from app.exceptions import ProviderError
from app.providers.massive import MassiveDataProvider


@pytest.fixture(autouse=True)
def _reset_breaker():
    POLYGON_BREAKER.close()
    yield
    POLYGON_BREAKER.close()


@pytest.fixture
def recorded(monkeypatch):
    calls = []
    monkeypatch.setattr(
        "app.core.provider_health.record_provider_call",
        lambda provider, endpoint, ok, latency_s, now=None: calls.append(
            (provider, endpoint, ok)
        ),
    )
    return calls


def _provider():
    p = MassiveDataProvider.__new__(MassiveDataProvider)
    p._client = MagicMock()
    return p


def _bars(p):
    return p.get_bars("AAPL", "minute", 1, "2026-06-01", "2026-06-02")


def test_get_bars_success_recorded(recorded):
    p = _provider()
    p._client.get_aggs.return_value = []
    assert _bars(p) == []
    assert recorded == [("polygon", "aggs", True)]


def test_get_bars_network_failure_recorded(recorded):
    p = _provider()
    p._client.get_aggs.side_effect = ConnectionError("egress blocked")
    with pytest.raises(ProviderError):
        _bars(p)
    assert recorded == [("polygon", "aggs", False)]


def test_plan_limit_error_is_not_a_health_failure(recorded):
    p = _provider()
    p._client.get_aggs.side_effect = Exception('{"status":"NOT_AUTHORIZED"}')
    with pytest.raises(ProviderError):
        _bars(p)
    assert recorded == [("polygon", "aggs", True)]


def test_ticker_details_recorded(recorded):
    p = _provider()
    p._client.get_ticker_details.side_effect = ConnectionError("egress blocked")
    assert p.get_ticker_details("AAPL") == {}
    assert recorded == [("polygon", "ticker_details", False)]


def test_snapshots_recorded(recorded):
    p = _provider()
    p._client.get_snapshot_all.return_value = []
    assert p.get_snapshots() == []
    assert recorded == [("polygon", "snapshot_all", True)]


def test_snapshot_extras_recorded(recorded):
    p = _provider()
    p._client.get_snapshot_all.side_effect = ConnectionError("egress blocked")
    p._client.get_snapshot_ticker.side_effect = ConnectionError("egress blocked")
    assert p.get_snapshot_all() == []
    assert p.get_snapshot_price("AAPL") is None
    assert recorded == [
        ("polygon", "snapshot_all", False),
        ("polygon", "snapshot_ticker", False),
    ]
```

- [ ] **Step 2: Verify it fails.** `docker-compose exec backend python -m pytest tests/providers/test_massive_health_instrumentation.py -q`
  Expected: 6 failed (`recorded == []`).

- [ ] **Step 3: Implement.** In `backend/app/providers/massive.py`:
  - Add the import `from app.core.provider_health import track_provider_call` after `from app.core.metrics import polygon_api_calls_total`.
  - After `_is_plan_limit_error`, add:

```python
def _is_health_failure(exc: BaseException) -> bool:
    """Plan-limit rejections are permanent per request, not provider ill-health."""
    return not _is_plan_limit_error(exc)
```

  - In `_get_bars_impl`, replace

```python
                page = self._client.get_aggs(
                    ticker=symbol.upper(),
                    multiplier=multiplier,
                    timespan=timespan,
                    from_=current_from,
                    to=to_date,
                    adjusted=adjusted,
                    sort=sort,
                    limit=limit,
                )
```

  with the same call wrapped:

```python
                with track_provider_call(
                    "polygon", "aggs", is_failure=_is_health_failure
                ):
                    page = self._client.get_aggs(
                        ticker=symbol.upper(),
                        multiplier=multiplier,
                        timespan=timespan,
                        from_=current_from,
                        to=to_date,
                        adjusted=adjusted,
                        sort=sort,
                        limit=limit,
                    )
```

  - In `_get_ticker_details_impl`, wrap `details = self._client.get_ticker_details(symbol.upper())`
    in `with track_provider_call("polygon", "ticker_details"):`.
  - In `_fetch_snapshots_raw`, change the body to:

```python
        polygon_api_calls_total.labels(endpoint="snapshot_all").inc()
        with track_provider_call("polygon", "snapshot_all"):
            return self._client.get_snapshot_all(market_type="stocks") or []
```

  - In `get_snapshot_all` (inside its `try:`), wrap `return self._client.get_snapshot_all(market_type=market_type) or []` in `with track_provider_call("polygon", "snapshot_all"):`.
  - In `get_snapshot_price` (inside its `try:`), wrap `snap = self._client.get_snapshot_ticker("stocks", symbol)` in `with track_provider_call("polygon", "snapshot_ticker"):`.

- [ ] **Step 4: Verify it passes.** New file → `6 passed`. Regression: `docker-compose exec backend python -m pytest tests/providers -q` → all pass (including `test_get_historical_bars_pagination.py`).
- [ ] **Step 5: Commit.** `git add backend/app/providers/massive.py backend/tests/providers/test_massive_health_instrumentation.py && git commit -m "feat(providers): record Polygon call outcome + latency for health (#388)"`

---

## Task 6: `app/services/provider_degradation.py` — failure-class findings

**Files:** `backend/app/services/provider_degradation.py` (new), `backend/tests/services/test_provider_degradation.py` (new)

- [ ] **Step 1: Write the failing tests.** Create `backend/tests/services/test_provider_degradation.py`:

```python
"""Failure-class → posture mapping for degraded Polygon feeds (#388, ADR-0013)."""

from datetime import date, datetime, timezone
from types import SimpleNamespace

from app.core.provider_health import ProviderHealthSnapshot
from app.services.provider_degradation import (
    LIVE_SUBTYPE,
    apply_provider_gaps,
    assess_premarket_ingestion,
    assess_provider_health,
    is_live_session_day,
    live_provider_gaps,
    severity_level,
)

DAY = date(2026, 6, 2)  # Tuesday, EDT (UTC-4)


def _utc(h, m=0):
    return datetime(2026, 6, 2, h, m, tzinfo=timezone.utc)


def _diag(max_bar=None, evaluated=80, no_pm=20, no_history=5, errors=0):
    return {
        "tickers": evaluated + no_pm + no_history + errors,
        "evaluated": evaluated,
        "no_premarket_data": no_pm,
        "no_history": no_history,
        "errors": errors,
        "max_premarket_bar_ts": max_bar,
    }


# --- is_live_session_day ---------------------------------------------------


def test_live_session_day_after_premarket_open():
    assert is_live_session_day(DAY, _utc(12)) is True  # 08:00 ET


def test_not_live_before_premarket_open():
    assert is_live_session_day(DAY, _utc(7)) is False  # 03:00 ET


def test_not_live_for_other_dates():
    assert is_live_session_day(date(2026, 6, 1), _utc(12)) is False


def test_naive_utc_now_is_accepted():
    assert is_live_session_day(DAY, datetime(2026, 6, 2, 12, 0)) is True


def test_weekday_market_holiday_is_not_a_live_session_day():
    """#388 review A1: Thanksgiving 2026-11-26 is a Thursday, so it survives the
    `weekday() < 5` trading_days filter, but it is a NYSE full close."""
    holiday = date(2026, 11, 26)
    now = datetime(2026, 11, 26, 13, 0, tzinfo=timezone.utc)  # 08:00 EST
    assert is_live_session_day(holiday, now) is True  # no holiday set supplied
    assert is_live_session_day(holiday, now, {holiday}) is False


def test_market_holiday_suppresses_no_fresh_bars_blocker():
    holiday = date(2026, 11, 26)
    now = datetime(2026, 11, 26, 13, 0, tzinfo=timezone.utc)
    diag = {
        "tickers": 500, "evaluated": 0, "no_premarket_data": 500,
        "no_history": 0, "errors": 0, "max_premarket_bar_ts": None,
    }
    assert assess_premarket_ingestion(diag, holiday, now)  # would page today
    assert assess_premarket_ingestion(diag, holiday, now, {holiday}) == []


def test_live_session_boundary_holds_in_est():
    """#388 review A6: the plan otherwise only tests the EDT (UTC-4) offset."""
    winter = date(2026, 1, 6)  # Tuesday, EST (UTC-5)
    assert is_live_session_day(winter, datetime(2026, 1, 6, 8, 0, tzinfo=timezone.utc)) is False
    assert is_live_session_day(winter, datetime(2026, 1, 6, 9, 0, tzinfo=timezone.utc)) is True


# --- assess_provider_health -----------------------------------------------


def test_healthy_snapshot_has_no_findings():
    assert assess_provider_health(ProviderHealthSnapshot(provider="polygon")) == []


def test_breaker_open_is_blocker_and_aborts():
    snap = ProviderHealthSnapshot(
        provider="polygon", breaker_state="open", breaker_open_workers=["w:1"]
    )
    (f,) = assess_provider_health(snap)
    assert (f.reason, f.severity, f.abort) == ("breaker_open", "blocker", True)
    assert f.detail["breaker_open_workers"] == ["w:1"]


def test_error_rate_over_threshold_is_blocker_and_aborts():
    snap = ProviderHealthSnapshot(
        provider="polygon",
        calls_error_window=40,
        errors_error_window=20,
        error_rate=0.5,
    )
    (f,) = assess_provider_health(snap)
    assert (f.reason, f.severity, f.abort) == ("error_rate", "blocker", True)
    assert f.detail["error_rate"] == 0.5


def test_error_rate_below_min_calls_ignored():
    snap = ProviderHealthSnapshot(
        provider="polygon", calls_error_window=2, errors_error_window=2, error_rate=1.0
    )
    assert assess_provider_health(snap) == []


def test_latency_is_warning_and_continues():
    snap = ProviderHealthSnapshot(provider="polygon", latency_p95_seconds=10.0)
    (f,) = assess_provider_health(snap)
    assert (f.reason, f.severity, f.abort) == ("latency", "warning", False)


# --- assess_premarket_ingestion -------------------------------------------


def test_historical_day_never_assessed():
    assert assess_premarket_ingestion(_diag(), date(2026, 6, 1), _utc(12)) == []


def test_too_early_to_judge():
    assert assess_premarket_ingestion(_diag(), DAY, _utc(8, 5)) == []  # 04:05 ET


def test_no_premarket_bars_is_blocker():
    (f,) = assess_premarket_ingestion(_diag(max_bar=None), DAY, _utc(12))
    assert (f.reason, f.severity, f.abort) == (
        "no_fresh_premarket_bars",
        "blocker",
        False,
    )


def test_stale_premarket_bars_is_blocker():
    bar = _utc(11, 40).isoformat()  # 07:40 ET; now 08:00 ET → 20 min old
    (f,) = assess_premarket_ingestion(_diag(max_bar=bar), DAY, _utc(12))
    assert (f.reason, f.severity) == ("stale_premarket_bars", "blocker")
    assert f.detail["minutes_since_last_bar"] == 20.0


def test_fresh_bars_and_good_coverage_have_no_findings():
    bar = _utc(11, 58).isoformat()
    assert assess_premarket_ingestion(_diag(max_bar=bar), DAY, _utc(12)) == []


def test_staleness_not_checked_after_regular_open():
    bar = _utc(13, 29).isoformat()  # 09:29 ET; now 11:00 ET
    assert assess_premarket_ingestion(_diag(max_bar=bar), DAY, _utc(15)) == []


def test_partial_coverage_is_warning_with_ratio():
    bar = _utc(11, 58).isoformat()
    (f,) = assess_premarket_ingestion(
        _diag(max_bar=bar, evaluated=30, no_pm=70), DAY, _utc(12)
    )
    assert (f.reason, f.severity, f.abort) == ("partial_coverage", "warning", False)
    assert f.detail["coverage_ratio"] == 0.3


# --- apply_provider_gaps / live_provider_gaps / severity_level ------------


def _trusted_gate():
    return {
        "schema_version": "quality_gate.v1",
        "policy": "advisory",
        "verdict": "trusted",
        "trusted": True,
        "scope": {"universe_id": 1, "scanner_type": "pre_market_volume_spike"},
        "score": 95.0,
        "grade": "A",
        "issues": [
            {
                "code": "provider_gap",
                "severity": "warning",
                "message": "historical",
                "detail": {"subtype": "structural"},
            }
        ],
        "warnings": [],
        "generated_at": "2026-06-02T11:00:00",
    }


def _findings():
    snap = ProviderHealthSnapshot(provider="polygon", latency_p95_seconds=10.0)
    return assess_provider_health(snap)


def test_apply_appends_live_issue_and_downgrades_verdict():
    run = SimpleNamespace(quality_gate=_trusted_gate(), data_degraded=False)
    apply_provider_gaps(
        run, _findings(), universe_id=1, scanner_type="pre_market_volume_spike",
        worker="celery:9",
    )
    assert run.data_degraded is True
    assert run.quality_gate["verdict"] == "warning"
    assert run.quality_gate["trusted"] is False
    live = [i for i in run.quality_gate["issues"] if i["detail"].get("subtype") == LIVE_SUBTYPE]
    assert len(live) == 1
    assert live[0]["code"] == "provider_gap"
    assert live[0]["detail"]["provider"] == "polygon"
    assert live[0]["detail"]["reason"] == "latency"
    assert live[0]["detail"]["worker"] == "celery:9"
    # the pre-existing historical provider_gap issue is preserved
    assert any(i["detail"].get("subtype") == "structural" for i in run.quality_gate["issues"])


def test_apply_is_idempotent_for_live_issues():
    run = SimpleNamespace(quality_gate=_trusted_gate(), data_degraded=False)
    for _ in range(2):
        apply_provider_gaps(
            run, _findings(), universe_id=1, scanner_type="pre_market_volume_spike",
            worker="w",
        )
    assert len(live_provider_gaps(run.quality_gate)) == 1


def test_apply_creates_assessment_when_gate_missing():
    run = SimpleNamespace(quality_gate=None, data_degraded=None)
    apply_provider_gaps(
        run, _findings(), universe_id=7, scanner_type="pre_market_volume_spike",
        worker="w",
    )
    assert run.quality_gate["schema_version"] == "quality_gate.v1"
    assert run.quality_gate["scope"]["universe_id"] == 7
    assert run.quality_gate["policy"] == "advisory"
    assert run.data_degraded is True


def test_apply_with_no_findings_is_noop():
    run = SimpleNamespace(quality_gate=None, data_degraded=False)
    apply_provider_gaps(run, [], universe_id=1, scanner_type="x", worker="w")
    assert run.quality_gate is None and run.data_degraded is False


def test_live_provider_gaps_filters_by_subtype():
    assert live_provider_gaps(None) == []
    assert live_provider_gaps(_trusted_gate()) == []


def test_severity_level():
    assert severity_level([]) == 0
    assert severity_level(_findings()) == 1
    snap = ProviderHealthSnapshot(provider="polygon", breaker_state="open")
    assert severity_level(assess_provider_health(snap)) == 2
```

- [ ] **Step 2: Verify it fails.** `docker-compose exec backend python -m pytest tests/services/test_provider_degradation.py -q`
  Expected: `ModuleNotFoundError: No module named 'app.services.provider_degradation'`.

- [ ] **Step 3: Implement.** Create `backend/app/services/provider_degradation.py`:

```python
"""
Degraded-feed assessment for pre-market scans (#388, ADR-0013).

Pure functions (no DB, no Redis) that map a ProviderHealthSnapshot and the
pre-market scan's per-day ingestion diagnostics to provider_gap findings, plus
apply_provider_gaps(), which folds findings into ScannerRun.quality_gate and
ScannerRun.data_degraded. Posture per failure class (ADR-0013):

  breaker open / error rate over threshold -> blocker, stop the scan
  elevated latency                         -> warning, continue
  no fresh pre-market minute bars          -> blocker, complete + mark (+ page)
  partial pre-market coverage              -> warning, complete + mark

Live findings carry detail.subtype == "live_degradation" so they are
distinguishable from the historical provider_gap evidence (absent / partial /
structural) that QualityGateService already emits from UniverseQualityReport.
"""

import json
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from typing import Any, Dict, List, Optional, Set
from zoneinfo import ZoneInfo

from app.core.config import settings
from app.core.provider_health import ProviderHealthSnapshot
from app.schemas.quality_gate import (
    QualityGateAssessment,
    QualityGateIssue,
    QualityGatePolicy,
    QualityGateScope,
    QualityGateVerdict,
    QualityIssueCode,
)
from app.services.quality_gate import _derive_verdict
from app.utils.time import ensure_utc, utc_now

_ET = ZoneInfo("America/New_York")
_PREMARKET_OPEN = time(4, 0)
_REGULAR_OPEN = time(9, 30)
LIVE_SUBTYPE = "live_degradation"


@dataclass(frozen=True)
class ProviderGapFinding:
    severity: str  # "blocker" | "warning"
    reason: str
    message: str
    abort: bool = False
    detail: Dict[str, Any] = field(default_factory=dict)

    def to_issue(self, provider: str, worker: Optional[str]) -> QualityGateIssue:
        return QualityGateIssue(
            code=QualityIssueCode.provider_gap,
            severity=self.severity,
            message=self.message,
            detail={
                "subtype": LIVE_SUBTYPE,
                "provider": provider,
                "reason": self.reason,
                "worker": worker,
                **self.detail,
            },
        )


def is_live_session_day(
    event_date: date,
    now_utc: datetime,
    market_holidays: Optional[Set[date]] = None,
) -> bool:
    """True when event_date is today's ET *trading* session and pre-market has opened.

    ``market_holidays`` is the NYSE full-close date set. It must be supplied by
    callers that act on the result: _run_universe_scan_logic builds
    ``trading_days`` with a ``weekday() < 5`` filter only, so a weekday NYSE
    holiday reaches here. On such a day there are legitimately no pre-market
    minute bars, and without this guard assess_premarket_ingestion would emit a
    blocker `no_fresh_premarket_bars` finding and page (#388 review finding A1).
    """
    now_et = ensure_utc(now_utc).astimezone(_ET)
    if event_date != now_et.date() or now_et.time() < _PREMARKET_OPEN:
        return False
    return event_date not in (market_holidays or set())


def assess_provider_health(snapshot: ProviderHealthSnapshot) -> List[ProviderGapFinding]:
    findings: List[ProviderGapFinding] = []
    if snapshot.breaker_state == "open":
        where = ", ".join(snapshot.breaker_open_workers) or "a worker"
        findings.append(
            ProviderGapFinding(
                severity="blocker",
                reason="breaker_open",
                message=f"Polygon circuit breaker open ({where}) — provider unavailable",
                abort=True,
                detail={"breaker_open_workers": list(snapshot.breaker_open_workers)},
            )
        )
    if (
        snapshot.calls_error_window >= settings.PROVIDER_HEALTH_MIN_CALLS
        and snapshot.error_rate >= settings.POLYGON_HEALTH_ERROR_RATE_THRESHOLD
    ):
        findings.append(
            ProviderGapFinding(
                severity="blocker",
                reason="error_rate",
                message=(
                    f"Polygon error rate {snapshot.error_rate:.0%} over the last "
                    f"{settings.PROVIDER_HEALTH_ERROR_WINDOW_SECONDS // 60} min "
                    f"({snapshot.errors_error_window}/{snapshot.calls_error_window} calls)"
                ),
                abort=True,
                detail={
                    "error_rate": round(snapshot.error_rate, 4),
                    "calls": snapshot.calls_error_window,
                },
            )
        )
    if (
        snapshot.latency_p95_seconds is not None
        and snapshot.latency_p95_seconds
        >= settings.POLYGON_HEALTH_LATENCY_P95_THRESHOLD_SECONDS
    ):
        findings.append(
            ProviderGapFinding(
                severity="warning",
                reason="latency",
                message=(
                    f"Polygon p95 latency {snapshot.latency_p95_seconds:.1f}s is "
                    "elevated — data may be arriving late"
                ),
                detail={"latency_p95_seconds": snapshot.latency_p95_seconds},
            )
        )
    return findings


def assess_premarket_ingestion(
    diagnostics: Dict[str, Any],
    event_date: date,
    now_utc: datetime,
    market_holidays: Optional[Set[date]] = None,
) -> List[ProviderGapFinding]:
    """Universe-wide ingestion health from run_pre_market_scan diagnostics_out."""
    if not is_live_session_day(event_date, now_utc, market_holidays):
        return []
    now_aware = ensure_utc(now_utc)
    now_et = now_aware.astimezone(_ET)
    staleness = timedelta(minutes=settings.PREMARKET_BAR_STALENESS_MINUTES)
    pm_open_et = datetime.combine(event_date, _PREMARKET_OPEN, tzinfo=_ET)
    if now_et < pm_open_et + staleness:
        return []  # too early in the session to judge ingestion

    findings: List[ProviderGapFinding] = []
    max_bar_iso = diagnostics.get("max_premarket_bar_ts")
    if max_bar_iso is None:
        findings.append(
            ProviderGapFinding(
                severity="blocker",
                reason="no_fresh_premarket_bars",
                message=(
                    f"No pre-market minute bars ingested for {event_date.isoformat()} "
                    "— Polygon ingestion appears stalled"
                ),
            )
        )
    else:
        max_bar = ensure_utc(datetime.fromisoformat(max_bar_iso))
        regular_open_et = datetime.combine(event_date, _REGULAR_OPEN, tzinfo=_ET)
        age = now_aware - max_bar
        if now_et < regular_open_et and age > staleness:
            minutes = round(age.total_seconds() / 60, 1)
            findings.append(
                ProviderGapFinding(
                    severity="blocker",
                    reason="stale_premarket_bars",
                    message=(
                        f"Freshest pre-market minute bar is {minutes:g} min old "
                        "— Polygon ingestion appears stalled"
                    ),
                    detail={
                        "max_premarket_bar_ts": max_bar_iso,
                        "minutes_since_last_bar": minutes,
                    },
                )
            )

    evaluated = int(diagnostics.get("evaluated", 0))
    no_pm = int(diagnostics.get("no_premarket_data", 0))
    evaluable = evaluated + no_pm
    if max_bar_iso is not None and evaluable > 0:
        coverage_ratio = round(evaluated / evaluable, 4)
        if coverage_ratio < settings.PREMARKET_MIN_COVERAGE_RATIO:
            findings.append(
                ProviderGapFinding(
                    severity="warning",
                    reason="partial_coverage",
                    message=(
                        f"Only {coverage_ratio:.0%} of tickers have pre-market data "
                        f"({evaluated}/{evaluable})"
                    ),
                    detail={
                        "coverage_ratio": coverage_ratio,
                        "tickers_with_premarket_data": evaluated,
                        "evaluable_tickers": evaluable,
                        "no_history": int(diagnostics.get("no_history", 0)),
                    },
                )
            )
    return findings


def severity_level(findings: List[ProviderGapFinding]) -> int:
    """0 = none, 1 = warning, 2 = blocker (scan_provider_gap_severity gauge)."""
    if any(f.severity == "blocker" for f in findings):
        return 2
    return 1 if findings else 0


def _is_live_issue(issue: QualityGateIssue) -> bool:
    return (
        issue.code == QualityIssueCode.provider_gap
        and issue.detail.get("subtype") == LIVE_SUBTYPE
    )


def apply_provider_gaps(
    run: Any,
    findings: List[ProviderGapFinding],
    *,
    universe_id: Optional[int],
    scanner_type: str,
    worker: Optional[str],
    provider: str = "polygon",
) -> None:
    """Fold live findings into run.quality_gate (re-deriving verdict) and set data_degraded.

    Re-applying replaces earlier live issues, so the call is idempotent.
    """
    if not findings:
        return
    existing = run.quality_gate if isinstance(run.quality_gate, dict) else None
    if existing is not None:
        assessment = QualityGateAssessment.model_validate(existing)
    else:
        assessment = QualityGateAssessment(
            policy=QualityGatePolicy.advisory,
            verdict=QualityGateVerdict.trusted,
            trusted=True,
            scope=QualityGateScope(universe_id=universe_id, scanner_type=scanner_type),
            generated_at=utc_now(),
        )
    issues = [i for i in assessment.issues if not _is_live_issue(i)]
    issues += [f.to_issue(provider, worker) for f in findings]
    verdict = _derive_verdict(issues, assessment.policy)
    updated = assessment.model_copy(
        update={
            "issues": issues,
            "warnings": [i for i in issues if i.severity == "warning"],
            "verdict": verdict,
            "trusted": verdict == QualityGateVerdict.trusted,
        }
    )
    # Same serialisation as the scan-start assessment in tasks/scanning.py.
    run.quality_gate = json.loads(json.dumps(updated.model_dump(), default=str))
    run.data_degraded = True


def live_provider_gaps(quality_gate: Optional[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """API projection: the live-degradation provider_gap issues of a stored gate."""
    if not isinstance(quality_gate, dict):
        return []
    return [
        issue
        for issue in quality_gate.get("issues") or []
        if issue.get("code") == QualityIssueCode.provider_gap.value
        and (issue.get("detail") or {}).get("subtype") == LIVE_SUBTYPE
    ]
```

- [ ] **Step 4: Verify it passes.** Same command. Expected: `22 passed`.
- [ ] **Step 5: Commit.** `git add backend/app/services/provider_degradation.py backend/tests/services/test_provider_degradation.py && git commit -m "feat(services): provider-gap failure-class findings (#388)"`

---

## Task 7: Pre-market scan ingestion diagnostics + orchestrator opt-in

**Files:** `backend/app/services/scan_orchestrator.py`, `backend/app/services/pre_market_scan.py`,
`backend/tests/services/test_scan_orchestrator.py`, `backend/tests/services/test_pre_market_scan_module.py`

- [ ] **Step 1: Write the failing tests.**
  Append to `backend/tests/services/test_scan_orchestrator.py`:

```python


def test_run_passes_diagnostics_out_only_when_supported():
    fn = AsyncMock(return_value=[])
    register(
        ScannerDescriptor(
            key="diag_scan",
            display_name="D",
            description="d",
            run=fn,
            supports_diagnostics=True,
        )
    )
    today = date(2026, 5, 23)
    diag: dict = {}
    asyncio.run(run("diag_scan", ["AAPL"], db=None, event_date=today, diagnostics_out=diag))
    fn.assert_awaited_once_with(
        ["AAPL"], None, today, scanner_run=None, gate_metadata=None, diagnostics_out=diag
    )


def test_run_omits_diagnostics_out_for_unsupported_scanner():
    fn = AsyncMock(return_value=[])
    register(ScannerDescriptor(key="plain_scan", display_name="P", description="d", run=fn))
    today = date(2026, 5, 23)
    asyncio.run(run("plain_scan", ["AAPL"], db=None, event_date=today, diagnostics_out={}))
    fn.assert_awaited_once_with(["AAPL"], None, today, scanner_run=None, gate_metadata=None)
```

  Append to `backend/tests/services/test_pre_market_scan_module.py`:

```python


def test_pre_market_scan_diagnostics_buckets(db):
    """#388: per-ticker outcome buckets + freshest pre-market bar → diagnostics_out."""
    from app.services.pre_market_scan import run_pre_market_scan

    event_date = date(2025, 3, 10)  # EDT
    _ET = ZoneInfo("America/New_York")
    base_et = datetime.combine(event_date, datetime.min.time(), tzinfo=_ET)

    def _daily(ticker, n):
        for i in range(n):
            db.add(
                _make_db_daily_bar(
                    ticker,
                    (base_et - timedelta(days=n - i))
                    .astimezone(timezone.utc)
                    .replace(tzinfo=None),
                )
            )

    _daily("DGA", 25)  # evaluated (has pre-market volume, no spike)
    _daily("DGB", 25)  # no_premarket_data
    _daily("DGC", 5)  # no_history
    pm_ts = datetime.combine(event_date, time(7, 0), tzinfo=_ET)
    db.add(
        _make_db_pm_bar(
            "DGA", pm_ts.astimezone(timezone.utc).replace(tzinfo=None), volume=1_000
        )
    )
    db.flush()

    diag: dict = {}
    with patch.object(
        ScannerService, "_get_batch_enrichment_data", return_value=({}, {}, {})
    ):
        results = asyncio.run(
            run_pre_market_scan(
                ["DGA", "DGB", "DGC"], db, event_date=event_date, diagnostics_out=diag
            )
        )

    assert results == []
    assert diag["tickers"] == 3
    assert diag["evaluated"] == 1
    assert diag["no_premarket_data"] == 1
    assert diag["no_history"] == 1
    assert diag["errors"] == 0
    assert diag["max_premarket_bar_ts"] == "2025-03-10T11:00:00+00:00"
```

- [ ] **Step 2: Verify they fail.**
  `docker-compose exec backend python -m pytest tests/services/test_scan_orchestrator.py tests/services/test_pre_market_scan_module.py -q`
  Expected: `TypeError: ScannerDescriptor.__init__() got an unexpected keyword argument 'supports_diagnostics'` and
  `TypeError: run_pre_market_scan() got an unexpected keyword argument 'diagnostics_out'`.

- [ ] **Step 3: Implement the orchestrator.** In `backend/app/services/scan_orchestrator.py`:
  - Add a field to `ScannerDescriptor` after `default_parameters`:

```python
    # True when run() accepts diagnostics_out= (per-ticker outcome buckets, #388).
    supports_diagnostics: bool = False
```

  - Replace `run()` with:

```python
async def run(
    scanner_type: str,
    tickers: list[str],
    db: Any,
    event_date: date,
    scanner_run: Optional[Any] = None,
    gate_metadata: Optional[Any] = None,
    diagnostics_out: Optional[dict] = None,
) -> list[dict]:
    descriptor = _REGISTRY.get(scanner_type)
    if descriptor is None:
        raise ValueError(
            f"Unknown scanner type: {scanner_type!r}. "
            f"Registered: {[d.key for d in _REGISTRY.get_all()]}"
        )
    kwargs: dict[str, Any] = {"scanner_run": scanner_run, "gate_metadata": gate_metadata}
    if diagnostics_out is not None and descriptor.supports_diagnostics:
        kwargs["diagnostics_out"] = diagnostics_out
    return await descriptor.run(tickers, db, event_date, **kwargs)
```

- [ ] **Step 4: Implement the pre-market scan.** In `backend/app/services/pre_market_scan.py`:
  - Add the parameter `diagnostics_out: Optional[Dict[str, Any]] = None,` to
    `run_pre_market_scan` after `gate_metadata`. Extend its docstring:

```python
    """Run extended hours volume spike scanner using DB aggregates.

    When ``diagnostics_out`` is supplied it is populated with per-ticker outcome
    buckets (evaluated / no_premarket_data / no_history / errors), the ticker
    count, and ``max_premarket_bar_ts`` (ISO-8601 UTC of the freshest pre-market
    minute bar, or None) — the universe-wide ingestion-health signal (#388).
    """
```

  - Directly after `failed: List[Dict[str, Any]] = []` (before `for ticker in tickers:`) add:

```python
        # Outcome buckets (house style: liquidity_hunt / pocket_pivot). Kept apart
        # from `failed`, which drives scan_failed_tickers_ratio and its alert —
        # "no data yet" is not an error (#388, ADR-0013).
        counts = {"evaluated": 0, "no_premarket_data": 0, "no_history": 0, "errors": 0}
```

  - Directly **after** the `raw = _detect(...)` call and before `if raw is not None:`, add the
    following. Placing it after `_detect` means a ticker whose evaluation raises is counted only
    under `errors`, never twice:

```python
                if len(daily_bars) < 20:
                    counts["no_history"] += 1
                elif pre_market_volume <= 0:
                    counts["no_premarket_data"] += 1
                else:
                    counts["evaluated"] += 1
```

  - At the start of the `except (ScanError, DataFetchError, ProviderError) as e:` block, add `counts["errors"] += 1`.
  - Directly after the existing `if _max_bar_ts is not None and isinstance(_max_bar_ts, datetime): ... .observe(...)` block, and before `return results`, add:

```python
        if diagnostics_out is not None:
            diagnostics_out.update(
                {
                    "tickers": len(tickers),
                    **counts,
                    "max_premarket_bar_ts": (
                        ensure_utc(_max_bar_ts).isoformat()
                        if isinstance(_max_bar_ts, datetime)
                        else None
                    ),
                }
            )
```

  - Update the `_run` adapter:

```python
async def _run(
    tickers: list[str],
    db: Any,
    event_date: date,
    scanner_run: Optional[Any] = None,
    gate_metadata: Optional[Any] = None,
    diagnostics_out: Optional[dict] = None,
) -> list[dict]:
    return await run_pre_market_scan(
        tickers,
        db,
        event_date=event_date,
        scanner_run=scanner_run,
        gate_metadata=gate_metadata,
        diagnostics_out=diagnostics_out,
    )
```

  - Add `supports_diagnostics=True,` to the `register(ScannerDescriptor(...))` call after `default_parameters={},`.

- [ ] **Step 5: Verify they pass.** Same command → all pass, including the existing `test_run_dispatches_to_registered_fn`
  (unchanged exact-kwargs assertion) and `test_pre_market_scan_total_failure_does_not_mark_success`.
- [ ] **Step 6: Commit.** `git add backend/app/services/scan_orchestrator.py backend/app/services/pre_market_scan.py backend/tests/services/test_scan_orchestrator.py backend/tests/services/test_pre_market_scan_module.py && git commit -m "feat(scanner): pre-market ingestion diagnostics via diagnostics_out (#388)"`

---

## Task 8: Wire degradation into `_run_universe_scan_logic`

**Files:** `backend/app/tasks/scanning.py`, `backend/tests/tasks/test_scanning_degradation.py` (new)

- [ ] **Step 1: Write the failing tests.** Create `backend/tests/tasks/test_scanning_degradation.py`:

```python
"""_run_universe_scan_logic degraded-feed behaviour (#388, ADR-0013)."""

from datetime import date, datetime
from unittest.mock import MagicMock, patch

from prometheus_client import REGISTRY

from app.core.provider_health import ProviderHealthSnapshot
from tests.tasks.test_scanning_tasks import (
    _make_assessment,
    _make_db,
    _make_run,
    _make_ticker,
)

DAY = date(2026, 6, 2)
LIVE_NOW = datetime(2026, 6, 2, 12, 0)  # naive UTC = 08:00 EDT


def _healthy():
    return ProviderHealthSnapshot(provider="polygon")


def _breaker_open():
    return ProviderHealthSnapshot(
        provider="polygon", breaker_state="open", breaker_open_workers=["celery:1"]
    )


def _fake_orchestrator(diag_payload, calls=None):
    async def fake_run(
        scanner_type, tickers, db, event_date, scanner_run=None,
        gate_metadata=None, diagnostics_out=None,
    ):
        if calls is not None:
            calls.append(event_date)
        if diagnostics_out is not None and diag_payload is not None:
            diagnostics_out.update(diag_payload)
        return []

    return fake_run


def _run(health, diag_payload, start=DAY, end=DAY, now=LIVE_NOW, calls=None):
    from app.tasks.scanning import _run_universe_scan_logic

    run = _make_run("scan-deg-01")
    run.quality_gate = None
    published = []
    db = _make_db(run=run, tickers=[_make_ticker("AAPL")])
    health_mock = MagicMock(side_effect=lambda *a, **k: health())
    with (
        patch(
            "app.services.quality_gate.QualityGateService.assess",
            return_value=_make_assessment("trusted"),
        ),
        patch("app.tasks.scanning._compute_data_degraded", return_value=False),
        patch("app.tasks.scanning.utc_now", return_value=now),
        patch("app.tasks.scanning.get_provider_health", health_mock),
        patch(
            "app.services.scan_orchestrator.run",
            _fake_orchestrator(diag_payload, calls),
        ),
    ):
        _run_universe_scan_logic(
            scan_id="scan-deg-01",
            scanner_type="pre_market_volume_spike",
            universe_id=1,
            start=start,
            end=end,
            db=db,
            publish=published.append,
            is_cancelled=lambda: False,
            task_id="task-deg",
        )
    return run, published, health_mock


def _live_issues(run):
    return [
        i for i in run.quality_gate["issues"]
        if i["detail"].get("subtype") == "live_degradation"
    ]


def _gauge():
    return REGISTRY.get_sample_value(
        "scan_provider_gap_severity", {"scanner_type": "pre_market_volume_spike"}
    )


def test_breaker_open_before_live_day_stops_scan():
    calls = []
    run, published, _ = _run(_breaker_open, None, calls=calls)
    assert calls == []  # the live day was never scanned
    assert run.status == "failed"
    assert "Polygon degraded" in run.error_message
    assert run.data_degraded is True
    (issue,) = _live_issues(run)
    assert issue["severity"] == "blocker"
    assert issue["detail"]["reason"] == "breaker_open"
    assert issue["detail"]["breaker_open_workers"] == ["celery:1"]
    assert issue["detail"]["worker"]  # process that observed it
    assert published[-1]["type"] == "failed"
    assert not any(p.get("type") == "completed" for p in published)
    assert _gauge() == 2


def test_empty_but_green_completes_but_is_marked_blocker():
    diag = {
        "tickers": 1, "evaluated": 0, "no_premarket_data": 1, "no_history": 0,
        "errors": 0, "max_premarket_bar_ts": None,
    }
    run, published, _ = _run(_healthy, diag)
    assert run.status == "completed"
    assert run.data_degraded is True
    (issue,) = _live_issues(run)
    assert (issue["severity"], issue["detail"]["reason"]) == (
        "blocker", "no_fresh_premarket_bars",
    )
    completed = [p for p in published if p.get("type") == "completed"][-1]
    assert completed["data_degraded"] is True
    assert _gauge() == 2


def test_partial_coverage_marks_warning_with_ratio():
    diag = {
        "tickers": 10, "evaluated": 2, "no_premarket_data": 8, "no_history": 0,
        "errors": 0, "max_premarket_bar_ts": "2026-06-02T11:58:00+00:00",
    }
    run, _, _ = _run(_healthy, diag)
    assert run.status == "completed"
    (issue,) = _live_issues(run)
    assert issue["severity"] == "warning"
    assert issue["detail"]["coverage_ratio"] == 0.2
    assert _gauge() == 1


def test_healthy_live_scan_stays_clean():
    diag = {
        "tickers": 10, "evaluated": 9, "no_premarket_data": 1, "no_history": 0,
        "errors": 0, "max_premarket_bar_ts": "2026-06-02T11:58:00+00:00",
    }
    run, published, _ = _run(_healthy, diag)
    assert run.status == "completed"
    assert run.data_degraded is False
    assert _live_issues(run) == []
    assert [p for p in published if p.get("type") == "completed"][-1]["data_degraded"] is False
    assert _gauge() == 0


def test_breaker_opening_mid_scan_fails_run_at_completion():
    states = iter([_healthy(), _breaker_open()])
    diag = {
        "tickers": 1, "evaluated": 1, "no_premarket_data": 0, "no_history": 0,
        "errors": 0, "max_premarket_bar_ts": "2026-06-02T11:58:00+00:00",
    }
    run, published, _ = _run(lambda: next(states), diag)
    assert run.status == "failed"
    assert "at completion" in run.error_message
    assert run.data_degraded is True
    assert published[-1]["type"] == "failed"


def test_historical_range_never_consults_provider_health():
    run, published, health_mock = _run(
        _breaker_open, None, start=date(2026, 5, 26), end=date(2026, 5, 29)
    )
    health_mock.assert_not_called()
    assert run.status == "completed"
    assert run.data_degraded is False


def test_findings_record_the_phase_they_were_raised_in():
    """#388 review A3: on-call must distinguish "never scanned" from
    "scanned, then failed at completion"."""
    run, _, _ = _run(_breaker_open, None)
    (issue,) = _live_issues(run)
    assert issue["detail"]["phase"] == "before_day"

    states = iter([_healthy(), _breaker_open()])
    diag = {
        "tickers": 1, "evaluated": 1, "no_premarket_data": 0, "no_history": 0,
        "errors": 0, "max_premarket_bar_ts": "2026-06-02T11:58:00+00:00",
    }
    run2, _, _ = _run(lambda: next(states), diag)
    (issue2,) = _live_issues(run2)
    assert issue2["detail"]["phase"] == "at_completion"
    assert run2.events_detected == 0  # events, if any, stay recorded on the run


def test_live_day_run_clears_a_latched_severity_gauge():
    """#388 review A2: a fresh live-day run must not inherit yesterday's blocker."""
    from app.core.metrics import scan_provider_gap_severity

    scan_provider_gap_severity.labels(
        scanner_type="pre_market_volume_spike"
    ).set(2)
    diag = {
        "tickers": 10, "evaluated": 9, "no_premarket_data": 1, "no_history": 0,
        "errors": 0, "max_premarket_bar_ts": "2026-06-02T11:58:00+00:00",
    }
    _run(_healthy, diag)
    assert _gauge() == 0


def test_weekday_market_holiday_does_not_page():
    """#388 review A1: no pre-market bars on a NYSE full close is not an outage."""
    diag = {
        "tickers": 10, "evaluated": 0, "no_premarket_data": 10, "no_history": 0,
        "errors": 0, "max_premarket_bar_ts": None,
    }
    holiday = date(2026, 11, 26)  # Thursday, NYSE full close
    run, _, _ = _run(
        _healthy, diag, start=holiday, end=holiday,
        now=datetime(2026, 11, 26, 13, 0),
    )
    assert run.status == "completed"
    assert run.data_degraded is False
    assert _gauge() == 0
```

  `_make_db` must return the holiday row for `2026-11-26` from the
  `db.query(MarketHoliday.date)` call for the last test; extend the `_make_db` helper stub in
  `tests/tasks/test_scanning_tasks.py`, or patch
  `app.tasks.scanning.MarketHoliday` per test, whichever keeps the existing helper simplest.

- [ ] **Step 2: Verify it fails.** `docker-compose exec backend python -m pytest tests/tasks/test_scanning_degradation.py -q`
  Expected: failures with `AttributeError: <module 'app.tasks.scanning'> does not have the attribute 'get_provider_health'`.

- [ ] **Step 3: Implement.** In `backend/app/tasks/scanning.py`:
  - Replace the metrics import and add the new imports (keep alphabetical grouping):

```python
from app.core.metrics import (
    celery_task_duration_seconds,
    celery_tasks_total,
    scan_provider_gap_severity,
)
from app.core.provider_health import get_provider_health, worker_id
```

  `ProviderGapFinding` is a frozen dataclass, so add `from dataclasses import replace` to the
  stdlib import block at the top of the file (#388 review A3).

```python
```

  and, after `from app.services.quality_gate import quality_gate_service`:

```python
from app.services.provider_degradation import (
    apply_provider_gaps,
    assess_premarket_ingestion,
    assess_provider_health,
    is_live_session_day,
    severity_level,
)
```

  - Add this helper directly above `def _run_universe_scan_logic(`:

```python
def _stop_for_provider_degradation(
    db: Session,
    run,
    findings,
    *,
    universe_id: int,
    scanner_type: str,
    started_at: datetime,
    events_total: int,
    publish,
    phase: str,
) -> None:
    """ADR-0013: breaker open / error rate → stop, mark degraded, never 'completed'.

    #388 review A3: ``phase`` is recorded on every finding as ``detail.phase``.
    A "before scanning <day>" abort means no data was read for that day. An
    "at completion" abort means the days WERE scanned and their events are
    already persisted against this run -- the run is marked ``failed`` because
    ADR-0013 forbids presenting it as a clean success, not because the events
    are invalid. On-call and the UI need to tell these apart.
    """
    phase_key = "at_completion" if phase == "at completion" else "before_day"
    findings = [
        replace(f, detail={**f.detail, "phase": phase_key}) for f in findings
    ]
    apply_provider_gaps(
        run,
        findings,
        universe_id=universe_id,
        scanner_type=scanner_type,
        worker=worker_id(),
    )
    reasons = "; ".join(f.message for f in findings if f.abort)
    run.status = "failed"
    run.error_message = f"Scan stopped {phase} — Polygon degraded: {reasons}"
    run.events_detected = events_total
    run.execution_time_ms = int((utc_now() - started_at).total_seconds() * 1000)
    db.commit()
    scan_provider_gap_severity.labels(scanner_type=scanner_type).set(2)
    logger.error("run_universe_scan %s: %s", run.uuid, run.error_message)
    publish({"type": "failed", "error": run.error_message, "data_degraded": True})
```

  - In `_run_universe_scan_logic`, directly after `events_total = 0`, add `day_diagnostics: dict = {}`.
  - **(#388 review A1)** `trading_days` is built with a `weekday() < 5` filter only, so weekday
    NYSE holidays reach the live-day checks and would produce a false blocker plus a page. Resolve
    the holiday set once per scan, right after `day_diagnostics`, using the same pattern as
    `services/quality_gate.py:559-569`. Add `from app.models.market_holiday import MarketHoliday`
    to the imports.

```python
    # #388/ADR-0013: a weekday NYSE full close has no pre-market bars by design;
    # it must not read as a Polygon ingestion stall. Resolved once per scan.
    market_holidays = {
        row.date
        for row in db.query(MarketHoliday.date).filter(
            MarketHoliday.exchange == "NYSE",
            MarketHoliday.event_type == "full_close",
        )
    }
```

  - **(#388 review A2)** Immediately before the `for i, day in ...` loop, clear the severity gauge
    for this scanner whenever this run covers a live session day, so a previously-degraded run
    stops paging as soon as a fresh live-day run starts. Without this the gauge latches (see the
    completion block below).

```python
    if any(is_live_session_day(d, utc_now(), market_holidays) for d in trading_days):
        scan_provider_gap_severity.labels(scanner_type=scanner_type).set(0)
```

  - Inside the `for i, day in enumerate(trading_days, start=1):` loop, directly after the
    `if is_cancelled(): ... return` block and before `publish({"type": "day_started", ...})`, add:

```python
        if is_live_session_day(day, utc_now(), market_holidays):
            pre_findings = assess_provider_health(get_provider_health("polygon"))
            if any(f.abort for f in pre_findings):
                _stop_for_provider_degradation(
                    db,
                    run,
                    pre_findings,
                    universe_id=universe_id,
                    scanner_type=scanner_type,
                    started_at=started_at,
                    events_total=events_total,
                    publish=publish,
                    phase=f"before scanning {day.isoformat()}",
                )
                return
```

  - Replace the `try: day_events = asyncio.run(_orchestrator.run(...))` call so that it passes a per-day diagnostics dict:

```python
        day_diag: dict = {}
        day_diagnostics[day] = day_diag
        try:
            day_events = asyncio.run(
                _orchestrator.run(
                    scanner_type,
                    tickers,
                    db=db,
                    event_date=day,
                    scanner_run=run,
                    gate_metadata=gate_metadata,
                    diagnostics_out=day_diag,
                )
            )
```

  - Directly after the loop ends and before `run.status = "completed"`, insert the completion check:

```python
    # --- Degraded-feed check at completion (#388, ADR-0013) ----------------
    # data_degraded = start-of-scan quality report OR live provider health OR
    # pre-market ingestion shortfall. Only live session days are assessed.
    # #388 review A2: severity_level() below is the ONLY writer of this gauge at
    # completion, and it is written only when live_days is non-empty. Combined with
    # the scan-start reset added above, the gauge means "severity of the most recent
    # live-session-day scan of this scanner_type". It therefore LATCHES between
    # sessions: a blocker at 07:00 keeps `pre-market-scan-provider-gap` (for: 0m,
    # critical) firing until the next live-day run clears it. That is intended --
    # a degraded pre-market window must not go quiet -- but it must be in the
    # runbook (Task 15) so on-call silences rather than re-investigates.
    finish_now = utc_now()
    live_days = [
        d for d in trading_days if is_live_session_day(d, finish_now, market_holidays)
    ]
    if live_days:
        findings = assess_provider_health(get_provider_health("polygon"))
        for d in live_days:
            diag = day_diagnostics.get(d) or {}
            if "max_premarket_bar_ts" in diag:
                findings += assess_premarket_ingestion(
                    diag, d, finish_now, market_holidays
                )
        scan_provider_gap_severity.labels(scanner_type=scanner_type).set(
            severity_level(findings)
        )
        if any(f.abort for f in findings):
            _stop_for_provider_degradation(
                db,
                run,
                findings,
                universe_id=universe_id,
                scanner_type=scanner_type,
                started_at=started_at,
                events_total=events_total,
                publish=publish,
                phase="at completion",
            )
            return
        if findings:
            apply_provider_gaps(
                run,
                findings,
                universe_id=universe_id,
                scanner_type=scanner_type,
                worker=worker_id(),
            )
            log = (
                logger.error
                if severity_level(findings) == 2
                else logger.warning
            )
            log(
                "run_universe_scan %s: data degraded — %s",
                scan_id,
                "; ".join(f.message for f in findings),
            )
```

  - In the final `publish({"type": "completed", ...})` payload, add `"data_degraded": bool(run.data_degraded),`
    after `"events_detected": events_total,`.

- [ ] **Step 4: Verify it passes.** New file → `6 passed`. Regression: `docker-compose exec backend python -m pytest tests/tasks -q`
  → all pass. The existing `TestRunUniverseScanLogic` and `TestQualityGateInUniverseScan` use
  `date(2026, 6, 2)`, which is historical relative to wall-clock "now", so they never reach the
  health check.
- [ ] **Step 5: Commit.** `git add backend/app/tasks/scanning.py backend/tests/tasks/test_scanning_degradation.py && git commit -m "feat(scanning): alert-and-degrade on Polygon degradation for live days (#388)"`

---

## Task 9: Acceptance test — simulated Polygon outage (blocked egress)

**Files:** `backend/tests/tasks/test_polygon_outage_simulation.py` (new)

This covers the issue's first acceptance criterion end to end with real components: a real
`MassiveDataProvider`, the real `POLYGON_BREAKER` and its listener, the real Redis health record
(fakeredis), and real `_run_universe_scan_logic`. Only the network is faked: the Polygon client
raises `ConnectionError`, which is what blocked egress looks like.

- [ ] **Step 1: Write the test.** Create `backend/tests/tasks/test_polygon_outage_simulation.py`:

```python
"""Acceptance (#388): a blocked-egress Polygon outage yields a degraded, never
empty-but-green, scan — and does not hang."""

import time
from datetime import date, datetime
from unittest.mock import MagicMock, patch

import fakeredis
import pytest

from app.core import provider_health as ph
from app.core.circuit_breakers import POLYGON_BREAKER
from app.exceptions import ProviderError
from app.providers.massive import MassiveDataProvider
from tests.tasks.test_scanning_tasks import (
    _make_assessment,
    _make_db,
    _make_run,
    _make_ticker,
)


@pytest.fixture
def outage(monkeypatch):
    server = fakeredis.FakeRedis(decode_responses=True)
    monkeypatch.setattr(ph, "get_redis", lambda: server)
    monkeypatch.setattr(ph, "_redis_backoff_until", 0.0)
    POLYGON_BREAKER.close()
    yield server
    POLYGON_BREAKER.close()


def _blocked_provider():
    p = MassiveDataProvider.__new__(MassiveDataProvider)
    p._client = MagicMock()
    p._client.get_aggs.side_effect = ConnectionError("egress to api.polygon.io blocked")
    return p


def test_blocked_egress_trips_health_and_stops_live_scan(outage):
    provider = _blocked_provider()
    # Ingestion pipeline hammering Polygon during the outage.
    for _ in range(25):
        with pytest.raises(ProviderError):
            provider.get_bars("AAPL", "minute", 1, "2026-06-02", "2026-06-02")

    snap = ph.get_provider_health("polygon")
    assert snap.breaker_state == "open"
    assert snap.errors_error_window >= 5
    assert ph.worker_id() in snap.breaker_open_workers

    from app.tasks.scanning import _run_universe_scan_logic

    run = _make_run("scan-outage")
    run.quality_gate = None
    published = []
    db = _make_db(run=run, tickers=[_make_ticker("AAPL")])
    started = time.monotonic()
    with (
        patch(
            "app.services.quality_gate.QualityGateService.assess",
            return_value=_make_assessment("trusted"),
        ),
        patch("app.tasks.scanning._compute_data_degraded", return_value=False),
        patch("app.tasks.scanning.utc_now", return_value=datetime(2026, 6, 2, 12, 0)),
    ):
        _run_universe_scan_logic(
            scan_id="scan-outage",
            scanner_type="pre_market_volume_spike",
            universe_id=1,
            start=date(2026, 6, 2),
            end=date(2026, 6, 2),
            db=db,
            publish=published.append,
            is_cancelled=lambda: False,
            task_id="task-outage",
        )
    assert time.monotonic() - started < 5  # no hang
    assert run.status == "failed"  # never "completed" on a dead feed
    assert run.data_degraded is True
    reasons = {
        i["detail"]["reason"]
        for i in run.quality_gate["issues"]
        if i["detail"].get("subtype") == "live_degradation"
    }
    assert "breaker_open" in reasons
    assert published[-1]["type"] == "failed"


def test_polygon_recovery_clears_signal(outage):
    ph.record_breaker_state("polygon", "open", now=time.time() - 400)  # long ago
    POLYGON_BREAKER.close()
    assert ph.get_provider_health("polygon").breaker_state == "closed"
```

- [ ] **Step 2: Run it.** `docker-compose exec backend python -m pytest tests/tasks/test_polygon_outage_simulation.py -q`
  Expected: `2 passed`. If this fails, it is a real integration bug in Tasks 3–8: fix the code,
  not the test.
- [ ] **Step 3: Commit.** `git add backend/tests/tasks/test_polygon_outage_simulation.py && git commit -m "test(scanning): blocked-egress Polygon outage acceptance test (#388)"`

---

## Task 10: API — degraded runs visible and queryable

**Files:** `backend/app/schemas/scanner.py`, `backend/app/routers/scanner.py`, `backend/tests/api/test_scanner_degraded_runs.py` (new)

- [ ] **Step 1: Write the failing test.** Create `backend/tests/api/test_scanner_degraded_runs.py`:

```python
"""#388: degraded runs are visible and queryable via the scanner API."""

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.main import app
from app.models.scanner_run import ScannerRun
from tests.fixtures.core import seed_universes

client = TestClient(app)

_LIVE_ISSUE = {
    "code": "provider_gap",
    "severity": "blocker",
    "message": "No pre-market minute bars ingested for 2026-06-02",
    "detail": {
        "subtype": "live_degradation",
        "provider": "polygon",
        "reason": "no_fresh_premarket_bars",
        "worker": "celery:1",
    },
}
_HISTORICAL_ISSUE = {
    "code": "provider_gap",
    "severity": "warning",
    "message": "One or more tickers have provider data gaps",
    "detail": {"subtype": "structural"},
}


def _gate(*issues):
    return {"schema_version": "quality_gate.v1", "issues": list(issues)}


def _seed(db: Session):
    universe = seed_universes(db)[0]
    degraded = ScannerRun(
        scanner_type="pre_market_volume_spike",
        status="completed",
        universe_id=universe.id,
        data_degraded=True,
        quality_gate=_gate(_LIVE_ISSUE, _HISTORICAL_ISSUE),
    )
    clean = ScannerRun(
        scanner_type="pre_market_volume_spike",
        status="completed",
        universe_id=universe.id,
        data_degraded=False,
        quality_gate=_gate(_HISTORICAL_ISSUE),
    )
    other = ScannerRun(scanner_type="liquidity_hunt", status="completed", data_degraded=False)
    db.add_all([degraded, clean, other])
    db.flush()
    return universe, degraded


def test_history_exposes_data_degraded_and_live_gaps(db: Session):
    _seed(db)
    data = client.get("/api/v1/scanner/history").json()
    by_degraded = {r["data_degraded"]: r for r in data if r["scanner_type"] == "pre_market_volume_spike"}
    assert by_degraded[True]["live_provider_gaps"] == [_LIVE_ISSUE]
    assert by_degraded[False]["live_provider_gaps"] == []  # historical gaps excluded


def test_history_filters_by_data_degraded(db: Session):
    _seed(db)
    data = client.get("/api/v1/scanner/history?data_degraded=true").json()
    assert len(data) == 1
    assert data[0]["data_degraded"] is True


def test_history_filters_by_universe_and_scanner_type(db: Session):
    universe, _ = _seed(db)
    data = client.get(
        f"/api/v1/scanner/history?universe_id={universe.id}"
        "&scanner_type=pre_market_volume_spike&limit=1"
    ).json()
    assert len(data) == 1
    assert data[0]["scanner_type"] == "pre_market_volume_spike"


def test_status_endpoint_exposes_degradation(db: Session):
    _, degraded = _seed(db)
    data = client.get(f"/api/v1/scanner/runs/{degraded.uuid}/status").json()
    assert data["data_degraded"] is True
    assert data["live_provider_gaps"][0]["detail"]["reason"] == "no_fresh_premarket_bars"
```

- [ ] **Step 2: Verify it fails.** `docker-compose exec backend python -m pytest tests/api/test_scanner_degraded_runs.py -q`
  Expected: `KeyError: 'data_degraded'` / length assertions fail.

- [ ] **Step 3: Implement the schemas.** In `backend/app/schemas/scanner.py`, ensure `Field` is
  imported from pydantic (`from pydantic import BaseModel, ConfigDict, Field`). Then add these fields
  to **both** `ScannerRunResponse` (after `diagnostics`) and `ScannerRunStatusResponse` (after `progress`):

```python
    # #388: live-degradation marking (ScannerRun.data_degraded) and the
    # provider_gap issues with detail.subtype == "live_degradation".
    data_degraded: Optional[bool] = None
    live_provider_gaps: List[Dict[str, Any]] = Field(default_factory=list)
```

- [ ] **Step 4: Implement the router.** In `backend/app/routers/scanner.py`:
  - Add the import `from app.services.provider_degradation import live_provider_gaps`
    directly after `from app.services import StockDataService` (#388 review A10: there is no
    `from app.services.quality_gate import ...` line in this router to anchor on).
  - Replace `get_scanner_history` with:

```python
@router.get("/history", response_model=List[ScannerRunResponse])
def get_scanner_history(
    limit: int = Query(20, ge=1, le=200),
    universe_id: Optional[int] = Query(None),
    scanner_type: Optional[str] = Query(None, max_length=50),
    data_degraded: Optional[bool] = Query(None),
    db: Session = Depends(get_db),
):
    """Get recent scanner runs, optionally filtered (#388: data_degraded is queryable)."""
    query = db.query(ScannerRun)
    if universe_id is not None:
        query = query.filter(ScannerRun.universe_id == universe_id)
    if scanner_type is not None:
        query = query.filter(ScannerRun.scanner_type == scanner_type)
    if data_degraded is not None:
        query = query.filter(ScannerRun.data_degraded.is_(data_degraded))
    runs = query.order_by(ScannerRun.created_at.desc()).limit(limit).all()

    # Map to schema
    return [
        ScannerRunResponse(
            scan_id=str(run.uuid),
            status=run.status,
            scanner_type=run.scanner_type,
            stocks_scanned=run.stocks_scanned,
            events_detected=run.events_detected,
            execution_time_ms=run.execution_time_ms,
            error_message=run.error_message,
            created_at=run.created_at,
            data_degraded=run.data_degraded,
            live_provider_gaps=live_provider_gaps(run.quality_gate),
        )
        for run in runs
    ]
```

  - In `get_scan_status`, add `data_degraded=run.data_degraded,` and
    `live_provider_gaps=live_provider_gaps(run.quality_gate),` to the `ScannerRunStatusResponse(...)` call after `progress=progress,`.

- [ ] **Step 5: Verify it passes.** New file → `4 passed`. Regression: `docker-compose exec backend python -m pytest tests/api/test_scanner.py -q` → all pass.
- [ ] **Step 6: Commit.** `git add backend/app/schemas/scanner.py backend/app/routers/scanner.py backend/tests/api/test_scanner_degraded_runs.py && git commit -m "feat(api): expose + filter degraded scanner runs (#388)"`

---

## Task 11: Scrape-time gauge refresh + Polygon WS feed status

**Files:** `backend/app/services/websocket_manager.py`, `backend/app/routers/live_data.py`, `backend/app/main.py`,
`backend/tests/services/test_websocket_manager.py`, `backend/tests/api/test_live_feed_status.py` (new), `backend/tests/api/test_metrics.py`

- [ ] **Step 1: Write the failing tests.**
  Append to `backend/tests/services/test_websocket_manager.py`:

```python


def test_feed_status_none_when_disabled_by_config():
    StockWebSocketManager._instance = None
    manager = StockWebSocketManager()
    manager.api_key = "k"
    with patch("app.services.websocket_manager.settings.LIVE_WEBSOCKET_ENABLED", False):
        assert manager.feed_status() is None
    manager.api_key = ""
    assert manager.feed_status() is None


def test_connected_flag_resets_when_client_exits():
    StockWebSocketManager._instance = None
    manager = StockWebSocketManager()
    manager.api_key = "k"
    seen_during_run = []
    client = MagicMock()
    client.run.side_effect = lambda handler: seen_during_run.append(manager._connected)
    targets = []
    with (
        patch("app.services.websocket_manager.settings.LIVE_WEBSOCKET_ENABLED", True),
        patch("app.services.websocket_manager.WebSocketClient", return_value=client),
        patch(
            "app.services.websocket_manager.asyncio.get_event_loop",
            return_value=MagicMock(),
        ),
        patch(
            "app.services.websocket_manager.threading.Thread",
            side_effect=lambda target, daemon: targets.append(target) or MagicMock(),
        ),
    ):
        manager.start()
        targets[0]()  # run the client thread body synchronously
        assert seen_during_run == [True]
        assert manager._connected is False
        assert manager.feed_status() is False
```

  Create `backend/tests/api/test_live_feed_status.py`:

```python
"""#388: the per-ticker live WS reports Polygon stream status as a feed_status frame."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi.testclient import TestClient

from app.core.auth import verify_ws_origin, ws_get_current_user
from app.main import app


def test_ticker_ws_sends_feed_status_on_connect():
    app.dependency_overrides[ws_get_current_user] = lambda: SimpleNamespace(id="u-388")
    app.dependency_overrides[verify_ws_origin] = lambda: None
    manager = "app.routers.live_data.websocket_manager"
    try:
        with (
            patch(f"{manager}.subscribe", MagicMock()),
            patch(f"{manager}.register", AsyncMock(return_value=asyncio.Queue())),
            patch(f"{manager}.unregister", MagicMock()),
            patch(f"{manager}.feed_status", MagicMock(return_value=False)),
            patch("app.routers.live_data.FEED_STATUS_POLL_SECONDS", 0.05),
            patch("app.routers.live_data.settings.WS_IDLE_TIMEOUT_SECONDS", 0.3),
        ):
            with TestClient(app).websocket_connect("/api/v1/live/ws/AAPL/minute") as ws:
                assert ws.receive_json() == {
                    "type": "feed_status",
                    "polygon_ws_connected": False,
                }
    finally:
        app.dependency_overrides.pop(ws_get_current_user, None)
        app.dependency_overrides.pop(verify_ws_origin, None)
```

  Append to `backend/tests/api/test_metrics.py`:

```python


def test_metrics_endpoint_exports_provider_health_gauges():
    """#388: /metrics refreshes provider-health gauges at scrape time."""
    response = client.get("/metrics")
    assert response.status_code == 200
    body = response.text
    assert 'provider_error_rate{provider="polygon"}' in body
    assert 'provider_circuit_breaker_state{provider="polygon"}' in body
    assert 'provider_request_latency_p95_seconds{provider="polygon"}' in body
    assert "polygon_ws_connected" in body
```

  (Check the name of the existing `TestClient` variable at the top of `test_metrics.py` with
  `grep -n "TestClient(" backend/tests/api/test_metrics.py`, and use it.)

- [ ] **Step 2: Verify they fail.**
  `docker-compose exec backend python -m pytest tests/services/test_websocket_manager.py tests/api/test_live_feed_status.py tests/api/test_metrics.py -q`
  Expected: `AttributeError: ... has no attribute 'feed_status'`, and the provider gauges are missing from `/metrics`.

- [ ] **Step 3: Implement `websocket_manager.py`.**
  - Add the method (after `start`):

```python
    def feed_status(self) -> Optional[bool]:
        """Polygon per-ticker stream state for health/UI (#388).

        None when the stream is disabled by configuration (no API key or
        LIVE_WEBSOCKET_ENABLED=false); otherwise whether the client is connected.
        """
        if not self.api_key or not settings.LIVE_WEBSOCKET_ENABLED:
            return None
        return self._connected
```

  - In `start()`'s inner `run_client`, replace the `except` block with `except` + `finally`, so that
    `_connected` is cleared however the client exits:

```python
            except Exception as e:
                logger.error(f"Polygon WebSocket Error: {e}")
            finally:
                # client.run() can also return without raising (e.g. reconnects
                # exhausted); either way the per-ticker stream is down now.
                self._connected = False
                logger.warning(
                    "Polygon WebSocket client stopped — per-ticker live stream unavailable"
                )
```

- [ ] **Step 4: Implement `live_data.py`.** Add `from typing import Optional` to the imports. Below
  `router = APIRouter(...)`, add:

```python
# How often an otherwise idle ticker stream re-checks Polygon WS status (#388).
FEED_STATUS_POLL_SECONDS = 5.0


def _feed_status_frame(connected: Optional[bool]) -> str:
    """Status frame for the per-ticker stream; clients must not treat it as a bar."""
    return json.dumps({"type": "feed_status", "polygon_ws_connected": connected})
```

  In `stock_live_websocket`, replace everything from `deadline = time.monotonic() + settings.WS_MAX_LIFETIME_SECONDS`
  down to (not including) `except WebSocketDisconnect:` with:

```python
        deadline = time.monotonic() + settings.WS_MAX_LIFETIME_SECONDS
        idle_timeout = settings.WS_IDLE_TIMEOUT_SECONDS
        last_message_at = time.monotonic()
        feed_status = websocket_manager.feed_status()

        try:
            await websocket.send_text(_feed_status_frame(feed_status))
            while True:
                now = time.monotonic()
                remaining = deadline - now
                if remaining <= 0:
                    await websocket.close(1001)
                    break
                idle_left = idle_timeout - (now - last_message_at)
                if idle_left <= 0:
                    # Idle timeout exceeded
                    await websocket.close(1000)
                    break
                wait = min(idle_left, remaining, FEED_STATUS_POLL_SECONDS)
                try:
                    message = await asyncio.wait_for(queue.get(), timeout=wait)
                    await websocket.send_text(message)
                    last_message_at = time.monotonic()
                except asyncio.TimeoutError:
                    current = websocket_manager.feed_status()
                    if current != feed_status:
                        feed_status = current
                        await websocket.send_text(_feed_status_frame(feed_status))
```

  The `except WebSocketDisconnect`, `except Exception` and `finally:` blocks stay as they are.
  Idle and lifetime semantics don't change: a status frame does not reset the idle clock.

- [ ] **Step 5: Implement `main.py`.** In the `/metrics` handler, add a refresh before registry
  selection:

```python
    @app.get("/metrics", include_in_schema=False)
    def prometheus_metrics():
        # #388: refresh provider-health gauges from the cross-process Redis
        # record (and this process's Polygon WS state) before export.
        from app.core.provider_health import refresh_provider_health_gauges

        try:
            refresh_provider_health_gauges(ws_connected=websocket_manager.feed_status())
        except Exception:
            logging.getLogger(__name__).debug(
                "provider health gauge refresh failed", exc_info=True
            )
```

  Insert only the refresh `try/except` block (and its import) at the top of `prometheus_metrics()`.
  Leave everything from `if os.environ.get("PROMETHEUS_MULTIPROC_DIR"):` to the `return Response(...)`
  unchanged. `websocket_manager` and `logging` are already imported at the top of `main.py`.

- [ ] **Step 6: Verify they pass.** Same command as Step 1 → all pass. Also run `tests/api/test_ws_auth.py -q`
  (the unauthenticated rejection path is unchanged).
- [ ] **Step 7: Commit.** `git add backend/app/services/websocket_manager.py backend/app/routers/live_data.py backend/app/main.py backend/tests/services/test_websocket_manager.py backend/tests/api/test_live_feed_status.py backend/tests/api/test_metrics.py && git commit -m "feat(live): Polygon WS feed_status + scrape-time provider gauges (#388)"`

---

## Task 12: Frontend — scanner degraded-run banner

**Files:** `frontend/src/api/scanner/types.ts`, `frontend/src/api/scanner/runs.ts`, `frontend/src/api/scanner/runs.test.ts` (new),
`frontend/src/pages/Scanner/ProviderDegradedBanner.tsx` (new), `frontend/src/pages/Scanner/ProviderDegradedBanner.test.tsx` (new),
`frontend/src/pages/Scanner/ResultsPanel.tsx`, `frontend/src/pages/Scanner/index.tsx`

- [ ] **Step 1: Write the failing tests.**
  Create `frontend/src/api/scanner/runs.test.ts`:

```ts
import { describe, expect, it, vi, beforeEach } from 'vitest';
import { fetchScannerHistory } from './runs';

const mocks = vi.hoisted(() => ({ get: vi.fn() }));

vi.mock('../client', () => ({
  apiClient: { get: (...args: unknown[]) => mocks.get(...args) },
}));

describe('fetchScannerHistory', () => {
  beforeEach(() => vi.clearAllMocks());

  it('keeps the limit-only call shape', async () => {
    mocks.get.mockResolvedValueOnce({ data: [] });
    await fetchScannerHistory(10);
    expect(mocks.get).toHaveBeenCalledWith('/scanner/history', { params: { limit: 10 } });
  });

  it('passes degraded-run filters (#388)', async () => {
    mocks.get.mockResolvedValueOnce({ data: [] });
    await fetchScannerHistory(1, { universe_id: 6, scanner_type: 'pre_market_volume_spike', data_degraded: true });
    expect(mocks.get).toHaveBeenCalledWith('/scanner/history', {
      params: { limit: 1, universe_id: 6, scanner_type: 'pre_market_volume_spike', data_degraded: true },
    });
  });
});
```

  Create `frontend/src/pages/Scanner/ProviderDegradedBanner.test.tsx`:

```tsx
import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';
import { ProviderDegradedBanner } from './ProviderDegradedBanner';
import type { ScannerRunResponse } from '../../api/scanner';

const baseRun: ScannerRunResponse = {
  scan_id: 'abc', status: 'completed', stocks_scanned: 100, events_detected: 0,
  execution_time_ms: 10, scanner_type: 'pre_market_volume_spike',
};

describe('ProviderDegradedBanner', () => {
  it('renders nothing without live provider gaps', () => {
    const { container } = render(<ProviderDegradedBanner run={{ ...baseRun, data_degraded: true, live_provider_gaps: [] }} />);
    expect(container).toBeEmptyDOMElement();
  });

  it('renders nothing when run is null', () => {
    const { container } = render(<ProviderDegradedBanner run={null} />);
    expect(container).toBeEmptyDOMElement();
  });

  it('shows each gap message and coverage ratio', () => {
    render(
      <ProviderDegradedBanner
        run={{
          ...baseRun,
          data_degraded: true,
          live_provider_gaps: [
            {
              code: 'provider_gap', severity: 'warning', message: 'Only 30% of tickers have pre-market data (30/100)',
              detail: { subtype: 'live_degradation', provider: 'polygon', reason: 'partial_coverage', coverage_ratio: 0.3 },
            },
            {
              code: 'provider_gap', severity: 'blocker', message: 'Polygon circuit breaker open (celery:1) — provider unavailable',
              detail: { subtype: 'live_degradation', provider: 'polygon', reason: 'breaker_open' },
            },
          ],
        }}
      />,
    );
    expect(screen.getByText(/Market data degraded during this scan/)).toBeInTheDocument();
    expect(screen.getByText(/Only 30% of tickers/)).toBeInTheDocument();
    expect(screen.getByText(/coverage 30%/)).toBeInTheDocument();
    expect(screen.getByText(/circuit breaker open/)).toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Verify they fail.** `cd frontend && npx vitest run src/api/scanner/runs.test.ts src/pages/Scanner/ProviderDegradedBanner.test.tsx`
  Expected: the filters test fails (params missing), and the banner test fails to resolve `./ProviderDegradedBanner`.

- [ ] **Step 3: Implement the types.** In `frontend/src/api/scanner/types.ts`, directly above `export interface ScannerRunResponse {`, add:

```ts
/** A live-degradation provider_gap issue from ScannerRun.quality_gate (#388, ADR-0013). */
export interface LiveProviderGapDetail {
  subtype: 'live_degradation';
  provider: string;
  reason: string;
  worker?: string | null;
  coverage_ratio?: number;
  [key: string]: unknown;
}

export interface LiveProviderGap {
  code: 'provider_gap';
  severity: 'blocker' | 'warning';
  message: string;
  detail: LiveProviderGapDetail;
}

export interface ScannerHistoryFilters {
  universe_id?: number;
  scanner_type?: string;
  data_degraded?: boolean;
}
```

  Add to **both** `ScannerRunResponse` (after `quality_gate?`) and `ScannerRunStatus` (after `progress?`):

```ts
  data_degraded?: boolean | null;
  live_provider_gaps?: LiveProviderGap[];
```

- [ ] **Step 4: Implement `runs.ts`.** Add `ScannerHistoryFilters` to the type import list and replace `fetchScannerHistory`:

```ts
export const fetchScannerHistory = async (
  limit: number = 20,
  filters: ScannerHistoryFilters = {},
): Promise<ScannerRunResponse[]> => {
  const response = await apiClient.get('/scanner/history', { params: { limit, ...filters } });
  return response.data;
};
```

- [ ] **Step 5: Implement the banner.** Create `frontend/src/pages/Scanner/ProviderDegradedBanner.tsx`. It uses the
  same visual language as the existing "Data quality degraded" banner in `Scanner/index.tsx`:

```tsx
import type { ScannerRunResponse } from '../../api/scanner';

export interface ProviderDegradedBannerProps {
  run?: ScannerRunResponse | null;
}

/** Live Polygon degradation recorded on the latest scan run (#388, ADR-0013). */
export function ProviderDegradedBanner({ run }: ProviderDegradedBannerProps) {
  const gaps = run?.live_provider_gaps ?? [];
  if (gaps.length === 0) return null;
  return (
    <div
      role="alert"
      className="flex items-start gap-3 rounded-lg border border-amber-400 bg-amber-50 px-4 py-3 text-amber-800 dark:border-amber-500 dark:bg-amber-900/20 dark:text-amber-300"
    >
      <span className="mt-0.5 text-lg leading-none">⚠️</span>
      <div className="flex-1 text-sm">
        <span className="font-semibold">Market data degraded during this scan</span> — results may be
        incomplete{run?.status === 'failed' ? ' and the scan was stopped' : ''}.
        <ul className="mt-1 list-disc pl-5">
          {gaps.map((gap, i) => (
            <li key={`${gap.detail.reason}-${i}`}>
              {gap.message}
              {typeof gap.detail.coverage_ratio === 'number' &&
                ` (coverage ${Math.round(gap.detail.coverage_ratio * 100)}%)`}
            </li>
          ))}
        </ul>
      </div>
    </div>
  );
}
```

- [ ] **Step 6: Wire `ResultsPanel`.** In `frontend/src/pages/Scanner/ResultsPanel.tsx`:
  - Import `import { ProviderDegradedBanner } from './ProviderDegradedBanner';`
  - Add `latestRun?: ScannerRunResponse | null;` to `ResultsPanelProps`, and destructure `latestRun` in the signature.
  - Render `<ProviderDegradedBanner run={latestRun} />` as the first child of the fragment (before `{scanResults && (`).

- [ ] **Step 7: Wire the Scanner page.** In `frontend/src/pages/Scanner/index.tsx`:
  - After the existing `scanHistory` `useQuery`, add:

```tsx
  // #388: latest run for the selected universe/scanner drives the degraded banner.
  // Key starts with 'scannerHistory' so finishScan()'s invalidation refreshes it.
  const { data: latestRuns } = useQuery({
    queryKey: ['scannerHistory', 'latest', state.selectedUniverse, state.selectedConfig],
    queryFn: () => fetchScannerHistory(1, {
      universe_id: state.selectedUniverse!,
      scanner_type: state.selectedConfig,
    }),
    enabled: !!state.selectedUniverse && !!state.selectedConfig,
  });
  const latestRun = latestRuns?.[0] ?? null;
```

  - Pass `latestRun={latestRun}` to `<ResultsPanel ... />`.

- [ ] **Step 8: Verify.** `cd frontend && npx vitest run src/api/scanner src/pages/Scanner && npx tsc --noEmit`
  Expected: all pass (the existing `Scanner.test.tsx` already mocks `fetchScannerHistory` to resolve `[]`), and tsc exits 0.
- [ ] **Step 9: Commit.** `git add frontend/src/api/scanner frontend/src/pages/Scanner && git commit -m "feat(ui): scanner banner for live provider degradation (#388)"`

---

## Task 13: Frontend — "live feed unavailable" badge on StockDetailPage

**Files:** `frontend/src/hooks/useLiveStockData.ts`, `frontend/src/hooks/useLiveStockData.test.ts`,
`frontend/src/pages/StockDetailPage/LiveFeedUnavailableBadge.tsx` (new), `frontend/src/pages/StockDetailPage/LiveFeedUnavailableBadge.test.tsx` (new),
`frontend/src/pages/StockDetailPage/index.tsx`

- [ ] **Step 1: Write the failing tests.** Add inside the `describe('useLiveStockData', ...)` block of `frontend/src/hooks/useLiveStockData.test.ts`:

```ts
  it('feedAvailable is null until a feed_status frame arrives', () => {
    const { result } = renderHook(() => useLiveStockData('AMD'));
    expect(result.current.feedAvailable).toBeNull();
  });

  it('feed_status frames set feedAvailable and never reach liveData (#388)', () => {
    const { result } = renderHook(() => useLiveStockData('AMD'));
    act(() => { vi.advanceTimersByTime(50); });
    act(() => { MockWebSocket.lastInstance!.simulateOpen(); });
    act(() => { MockWebSocket.lastInstance!.simulateMessage({ type: 'feed_status', polygon_ws_connected: false }); });
    expect(result.current.feedAvailable).toBe(false);
    expect(result.current.liveData).toBeNull();
    act(() => { MockWebSocket.lastInstance!.simulateMessage({ type: 'feed_status', polygon_ws_connected: true }); });
    expect(result.current.feedAvailable).toBe(true);
  });
```

  Create `frontend/src/pages/StockDetailPage/LiveFeedUnavailableBadge.test.tsx`:

```tsx
import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';
import { LiveFeedUnavailableBadge } from './LiveFeedUnavailableBadge';

describe('LiveFeedUnavailableBadge', () => {
  it('tells the user the chart shows last known data', () => {
    render(<LiveFeedUnavailableBadge />);
    expect(screen.getByRole('status')).toHaveTextContent('Live feed unavailable — showing last known data');
  });
});
```

- [ ] **Step 2: Verify they fail.** `cd frontend && npx vitest run src/hooks/useLiveStockData.test.ts src/pages/StockDetailPage/LiveFeedUnavailableBadge.test.tsx`
  Expected: `feedAvailable` is `undefined`, and the badge module cannot be resolved.

- [ ] **Step 3: Implement the hook.** In `frontend/src/hooks/useLiveStockData.ts`:
  - After the `LiveStockData` interface, add:

```ts
/** Server status frame on the per-ticker stream (#388) — not a bar. */
export interface FeedStatusFrame {
  type: 'feed_status';
  /** null = Polygon stream disabled by config; false = enabled but disconnected. */
  polygon_ws_connected: boolean | null;
}
```

  - Add state: `const [feedAvailable, setFeedAvailable] = useState<boolean | null>(null);`
  - Replace the body of the `try` block in `ws.onmessage` with:

```ts
          const data = JSON.parse(event.data) as LiveStockData | FeedStatusFrame;
          if ('type' in data && data.type === 'feed_status') {
            setFeedAvailable(data.polygon_ws_connected);
            return;
          }
          setLiveData(data as LiveStockData);
```

  - Change the return to `return { liveData, isConnected, feedAvailable };`.

- [ ] **Step 4: Implement the badge.** Create `frontend/src/pages/StockDetailPage/LiveFeedUnavailableBadge.tsx`. It reuses
  the Scanner page's degraded-banner visual language:

```tsx
/** Polygon per-ticker stream is down: the chart is frozen at its last bar (#388). */
export function LiveFeedUnavailableBadge() {
  return (
    <div
      role="status"
      className="flex items-start gap-3 rounded-lg border border-amber-400 bg-amber-50 px-4 py-3 text-amber-800 dark:border-amber-500 dark:bg-amber-900/20 dark:text-amber-300"
    >
      <span className="mt-0.5 text-lg leading-none">⚠️</span>
      <div className="flex-1 text-sm">
        <span className="font-semibold">Live feed unavailable — showing last known data</span>. The Polygon
        real-time stream is disconnected; the chart resumes updating when it reconnects.
      </div>
    </div>
  );
}
```

- [ ] **Step 5: Wire the page.** In `frontend/src/pages/StockDetailPage/index.tsx`:
  - Import `import { LiveFeedUnavailableBadge } from './LiveFeedUnavailableBadge';`
  - Change line ~117 to `const { liveData, isConnected, feedAvailable } = useLiveStockData(symbol, wsResolution);`
  - Directly before `{recentSplits.length > 0 && (`, add `{feedAvailable === false && <LiveFeedUnavailableBadge />}`.
    `null` (disabled by config or no status yet) shows nothing.

- [ ] **Step 6: Verify.** `cd frontend && npx vitest run src/hooks src/pages/StockDetailPage && npx tsc --noEmit` → all pass, tsc exit 0.
- [ ] **Step 7: Commit.** `git add frontend/src/hooks frontend/src/pages/StockDetailPage && git commit -m "feat(ui): live-feed-unavailable badge on stock detail (#388)"`

---

## Task 14: Grafana alert rules + dashboard panels

**Files:** `grafana/provisioning/alerting/rules.yaml`, `grafana/provisioning/dashboards/infrastructure.json`,
`grafana/provisioning/dashboards/scanner-performance.json`, `backend/tests/core/test_grafana_provider_alerts.py` (new)

- [ ] **Step 1: Write the failing test.** Create `backend/tests/core/test_grafana_provider_alerts.py`. It follows the
  repo-root file pattern of `tests/api/test_metrics.py`, which skips when the root is not mounted, as in the baked image:

```python
"""#388: Grafana provisioning references the provider-health metrics."""

import json
import os

import pytest
import yaml

_REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
_RULES = os.path.join(_REPO_ROOT, "grafana/provisioning/alerting/rules.yaml")
_DASH = os.path.join(_REPO_ROOT, "grafana/provisioning/dashboards")

pytestmark = pytest.mark.skipif(
    not os.path.exists(_RULES), reason="grafana provisioning not accessible"
)


def _rules():
    with open(_RULES) as f:
        doc = yaml.safe_load(f)
    return {r["uid"]: r for g in doc["groups"] for r in g["rules"]}


def _exprs(rule):
    return " ".join(d["model"].get("expr", "") for d in rule["data"])


def test_polygon_provider_degraded_rule():
    rule = _rules()["polygon-provider-degraded"]
    assert rule["labels"]["severity"] == "critical"
    assert rule["for"] == "2m"
    exprs = _exprs(rule)
    for metric in ("provider_circuit_breaker_state", "provider_error_rate", "polygon_ws_connected"):
        assert metric in exprs


def test_polygon_latency_rule_is_warning_only():
    rule = _rules()["polygon-latency-elevated"]
    assert rule["labels"]["severity"] == "warning"
    assert "provider_request_latency_p95_seconds" in _exprs(rule)


def test_pre_market_provider_gap_rule():
    rule = _rules()["pre-market-scan-provider-gap"]
    assert rule["labels"]["severity"] == "critical"
    assert "scan_provider_gap_severity" in _exprs(rule)


@pytest.mark.parametrize("name", ["infrastructure.json", "scanner-performance.json"])
def test_dashboards_have_provider_panels(name):
    with open(os.path.join(_DASH, name)) as f:
        dash = json.load(f)
    exprs = " ".join(t.get("expr", "") for p in dash["panels"] for t in p.get("targets", []))
    assert "provider_error_rate" in exprs
    assert "provider_circuit_breaker_state" in exprs
    ids = [p["id"] for p in dash["panels"]]
    assert len(ids) == len(set(ids))
```

- [ ] **Step 2: Verify it fails.** `cd backend && python -m pytest tests/core/test_grafana_provider_alerts.py -q`
  Run it **from the host checkout**: the backend container only mounts `backend/`, so there the
  tests skip. Expected: `KeyError: 'polygon-provider-degraded'` and failed dashboard assertions. A host run
  needs the backend venv, because the root `tests/conftest.py` imports `app.main`. If no host venv is
  available, the skip is acceptable. The `yaml.safe_load` check in Step 3 and the script's `ok` in
  Step 4 then serve as the structural gate, plus this standalone check:
  `python3 -c "import json;[json.load(open(f'grafana/provisioning/dashboards/{n}.json')) for n in ('infrastructure','scanner-performance')];print('ok')"`.

- [ ] **Step 3: Add the alert rules.** In `grafana/provisioning/alerting/rules.yaml`, insert the following
  after the `scan-high-failed-ticker-ratio` rule (which ends with `expression: $B > 0.1`) and before
  `  - name: LiveTrading`. Indentation must match the sibling rules (6 spaces before `- uid`).

```yaml

      - uid: polygon-provider-degraded
        title: Polygon Provider Degraded
        condition: E
        for: 2m
        annotations:
          summary: >
            Polygon market data is degraded: circuit breaker open in some process,
            rolling 5-minute error rate >= 25% (POLYGON_HEALTH_ERROR_RATE_THRESHOLD),
            or the per-ticker WebSocket stream is disconnected. Live-day pre-market
            scans stop or are marked degraded (ADR-0013). See deployment-guide.md
            "Pre-Market Data Degradation Runbook".
        labels:
          severity: critical
        data:
          - refId: B
            relativeTimeRange:
              from: 300
              to: 0
            datasourceUid: prometheus
            model:
              # 0=closed, 1=half-open, 2=open (worst across processes)
              expr: max(provider_circuit_breaker_state{provider="polygon"})
              refId: B
          - refId: C
            relativeTimeRange:
              from: 300
              to: 0
            datasourceUid: prometheus
            model:
              expr: max(provider_error_rate{provider="polygon"})
              refId: C
          - refId: D
            relativeTimeRange:
              from: 300
              to: 0
            datasourceUid: prometheus
            model:
              # 1=connected, 0=disconnected, -1=disabled by config (never alerts)
              expr: max(polygon_ws_connected)
              refId: D
          - refId: E
            relativeTimeRange:
              from: 300
              to: 0
            datasourceUid: "-- Grafana --"
            model:
              type: math
              expression: $B >= 2 || $C >= 0.25 || $D == 0

      - uid: polygon-latency-elevated
        title: Polygon Latency Elevated
        condition: C
        for: 5m
        annotations:
          summary: >
            Polygon rolling 15-minute p95 latency exceeds 5 s
            (POLYGON_HEALTH_LATENCY_P95_THRESHOLD_SECONDS). Scans continue but are
            marked degraded (warning) per ADR-0013 — informational, not a page.
        labels:
          severity: warning
        data:
          - refId: B
            relativeTimeRange:
              from: 900
              to: 0
            datasourceUid: prometheus
            model:
              expr: max(provider_request_latency_p95_seconds{provider="polygon"})
              refId: B
          - refId: C
            relativeTimeRange:
              from: 900
              to: 0
            datasourceUid: "-- Grafana --"
            model:
              type: math
              expression: $B > 5

      - uid: pre-market-scan-provider-gap
        title: Pre-Market Scan Ran on Degraded Data
        condition: C
        for: 0m
        annotations:
          summary: >
            The latest pre_market_volume_spike run on today's session recorded a
            blocker provider_gap (no/stale pre-market minute bars, breaker open, or
            high error rate). Check the run's quality_gate via
            GET /api/v1/scanner/history?data_degraded=true and the Polygon panels.
        labels:
          severity: critical
        data:
          - refId: B
            relativeTimeRange:
              from: 300
              to: 0
            datasourceUid: prometheus
            model:
              # 0=none, 1=warning, 2=blocker
              expr: max(scan_provider_gap_severity{scanner_type="pre_market_volume_spike"})
              refId: B
          - refId: C
            relativeTimeRange:
              from: 300
              to: 0
            datasourceUid: "-- Grafana --"
            model:
              type: math
              expression: $B >= 2
```

  Then validate: `python3 -c "import yaml; yaml.safe_load(open('grafana/provisioning/alerting/rules.yaml')); print('ok')"` → `ok`.

- [ ] **Step 4: Add the dashboard panels.** Run this script once from the repo root. It appends panels
  with unique ids below the existing layout and rewrites the files with 2-space indentation. First
  check the existing indentation with `head -3 grafana/provisioning/dashboards/infrastructure.json`,
  and set `INDENT` to match so the diff stays minimal:

```bash
python3 - <<'EOF'
import json

INDENT = 2
DS = {"type": "prometheus", "uid": "$datasource"}


def stat(title, expr, grid, steps, mappings=None, unit=None):
    p = {
        "title": title,
        "type": "stat",
        "gridPos": grid,
        "options": {
            "colorMode": "background",
            "thresholds": {"mode": "absolute", "steps": steps},
        },
        "targets": [{"datasource": DS, "expr": expr, "legendFormat": title}],
    }
    if mappings:
        p["options"]["mappings"] = mappings
    # Mirror the existing panels (thresholds/mappings under options) AND set them
    # under fieldConfig.defaults, which is where current Grafana reads them.
    defaults = {"thresholds": {"mode": "absolute", "steps": steps}}
    if mappings:
        defaults["mappings"] = mappings
    if unit:
        defaults["unit"] = unit
    p["fieldConfig"] = {"defaults": defaults, "overrides": []}
    return p


BREAKER_MAP = [{"type": "value", "options": {"0": {"text": "Closed"}, "1": {"text": "Half-open"}, "2": {"text": "Open"}}}]
WS_MAP = [{"type": "value", "options": {"-1": {"text": "Disabled"}, "0": {"text": "Disconnected"}, "1": {"text": "Connected"}}}]
RED_AT = lambda v: [{"color": "green", "value": None}, {"color": "red", "value": v}]


def append(path, panels):
    with open(path) as f:
        dash = json.load(f)
    next_id = max(p["id"] for p in dash["panels"]) + 1
    base_y = max(p["gridPos"]["y"] + p["gridPos"]["h"] for p in dash["panels"])
    for p in panels:
        p["id"] = next_id
        next_id += 1
        p["gridPos"]["y"] += base_y
        dash["panels"].append(p)
    with open(path, "w") as f:
        json.dump(dash, f, indent=INDENT, ensure_ascii=False)
        f.write("\n")


append("grafana/provisioning/dashboards/infrastructure.json", [
    stat("Polygon Circuit Breaker", 'max(provider_circuit_breaker_state{provider="polygon"})',
         {"h": 4, "w": 6, "x": 0, "y": 0},
         [{"color": "green", "value": None}, {"color": "orange", "value": 1}, {"color": "red", "value": 2}], BREAKER_MAP),
    stat("Polygon Error Rate (5m)", 'max(provider_error_rate{provider="polygon"})',
         {"h": 4, "w": 6, "x": 6, "y": 0}, RED_AT(0.25), unit="percentunit"),
    stat("Polygon Latency p95 (15m)", 'max(provider_request_latency_p95_seconds{provider="polygon"})',
         {"h": 4, "w": 6, "x": 12, "y": 0}, [{"color": "green", "value": None}, {"color": "orange", "value": 5}], unit="s"),
    stat("Polygon WS (chart stream)", "max(polygon_ws_connected)",
         {"h": 4, "w": 6, "x": 18, "y": 0},
         [{"color": "red", "value": None}, {"color": "blue", "value": -1}, {"color": "red", "value": 0}, {"color": "green", "value": 1}], WS_MAP),
])

append("grafana/provisioning/dashboards/scanner-performance.json", [
    {
        "title": "Polygon Provider Health",
        "type": "timeseries",
        "gridPos": {"h": 8, "w": 12, "x": 0, "y": 0},
        "targets": [
            {"datasource": DS, "expr": 'max(provider_error_rate{provider="polygon"})', "legendFormat": "error rate (5m)"},
            {"datasource": DS, "expr": 'max(provider_circuit_breaker_state{provider="polygon"})', "legendFormat": "breaker (2=open)"},
            {"datasource": DS, "expr": 'max(provider_request_latency_p95_seconds{provider="polygon"})', "legendFormat": "p95 latency s (15m)"},
        ],
    },
    stat("Pre-Market Provider Gap Severity",
         'max(scan_provider_gap_severity{scanner_type="pre_market_volume_spike"})',
         {"h": 8, "w": 12, "x": 12, "y": 0},
         [{"color": "green", "value": None}, {"color": "orange", "value": 1}, {"color": "red", "value": 2}],
         [{"type": "value", "options": {"0": {"text": "Clean"}, "1": {"text": "Warning"}, "2": {"text": "Blocker"}}}]),
])
print("ok")
EOF
```

  Expected output: `ok`.

  **(#388 review A4) This script WILL reformat the whole file, and no `INDENT` value avoids it.**
  Both dashboards are hand-written with compact single-line objects
  (`"gridPos": { "h": 4, "w": 6, "x": 0, "y": 0 }`) that `json.dump(indent=N)` always expands, and
  both files are CRLF while `json.dump` writes LF. Measured on this plan: 433 insertions /
  25 deletions in `infrastructure.json`, 135 / 3 in `scanner-performance.json`.

  So do **not** treat "only additions" as the gate. Choose one:

  1. **Preferred:** discard the script output (`git checkout grafana/provisioning/dashboards/`) and
     paste the four `infrastructure.json` panels and two `scanner-performance.json` panels in by
     hand, matching the surrounding compact style and CRLF endings. Use the script's output only as
     the source of the panel JSON, `id` values (max existing `id` + 1) and `gridPos.y` offsets
     (max existing `y + h`).
  2. Keep the reformat, and say so explicitly in the PR description so review is not surprised by a
     600-line whitespace diff.

  Either way the gate is Step 5 plus `python3 -c "import json; [json.load(open(f)) for f in
  ('grafana/provisioning/dashboards/infrastructure.json',
  'grafana/provisioning/dashboards/scanner-performance.json')]; print('ok')"`.

- [ ] **Step 5: Verify.** `cd backend && python -m pytest tests/core/test_grafana_provider_alerts.py -q` (host) → `5 passed`.
- [ ] **Step 6: Commit.** `git add grafana backend/tests/core/test_grafana_provider_alerts.py && git commit -m "feat(grafana): Polygon degradation alerts + provider health panels (#388)"`

---

## Task 15: ADR-0013, runbook, architecture and env docs

**Files:** `docs/adr/0013-polygon-ibkr-hybrid-failover.md` (new), `docs/adr/README.md`, `deployment-guide.md`, `ARCHITECTURE.md`, `ENV_VARIABLES.md`

- [ ] **Step 1: Write the ADR.** Create `docs/adr/0013-polygon-ibkr-hybrid-failover.md`:

```markdown
# ADR-0013: Polygon↔IBKR Hybrid Failover — Alert-and-Degrade for Scans

**Date**: 2026-09-26  
**Status**: Accepted  
**Issue**: [#388 — providers: define Polygon↔IBKR degraded-feed failover for pre-market scans](https://github.com/omniscient/markethawk/issues/388)

## Context

Polygon.io is the primary market-data source and IBKR the secondary. Until now, nothing defined what
happens when Polygon degrades mid-pre-market (04:00–09:30 ET). `run_pre_market_scan()` reads
`StockAggregate` rows persisted by a separate sync pipeline; it does not call Polygon live. An
outage therefore starved ingestion without raising anything: tickers silently failed
`minimum_volume`, and runs completed "empty-but-green".

Three postures were considered: (1) alert-and-degrade everywhere; (2) auto-failover of bars/quotes
to `IBKRDataProvider`; (3) hybrid. Option 2 is not viable. `IBKRDataProvider.get_bars()` and
`get_snapshots()` are stubs that return `[]` for stocks, and even with real support, IBKR pacing
(60 historical requests / 10 min, no duplicates within 15 s) makes scanning thousands of tickers
inside the pre-market window arithmetically impossible.

## Decision

**Hybrid (option 3):**

- **Full-universe scans — alert-and-degrade, never switch providers.** For live session days
  (today's ET date, at or after 04:00 ET):

  | Failure class | Severity | Action |
  |---|---|---|
  | Circuit breaker open in any process | blocker | Stop the scan (`status=failed`), mark degraded, page |
  | Error rate ≥ `POLYGON_HEALTH_ERROR_RATE_THRESHOLD` (5 min, ≥ `PROVIDER_HEALTH_MIN_CALLS`) | blocker | Stop, mark, page |
  | p95 latency ≥ `POLYGON_HEALTH_LATENCY_P95_THRESHOLD_SECONDS` (15 min) | warning | Continue, mark, warning alert only |
  | No pre-market minute bars, or freshest bar older than `PREMARKET_BAR_STALENESS_MINUTES` before 09:30 ET | blocker | Complete, mark, page |
  | Pre-market coverage below `PREMARKET_MIN_COVERAGE_RATIO` | warning | Complete, mark, record `coverage_ratio` |

  These checks apply to every scanner type run through `_run_universe_scan_logic` on a live session
  day, because any universe scan of today's data depends on the same ingestion. The pre-market
  ingestion checks (no/stale bars, coverage) apply only to scanners that report diagnostics, which
  today means `pre_market_volume_spike`.

  Degradation is recorded on the existing `ScannerRun.data_degraded` and as
  `quality_gate.issues[]` entries with `code=provider_gap`, `detail.subtype="live_degradation"`,
  `detail.worker`, and a `detail.reason` from the table. No parallel "data_quality" field is added.
- **Active Watchlist — already resilient, no new failover.** `live_scanner/` streams watchlist
  symbols straight from IB Gateway (`reqMktData`/`reqRealTimeBars`). It reaches clients over Redis
  pub/sub (`watchlist:live_data`, `watchlist:alerts`) with no Polygon coupling.
- **Per-ticker chart stream (`/api/v1/live/ws/{ticker}/{resolution}`) — detection only, explicitly no
  fallback.** IBKR can only stream the curated watchlist and cannot serve arbitrary tickers on
  demand. The stream reports `feed_status` frames. The UI shows "Live feed unavailable — showing
  last known data". `polygon_ws_connected` means "the Polygon client thread is running". It is
  set before the socket authenticates and cleared when the client exits, so it detects a dead
  stream but not an authenticated-yet-silent one.

Provider health is a cross-process Redis rolling window (`app/core/provider_health.py`), written at
the `MassiveDataProvider` chokepoint and by a pybreaker listener. Breaker state is in-process per
worker, so the record is keyed by `hostname:pid`, and the local breaker is OR'd in as a fast path.

## Consequences

- A live Polygon outage produces a visibly degraded or failed run with a reason: in the UI, via
  `GET /api/v1/scanner/history?data_degraded=true`, and in Grafana (`polygon-provider-degraded`,
  `pre-market-scan-provider-gap`, `polygon-latency-elevated`).
- Every Polygon REST call now costs one pipelined Redis round trip. On Redis errors, writes back off
  for 30 s, so they never slow provider calls.
- Thresholds are env-tunable first cuts that have not been validated against production pre-market
  bar cadence. Revisit after a few weeks of `provider_*` gauge history. In particular the
  10-minute `PREMARKET_BAR_STALENESS_MINUTES` default is the value spec §5 asked to confirm during
  planning; it could not be checked against production bar cadence pre-merge and remains a
  first cut.
- `breaker_open` is only reliable while calls keep flowing. `_merge_breaker_states` ignores entries
  older than `PROVIDER_HEALTH_ERROR_WINDOW_SECONDS` (5 min) and downgrades `open` entries older
  than `POLYGON_CB_RESET_TIMEOUT` to `half-open`, so a process that trips its breaker and then
  stops calling Polygon reads `closed` again after five minutes (verified: age 10 s -> open,
  120 s -> half-open, 400 s -> closed). During a sustained outage with idle workers the
  `no_fresh_premarket_bars` / `stale_premarket_bars` ingestion checks are the backstop, not the
  breaker gauge.
- Historical-range scans are unaffected. Their data quality remains the domain of
  `UniverseQualityReport` and the existing `quality_gate` evidence.
- Real IBKR stock market-data support would be a separate ADR. It would not change the scan posture,
  because of pacing limits.
```

  Append this row to the end of the `docs/adr/README.md` table (the missing 0012 row is a separate,
  pre-existing gap and is out of scope for #388, so do not backfill it here):

```markdown
| [0013](0013-polygon-ibkr-hybrid-failover.md) | Polygon↔IBKR Hybrid Failover — Alert-and-Degrade for Scans | Accepted | 2026-09-26 |
```

- [ ] **Step 2: Runbook.** In `deployment-guide.md`, insert a new section immediately **before**
  `## IBKR Feed Loss Runbook` (after its preceding `---`):

```markdown
## Pre-Market Data Degradation Runbook

Posture: [ADR-0013](docs/adr/0013-polygon-ibkr-hybrid-failover.md). Full-universe scans alert and
degrade. They never switch to IBKR.

### Check first (Grafana)

1. **Infrastructure** dashboard → *Polygon Circuit Breaker*, *Polygon Error Rate (5m)*,
   *Polygon Latency p95 (15m)*, *Polygon WS (chart stream)*.
2. **Scanner Performance** dashboard → *Polygon Provider Health*, *Pre-Market Provider Gap Severity*.
3. Alerts: `polygon-provider-degraded` (critical), `pre-market-scan-provider-gap` (critical),
   `polygon-latency-elevated` (warning).

### Which "degraded" is this?

| Signal | Meaning | Where |
|---|---|---|
| Scanner banner **"Market data degraded during this scan"** / `quality_gate.issues[]` with `code=provider_gap` and `detail.subtype=live_degradation` | **Live** Polygon outage or ingestion stall during today's pre-market | `GET /api/v1/scanner/history?data_degraded=true`, or `GET /api/v1/scanner/runs/{scan_id}/status` → `live_provider_gaps` |
| Scanner banner **"Data quality degraded"** (stale/gap %) | **Historical** aggregate staleness or gaps from the nightly quality report (`/data-health`) | Universes page → quality details |
| `provider_gap` with `detail.subtype` of `absent` / `partial` / `structural` | Historical per-ticker coverage from `UniverseQualityReport` | Same as above; not a live outage |

`detail.reason` identifies the failure class: `breaker_open`, `error_rate`, `latency`,
`no_fresh_premarket_bars`, `stale_premarket_bars`, or `partial_coverage`. `detail.worker` identifies
the process that observed it.

### Breaker state is per process

`POLYGON_BREAKER` lives in-process (`app/core/circuit_breakers.py`). A breaker tripped in a
`celery-worker` child can read `closed` in the API process, and vice versa. **A partial trip is not a
full outage.** The cross-process view is `provider_circuit_breaker_state` (worst state across
processes) and the Redis hash `mh:provider_health:polygon:breaker` (one entry per `hostname:pid`):

```bash
docker-compose exec redis redis-cli -a "$REDIS_PASSWORD" HGETALL mh:provider_health:polygon:breaker
```

An `open` entry older than `POLYGON_CB_RESET_TIMEOUT` counts as half-open. Entries older than
5 minutes are ignored.

### Recovery

- Polygon status page / API key plan limits: 429s surface as `error_rate` findings.
- Once Polygon recovers, breakers half-open and close on the next successful call, and the gauges
  clear within the 5-minute error window. Re-run the scan from the Scanner page. Runs that were
  stopped keep `status=failed` and their `provider_gap` record.
- **`pre-market-scan-provider-gap` does not clear on its own.** `scan_provider_gap_severity` is
  written only by a scan that covers a live session day, so a blocker recorded at 07:00 keeps the
  rule firing until the next live-day run of that `scanner_type` resets it — normally the next
  trading morning. To clear it now, re-run that scanner for today from the Scanner page once
  Polygon is healthy; otherwise silence the rule for the rest of the session.
- `detail.phase` distinguishes the two abort points. `before_day` means the day was never scanned.
  `at_completion` means the days *were* scanned and their events are persisted against the run —
  the run is `failed` because ADR-0013 forbids presenting it as a clean success, not because the
  events are wrong. Check `GET /api/v1/scanner/results` for that run before re-running.
- Ingestion stall with healthy Polygon (`no_fresh_premarket_bars` but breaker closed, errors ~0):
  check the sync pipeline (Catch-Up / universe orchestrator tasks in Flower). The scan only reads
  what sync persisted.

### What needs no troubleshooting

The **Active Watchlist** (`/watchlist`) is IBKR-sourced end to end (`live_scanner/` → IB Gateway →
Redis `watchlist:*` channels) and is unaffected by Polygon outages. For watchlist feed loss, use the
IBKR runbook below. The per-ticker **stock detail chart** has no fallback: during a Polygon WS drop
it shows "Live feed unavailable — showing last known data" until the stream reconnects.

---
```

- [ ] **Step 3: ARCHITECTURE.md.** In the Prometheus metrics table, add after the `ibkr_connection_status` row:

```markdown
| `provider_request_latency_p95_seconds` | Gauge (`livemostrecent`) | `provider` | `core/provider_health.py` (set at `/metrics` scrape) |
| `provider_error_rate` | Gauge (`livemostrecent`) | `provider` | `core/provider_health.py` (set at `/metrics` scrape) |
| `provider_circuit_breaker_state` | Gauge (`livemostrecent`) | `provider` | `core/provider_health.py` (set at `/metrics` scrape) |
| `polygon_ws_connected` | Gauge (`livemostrecent`) | — | `core/provider_health.py` from `websocket_manager.feed_status()` |
| `scan_provider_gap_severity` | Gauge (`mostrecent`) | `scanner_type` | `tasks/scanning.py` (live session days) |
```

  In the `quality_gate.py` row of the services table, replace the sentence
  `Three active issue codes: \`missing_bars\`, \`provider_gap\`, \`insufficient_lookback\`.` with:
  `Three active issue codes: \`missing_bars\`, \`provider_gap\`, \`insufficient_lookback\`. \`provider_gap\` is also appended at scan completion by \`services/provider_degradation.py\` with \`detail.subtype="live_degradation"\` for live Polygon degradation (#388, ADR-0013).`
  Also add a row for the new modules in the same services/core tables (match the neighbouring rows' format):
  `| \`provider_degradation.py\` | Pure failure-class → \`provider_gap\` findings for live pre-market degradation; \`apply_provider_gaps()\` folds them into \`ScannerRun.quality_gate\`/\`data_degraded\` (ADR-0013). |`
  **(#388 review A11)** `circuit_breakers` does not appear in `ARCHITECTURE.md` at all, so there is
  no such row to sit next to. Instead add the new core row immediately after the `cache.py` row
  in the core table: `| \`provider_health.py\` | Cross-process Polygon health record in Redis
  (TTL-bounded per-minute buckets); \`track_provider_call\`, \`get_provider_health\`,
  \`refresh_provider_health_gauges\`, \`worker_id\` (#388, ADR-0013). |`
  Locate the rows with `grep -n "circuit_breakers\|quality_gate.py" ARCHITECTURE.md`.

- [ ] **Step 4: ENV_VARIABLES.md.** Insert a new section before `## Adding a New Variable`:

```markdown
## Provider Health / Degraded-Feed Failover

See [ADR-0013](docs/adr/0013-polygon-ibkr-hybrid-failover.md). All are optional. To override one,
add it to the `backend` and `celery-worker` `environment:` blocks.

| Variable | Default | Description |
|---|---|---|
| `PROVIDER_HEALTH_ERROR_WINDOW_SECONDS` | `300` | Rolling window for `provider_error_rate` and the breaker-state staleness cut-off. |
| `PROVIDER_HEALTH_LATENCY_WINDOW_SECONDS` | `900` | Rolling window for `provider_request_latency_p95_seconds`. |
| `PROVIDER_HEALTH_MIN_CALLS` | `20` | Minimum calls in a window before error rate / p95 are reported (otherwise 0 / none). |
| `POLYGON_HEALTH_ERROR_RATE_THRESHOLD` | `0.25` | Error rate at or above which live-day scans stop (blocker). Mirror changes in Grafana rule `polygon-provider-degraded`. |
| `POLYGON_HEALTH_LATENCY_P95_THRESHOLD_SECONDS` | `5.0` | p95 latency at or above which live-day scans are marked degraded (warning). Mirror changes in rule `polygon-latency-elevated`. |
| `PREMARKET_BAR_STALENESS_MINUTES` | `10` | Freshest pre-market minute bar older than this during 04:00–09:30 ET, or no bar by 04:00 ET + this, marks the run degraded (blocker). |
| `PREMARKET_MIN_COVERAGE_RATIO` | `0.5` | Fraction of evaluable tickers that must have pre-market volume; below this, a `partial_coverage` warning is recorded. The default is deliberately lenient: many liquid names legitimately print no pre-market trades early in the session, so a higher ratio would fire on ordinary sparsity. Raise it once production cadence is known. |

---
```

- [ ] **Step 5: Verify.** `grep -n "0013" docs/adr/README.md` prints the new row. `grep -n "Pre-Market Data Degradation Runbook" deployment-guide.md` prints one line.
- [ ] **Step 6: Commit.** `git add docs/adr deployment-guide.md ARCHITECTURE.md ENV_VARIABLES.md && git commit -m "docs: ADR-0013 hybrid failover, degradation runbook, metrics + env docs (#388)"`

---

## Task 16: Full verification and live validation (CLAUDE.md "Validating Changes")

**Files:** none (verification only)

- [ ] **Step 1: Backend suite.** `docker-compose exec backend python -m pytest -q -x`. Expected: all pass, with no
  new failures relative to `main`. If an unrelated pre-existing failure shows up, confirm it also
  fails on `origin/main` before moving on.
- [ ] **Step 2: Frontend suite + types.** `cd frontend && npx vitest run && npx tsc --noEmit` → all
  green (measured on this plan: 47 files / 408 tests passed, `tsc` exit 0).
  Then `npm run lint`. **(#388 review A5)** `npm run lint` is
  `eslint . --report-unused-disable-directives --max-warnings 0` and already fails on `main` with
  three pre-existing `react-refresh/only-export-components` warnings in
  `src/components/QualityReportModal/GradeBadge.tsx` (2) and `src/pages/ScorecardOverview.tsx` (1).
  Neither file is in this plan's scope. Confirm the count is still exactly 3 and that no warning
  names a file this plan touched; do not "fix" them here.
- [ ] **Step 3: Backend reload.** `docker-compose restart backend celery-worker && docker-compose logs backend --tail=10`.
  Expected: startup lines include `Stock WebSocket Manager started` and there are no tracebacks.
- [ ] **Step 4: Live curl checks.**

```bash
curl -s http://localhost:8000/metrics | grep -E '^(provider_|polygon_ws_connected)'
# expect: provider_error_rate{provider="polygon"} 0.0, provider_circuit_breaker_state{...} 0.0,
#         provider_request_latency_p95_seconds{...} <n>, polygon_ws_connected 1.0 (or -1.0 if disabled)
curl -s "http://localhost:8000/api/v1/scanner/history?limit=3" | python -m json.tool | grep -E '"data_degraded"|"live_provider_gaps"'
curl -s "http://localhost:8000/api/v1/scanner/history?data_degraded=true&limit=5" | python -m json.tool
```

  (If the endpoints need auth, reuse the session cookie as in DEVELOPMENT.md.)

- [ ] **Step 5: Simulated outage on the dev stack (manual acceptance, optional if no live key).** Block
  egress for the worker and confirm the gauges move:

```bash
docker-compose exec -u root celery-worker sh -c 'echo "127.0.0.1 api.polygon.io" >> /etc/hosts'
# trigger a sync that hits Polygon (e.g. Catch-Up for one ticker from the UI), then:
curl -s http://localhost:8000/metrics | grep -E '^provider_(error_rate|circuit_breaker_state)'
# expect error_rate rising and breaker_state 2 once POLYGON_CB_FAIL_MAX consecutive failures occur
docker-compose restart celery-worker   # restores /etc/hosts
```

- [ ] **Step 6: Migrations.** None are expected. Confirm with `docker-compose exec backend python -m alembic check`,
  which should report no new upgrade operations.
- [ ] **Step 7: Push.** `git push -u origin HEAD`.

## Self-review checklist (completed at plan time)

- `**Issue:** #388` line present under the title.
- No placeholders: every code step has concrete code and every command has an expected result.
- Memory lessons applied: Redis is used only for ephemeral, TTL-bounded health counters (`[AVOID]
  durable Redis state`); no new containers (`[PATTERN] extend existing services`); metrics rely on
  the shared `prometheus_multiproc` named volume, which this plan does not touch (`[AVOID] tmpfs
  named volumes`).
- Spec coverage: §3.1 (Tasks 8, 11, 13, 15), §3.2 (Task 6 table), §3.3 (Task 7 buckets and
  `max_premarket_bar_ts`), §3.4 (Tasks 3–5, 8: completion-time `data_degraded`, worker id), §3.5
  (Task 6: reuses `data_degraded` + `provider_gap`, no new field), §3.6 (Tasks 2, 11, 14), §3.7
  (Tasks 12–13), §3.8 (Task 15), §2 acceptance (Task 9 simulated outage; Tasks 10 and 12 UI/API;
  Task 14 Grafana).
