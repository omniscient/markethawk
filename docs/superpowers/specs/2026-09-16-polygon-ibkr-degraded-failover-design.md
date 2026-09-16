# Polygon↔IBKR Degraded-Feed Failover for Pre-Market Scans — Design Spec

**Issue:** #388
**Date:** 2026-09-16
**Status:** Proposed — pending implementation plan

## 1. Overview / Problem Statement

The platform's value window is pre-market (4:00–9:30 AM EST). Polygon.io is the primary
market-data source; IBKR is secondary. There is currently no defined behavior for what
happens when Polygon degrades mid-pre-market — elevated latency, empty responses, 429s past
the circuit breaker, or partial universe coverage. A scan that starts healthy and hits a
Polygon outage partway through today produces **no signal at all**: it can complete looking
"clean" while having evaluated a fraction of the universe on stale or missing data.

This spec settles the failover posture the issue asks for, and designs the concrete mechanism
to close that gap using infrastructure that (mostly) already exists in the codebase.

## 2. Requirements (from Q&A)

1. Adopt a single, explicit failover posture per failure class, recorded as an ADR.
2. Full-universe pre-market scans must never hang or complete silently "empty-but-green" during
   a Polygon degradation — they must be visibly marked degraded, with a reason, both in the UI
   and via API.
3. The Active Watchlist live path needs no new failover logic (it's already IBKR-sourced,
   independent of Polygon) but that fact must be documented so on-call doesn't go looking for
   work that doesn't exist.
4. The per-ticker (non-watchlist) live chart stream, which *is* Polygon-dependent with no IBKR
   counterpart, needs outage **detection and UI visibility**, not a fallback.
5. New Prometheus gauges expose per-provider health (latency, error rate, breaker state) as a
   rolling-window signal, feeding a new Grafana alert analogous to the existing
   `ibkr-disconnected` rule.
6. A runbook section in `deployment-guide.md` tells on-call what to check when pre-market data
   goes bad, including the per-worker scoping caveat below.
7. Acceptance: a simulated Polygon outage (blocked egress) produces the designed degraded
   behavior, not a hang or an empty-but-green scan; degraded runs are visibly marked in UI and
   queryable via API; provider health is visible in Grafana.

## 3. Architecture / Approach

### 3.1 Failover posture decision (Hybrid — option 3)

Full-universe pre-market scans: **alert-and-degrade, never switch providers.** There is no
viable provider to switch to — `IBKRDataProvider.get_bars()`/`get_snapshots()`
(`backend/app/providers/ibkr.py`) are hard stubs that unconditionally `return []`; IBKR is
futures-only at the `BaseDataProvider` interface level. Even if stock support existed, IBKR's
pacing limits (60 historical requests/10min, no duplicate requests within 15s) make bulk
scanning thousands of tickers inside the 4:00–9:30 window arithmetically impossible. This is
recorded as `docs/adr/0013-polygon-ibkr-hybrid-failover.md` so it isn't relitigated.

Active Watchlist path (`backend/live_scanner/`, `ActiveWatchlist` page): **already resilient,
no new failover work.** It streams every watchlist symbol directly from IB Gateway via
`ib_insync` (`reqMktData`/`reqRealTimeBars`), independent of `IBKRDataProvider`/
`BaseDataProvider`, and reaches the client over Redis pub/sub (`watchlist:live_data`/
`watchlist:alerts`) with no Polygon coupling anywhere in that path. Document this in the
runbook explicitly.

Per-ticker live chart stream (`GET /api/v1/live/ws/{ticker}/{resolution}`, used by
`StockDetailPage`, backed by the Polygon-only `StockWebSocketManager` in
`backend/app/services/websocket_manager.py`): **in scope for detection/visibility, explicitly
no fallback.** IBKR only streams the curated watchlist's symbols and cannot serve arbitrary
on-demand tickers — record this exclusion in the ADR.

### 3.2 Failure-class → posture table

| Failure class | Posture |
|---|---|
| Elevated latency (p95 over threshold, still returning data) | Continue scan; mark `data_degraded=true` with a `provider_gap` warning issue; emit gauge; no page. |
| 429s / circuit breaker open (`POLYGON_BREAKER.current_state == "open"`) | Stop the scan; mark degraded with a blocker-severity `provider_gap` issue; page. Never persist a completed run as if it succeeded. |
| Empty/null responses on a healthy 200 (universe-wide: no fresh pre-market minute bars) | Treat as degraded; mark the run; page. This is the concrete "empty-but-green" case (§3.3). |
| Partial universe coverage (some tickers missing pre-market data, most succeed) | Complete the run; `data_degraded=true`; warning-severity `provider_gap` issue with the coverage ratio in `detail`. |

### 3.3 Closing the "empty-but-green" gap

`run_pre_market_scan()` (`backend/app/services/pre_market_scan.py`) does **not** call Polygon
live — its per-ticker loop reads `StockAggregate` rows already persisted by a separate sync
pipeline (on-demand sync / Catch-Up / universe orchestrator, decoupled from the scan). A live
Polygon outage therefore doesn't throw inside the scan; it starves the ingestion pipeline, and
today that shows up as tickers silently failing `criteria_met["minimum_volume"]` (line ~115,
`pre_market_volume > 100000`) when `pre_market_volume` is 0 because no minute bars landed —
indistinguishable from a legitimate "didn't fire". Nothing increments `failed`, so nothing
about this reaches `scan_failed_tickers_ratio`, `ScannerRun.data_degraded`, or any alert.

`_detect()` already computes `_max_bar_ts` (freshest pre-market minute bar across the universe,
lines ~596–611) but silently no-ops when it's `None`. This is the cheapest, most direct
universe-wide ingestion-health signal already in hand:

- Treat `_max_bar_ts is None`, or `_max_bar_ts` older than a configurable threshold (default
  10 minutes; env-tunable, following the `POLYGON_CB_FAIL_MAX`-style pattern in
  `app/core/config.py`) while inside the 4:00–9:30 ET window, as a universe-wide degradation
  signal — this is the "empty responses" failure class.
- Separately, bucket per-ticker outcomes in the existing house style used by
  `liquidity_hunt.py` and `pocket_pivot.py` (a `counts` dict — `no_premarket_data`,
  `no_history`, `evaluated`, `errors` — surfaced as diagnostics), rather than overloading
  `failed`. `failed` already drives two live alerts (`scan-high-failed-ticker-ratio` at
  `scan_failed_tickers_ratio > 0.1`, and the "Pre-Market Scan Missed Slot" alert via
  `scan_last_success_timestamp`) — routing non-error "no data yet" cases into it would trip
  those on ordinary pre-open ticker sparsity, not just real outages.
- `no_premarket_data` (zero minute-bar volume, the live-outage-sensitive bucket) is the primary
  coverage signal; `no_history` (<20 daily bars — nightly-synced, insensitive to a live
  outage, and expected for new listings) stays a secondary/hygiene signal, not a degradation
  trigger.

### 3.4 Live provider-health signal: where it's read

Circuit-breaker state is in-process per worker (`core/circuit_breakers.py` docstring: *"State
is in-process per worker — no distributed coordination is needed or desired"*). The scan runs
in `celery-worker`; Polygon calls also happen from the FastAPI process. Reading
`POLYGON_BREAKER.current_state` directly inside the scan would miss a breaker tripped in a
different process.

Approach: instrument the provider layer once, at the chokepoint every Polygon call already
passes through — `backend/app/providers/massive.py` (`_get_bars_impl`,
`_get_ticker_details_impl`, `_fetch_snapshots_raw`, already carrying
`polygon_api_calls_total.labels(endpoint=...)`). On each call, record outcome + latency into a
small rolling-window record in Redis (`app/core/cache.py::get_redis()` — already the
process-scoped sync client every other cache consumer uses). This covers on-demand sync,
Catch-Up, and the universe orchestrator for free, regardless of which process or task
triggered the call, and gives the scan (running in a different worker) a real cross-process
health signal to read. Keep a local `POLYGON_BREAKER.current_state == "open"` check as an
OR'd fast path (mirrors the existing pattern in `services/normalization.py`'s
`_wait_out_open_breaker`).

`ScannerRun.data_degraded` is currently computed once, at scan **start**
(`backend/app/tasks/scanning.py::_compute_data_degraded`, called at `scanning.py:344`), purely
from the pre-existing `UniverseQualityReport`. Change the final value to be computed at
**completion**: `data_degraded = start_quality_report_degraded OR live_provider_degraded OR
coverage_shortfall`, so a run that started clean and hit an outage mid-run still ends up
correctly marked. `data_degraded`'s reason should record which worker/process observed the
degradation (see §3.6, per-worker scoping).

### 3.5 `quality_gate` schema extension (reuse, don't duplicate `data_degraded`)

The issue's "`ScannerRun.data_quality` flag (shared with the data-quality ticket)" is already
substantially built: `ScannerRun.data_degraded` (Boolean) and `ScannerRun.quality_gate`
(JSONB, backed by the `QualityGateAssessment` Pydantic model,
`backend/app/schemas/quality_gate.py`) already exist. `QualityGateIssue.code` already declares
a `provider_gap` value in `QualityIssueCode` that's documented as "defined for API stability
but not yet emitted" (`ARCHITECTURE.md`). This ticket is the natural place to start emitting
it: append a `QualityGateIssue(code=provider_gap, severity="blocker"|"warning", message=...,
detail={"provider": "polygon", "reason": ..., "coverage_ratio": ..., "worker": ...})` to
`quality_gate.issues` at scan completion when live degradation is detected, and let the
existing `_derive_verdict()` logic (in `quality_gate.py`) fold it into `verdict`/`trusted` the
same way any other issue does. `QualityGateAssessment` is `extra="forbid"`, so this means
adding declared support for the code path that emits `provider_gap`, not inventing new JSON
shape.

Do not introduce a second, parallel "data_quality" field — reuse `data_degraded` +
`quality_gate.issues[].code=provider_gap` as the single source of truth, consistent with how
the existing historical-quality-report degradation already works.

### 3.6 New Prometheus gauges + Grafana alert

Add, in `backend/app/core/metrics.py` alongside the existing `ibkr_connection_status`:

- `provider_request_latency_p95_seconds{provider}` (Gauge) — rolling p95 latency.
- `provider_error_rate{provider}` (Gauge) — rolling error rate.
- `provider_circuit_breaker_state{provider}` (Gauge; 0=closed, 1=half-open, 2=open).
- A Polygon WS connection gauge, e.g. `polygon_ws_connected` (Gauge) — surfaces
  `StockWebSocketManager._connected`, which already exists; no new probing infra needed for
  the per-ticker chart stream's health.

Window sizes follow existing precedent rather than inventing new ones: 5 minutes for error
rate (matches the existing Celery failure-rate alert's `[5m]`/`for: 5m`), 15 minutes for
latency p95 (matches the existing scanner p95 alert's 900s range and the
`scan_data_to_detection_seconds` dashboard's `[15m]` rate window). Exact thresholds (e.g. what
error rate counts as "degraded") are env-tunable settings in `app/core/config.py`, following
the `POLYGON_CB_FAIL_MAX`/`POLYGON_CB_RESET_TIMEOUT` pattern — defaults chosen in the
implementation plan, not fixed here, since they're safe to tune post-merge.

Add one new rule to `grafana/provisioning/alerting/rules.yaml`, in the existing format
(`ibkr-disconnected` is the template — POSTs to `backend:8000/api/v1/alerts/infrastructure`)
for Polygon degradation (breaker open, or error-rate/latency gauge over threshold, or
`polygon_ws_connected == 0` for >2min). There is no `rule_files:` entry in
`monitoring/prometheus/prometheus.yml` — all alerting in this repo is Grafana-side; this new
rule belongs there, not in a new Prometheus rules file. Add the new metrics to the metrics
table in `ARCHITECTURE.md` and to the "Scanner Performance"/"Infrastructure" Grafana
dashboards alongside the existing Polygon call-rate and IBKR-status panels.

### 3.7 Frontend

`ScannerRun.data_degraded` is currently written but read by zero frontend code (`quality_gate`
is rendered in `ResultsPanel` via `scanResults.quality_gate`, but the boolean itself and any
`provider_gap` issue are not surfaced). Wire it into `ResultsPanel`: render a degraded banner
(reusing the visual language of the existing "Data quality degraded" banner in
`Scanner/index.tsx`, which is currently driven by the unrelated `/data-health` staleness
signal) whenever `quality_gate.issues` contains a `provider_gap` entry, showing the
human-readable `message` and `detail.coverage_ratio` where present.

For the per-ticker chart stream, add a lightweight "live feed unavailable — showing last known
data" badge on `StockDetailPage`, driven off `polygon_ws_connected` (via the existing
`/metrics`-derived state or a small status field on the ticker WS payload — implementation
detail for the plan phase), reusing the same banner visual language.

### 3.8 Runbook (deployment-guide.md)

Add a "Pre-market data degradation" section covering: how to distinguish a
`quality_gate`-reported `provider_gap` (live outage) from the older staleness/gap-based
`/data-health` banner (historical); where to check current breaker state per process
(`POLYGON_BREAKER` is in-process/per-worker — a breaker tripped in `celery-worker` may read
`closed` in the API process and vice versa, so a partial trip must not be misread as a full
outage); the new Grafana panels/alert to check first; and that the Active Watchlist path needs
no troubleshooting for Polygon outages since it's IBKR-sourced independently.

## 4. Alternatives Considered

1. **Alert-and-degrade only, no distinction by failure class or path.** Rejected: doesn't
   address the issue's explicit ask for a hybrid design, and leaves the Active Watchlist's
   existing resilience undocumented (risk: someone builds redundant failover work for a path
   that doesn't need it).
2. **Auto-failover for quotes/bars via `IBKRDataProvider`.** Rejected: `get_bars()`/
   `get_snapshots()` are non-functional stubs for stocks today; building real IBKR stock
   market-data support is a large, separate undertaking outside this ticket's size budget, and
   IBKR's pacing limits make it structurally unusable for full-universe scans regardless of
   stub status.
3. **Hybrid (chosen).** Matches both the issue's own lean and the codebase's actual
   capabilities: the watchlist path is already resilient by construction; full-universe scans
   get alert-and-degrade using infrastructure (circuit breakers, `DataProviderFactory`,
   `quality_gate`) that's already mostly built.

## 5. Open Questions (non-blocking)

- Exact latency/error-rate thresholds for the new gauges — deferred to the plan phase as
  env-tunable settings (§3.6).
- Exact staleness threshold for "no fresh pre-market minute bars" (default proposed: 10
  minutes) — confirm during planning against real pre-market bar cadence.
- Whether `no_history`/`no_premarket_data` diagnostics counters should also be wired into the
  existing `_run_universe_scan_logic` diagnostics payload (`scanning.py`), which today declares
  but never populates `no_data`/`no_prior_close`/`no_baseline` — worth fixing opportunistically
  but not required for this ticket's acceptance criteria.

## 6. Assumptions (flagged)

- Redis is available and suitable for the cross-process rolling health record (already
  mandatory infra per `app/core/cache.py`).
- The 10-minute default staleness threshold for "no fresh minute bars" is a reasonable
  first cut; not validated against production pre-market bar arrival cadence.
- `provider_gap` is safe to start emitting without breaking existing `quality_gate` consumers,
  since `QualityGateIssue.code` already declares it as a valid enum value and consumers must
  already handle an open set of issue codes.
