# Aggregate Gap & Staleness Detection — Design

**Status:** design  
**Date:** 2026-06-21  
**Issue:** #387  
**Branch:** refine/issue-387-data-quality--gap-staleness-detection-on

## Problem

Nothing watches the health of the data the scanner scans. Two silent-corruption classes directly distort signals and backtest results:

1. **Gaps** — missing trading-day bars per ticker in `stock_aggregates` / `futures_aggregates`. A universe ticker with holes produces wrong rolling averages, which corrupts the >4× volume judgments the scanner relies on.
2. **Staleness** — per-ticker `MAX(timestamp)` lag vs. expected freshness. A stuck Celery sync task currently fails silently — no alert, no banner, no Prometheus gauge.

This spec covers part 1 of issue #387 (gap/staleness detection only). Corporate-action handling (adjustment-state audit + re-sync policy) is a separate follow-on ticket.

## Requirements

1. A new lightweight nightly Celery task (`check_aggregate_staleness`) runs for every active universe and queries `MAX(timestamp)` per ticker + gap windows, producing structured Seq log events and updating Prometheus gauges.
2. Two Prometheus gauges are emitted per active universe: `markethawk_aggregate_gap_days` (worst gap in weekdays across tickers) and `markethawk_aggregate_staleness_hours` (worst staleness in hours across tickers), both labeled by `universe_id`.
3. A Seq `Warning` event is written when `>quality_alert_pct%` (default 20%) of an active universe's tickers are stale or gapped.
4. A new `GET /api/v1/universes/{id}/data-health` endpoint returns a compact degradation summary for the Scanner page UI.
5. The Scanner page shows a banner when `degraded=true` on the active universe's data-health response.
6. `ScannerRun` gains a `data_degraded` boolean column populated at scan start by checking the latest `UniverseQualityReport`.
7. All staleness/gap thresholds are stored in `SystemConfig` with safe code-level fallback defaults.
8. Shared gap-detection helpers (`_detect_gaps`, `_count_weekdays_between`) are extracted from `data_quality.py` into a reusable module consumed by both `DataQualityService` and the new task — no duplicated logic.

## Architecture / Approach

### Shared Gap Helpers

Extract `_detect_gaps` and `_count_weekdays_between` from `backend/app/services/data_quality.py` into `backend/app/services/quality_helpers.py`. Both `DataQualityService` and the new `check_aggregate_staleness` task import from there. This is the only prerequisite refactor; `DataQualityService` behavior is unchanged.

### New Celery Task: `check_aggregate_staleness`

**Location:** `backend/app/tasks/quality.py` (add alongside existing tasks)  
**Beat schedule:** 03:00 UTC weekdays (after `sync-stock-splits` at 01:00 UTC and the nightly scans at 02:00 UTC)

The task:

1. Loads config from `SystemConfig` (with fallback defaults):
   - `quality_staleness_hours` → `48` (a ticker is stale if newest aggregate is older than this; 48 h covers Fri→Mon without false-firing)
   - `quality_gap_min_weekdays` → `2` (a ticker is gapped if a gap window spans more than this many weekdays)
   - `quality_alert_pct` → `20` (Seq alert fires when >20% of active universe tickers are stale **or** gapped)

2. For each active `StockUniverse`:
   a. Queries `MAX(timestamp)` per active ticker from `stock_aggregates` / `futures_aggregates` (group by ticker, one round-trip per universe using aggregate functions).
   b. Classifies each ticker as stale if `now - max_ts > staleness_hours`.
   c. For gap detection, imports and calls `_detect_gaps` from `quality_helpers` against the sorted timestamps for the primary (daily) timespan only — lighter than the full multi-timespan analysis.
   d. Computes: `stale_count`, `gapped_count`, `worst_staleness_hours`, `worst_gap_days`, `affected_pct = max(stale_count, gapped_count) / active_ticker_count * 100`.

3. Emits Prometheus gauges (per universe):
   ```python
   aggregate_staleness_hours.labels(universe_id=str(universe.id)).set(worst_staleness_hours)
   aggregate_gap_days.labels(universe_id=str(universe.id)).set(worst_gap_days)
   ```
   Uses `multiprocess_mode="livemax"` (matches existing gauges; task runs in a Celery worker separate from the backend scrape process).

4. If `affected_pct > quality_alert_pct`, logs a structured `WARNING` to Seq:
   ```json
   {
     "event": "AggregateDataDegradation",
     "universe_id": 1,
     "stale_tickers": 12,
     "gapped_tickers": 3,
     "affected_pct": 25.0,
     "worst_staleness_hours": 72.1,
     "worst_gap_days": 4,
     "threshold_pct": 20
   }
   ```

### `data_degraded` Flag on `ScannerRun`

Add `data_degraded = Column(Boolean, nullable=True)` to `ScannerRun` (nullable = unknown; `False` = clean; `True` = degraded at scan time). Requires an Alembic migration.

At scan start (in `tasks/scanning.py` before the scan body), populate it:
1. Load `UniverseQualityReport` for the run's `universe_id` — a single indexed query.
2. Read `report_data.tickers` and count stale/gapped tickers using the same `quality_staleness_hours` and `quality_gap_min_weekdays` from `SystemConfig`.
3. Set `data_degraded = True` if `affected_pct > quality_alert_pct`, or if the report is absent or was generated more than 48 hours ago (treat missing/stale report as degraded).
4. `data_degraded = False` otherwise.

This does not block the scan. It is a metadata annotation — the scan proceeds regardless.

### `GET /api/v1/universes/{id}/data-health`

New endpoint in `backend/app/routers/universe.py`. Returns a compact summary derived from the latest `UniverseQualityReport`:

```json
{
  "universe_id": 1,
  "degraded": true,
  "stale_pct": 25.0,
  "gapped_pct": 8.3,
  "worst_staleness_hours": 72.1,
  "worst_gap_days": 4,
  "report_age_hours": 6.2,
  "grade": "C"
}
```

`degraded = stale_pct > quality_alert_pct OR gapped_pct > quality_alert_pct OR report absent/stale`.

If no `UniverseQualityReport` exists, returns `{"degraded": true, "stale_pct": null, ...}` (missing report = degraded). Response is cached 5 minutes (matches `universe/list` cache TTL).

### Scanner Page Banner

In `frontend/src/pages/Scanner/`, the Scanner index component calls `GET /api/v1/universes/{id}/data-health` when a universe is selected (React Query, 5-minute `staleTime`). If `degraded=true`, renders a yellow/amber banner above the results panel:

> ⚠️ **Data quality warning** — {stale_pct}% of tickers in this universe have stale or gapped data (worst: {worst_staleness_hours}h stale). Scanner results may be distorted. [Run quality analysis →]

The banner links to the existing `UniverseDetailsModal` quality tab on the Universes page. No new page or modal is needed.

### New Prometheus Metrics

Add to `backend/app/core/metrics.py`:

```python
aggregate_gap_days = Gauge(
    "markethawk_aggregate_gap_days",
    "Worst gap (weekdays) across tickers in a universe",
    ["universe_id"],
    multiprocess_mode="livemax",
)
aggregate_staleness_hours = Gauge(
    "markethawk_aggregate_staleness_hours",
    "Worst staleness (hours since newest aggregate) across tickers in a universe",
    ["universe_id"],
    multiprocess_mode="livemax",
)
```

Grafana alert rule example: `markethawk_aggregate_staleness_hours{universe_id="1"} > 48`.

On universe deletion, call `.remove(str(universe.id))` on both gauges (via the existing universe DELETE endpoint) to prevent stale label series.

## Alternatives Considered

### Option A: Schedule full `analyze_universe_quality` nightly

**Rejected.** The full `DataQualityService.analyze_universe()` fetches every OHLCV bar for every ticker×timespan combo and runs P90 coverage estimation, per-bar integrity loops, and holiday-calendar joins. Running this for all active universes nightly is disproportionately heavy. It also writes to the same `UniverseQualityReport` row the on-demand user modal reads, creating a write-race between the scheduler and interactive user requests. The nightly health sweep should not overwrite the on-demand deep report.

### Using `UniverseQualityReport.tickers[].last_bar` for staleness

Tempting shortcut, but the nightly task deliberately avoids the deep report path (Option A rejection above). Staleness requires a live `MAX(timestamp)` query rather than a potentially 24-hour-old pre-computed value. The lightweight task queries the DB directly.

### Per-ticker Prometheus gauges

High cardinality (thousands of tickers × universes). Rejected in favour of per-universe worst-case values, with per-ticker detail delegated to Seq structured events.

### `data_degraded` populated by retroactive post-scan update

Rejected. Mutating historical `ScannerRun` rows after the fact races with concurrent scans and obscures what was known at execution time. The flag must reflect scan-time knowledge.

## Assumptions

- The primary timespan used for gap detection in the nightly task is `day` / `multiplier=1` (or the most complete timespan in the universe). Minute-bar gap detection is left to the on-demand deep analysis.
- `UniverseQualityReport` is populated by at least one prior on-demand analysis before the scan-time check is meaningful. A missing report is treated as degraded.
- The nightly task runs against all universes with at least one active ticker; inactive/empty universes are skipped.
- Grafana alerting rules for the new gauges are NOT part of this spec; they are added as a follow-up or manually configured. The spec provides the example rule above as guidance.
- This spec does not touch the `DataReadinessService` (referenced in the scanner explainability spec #448) — it is a separate abstraction layer to be defined later.

## Open Questions (non-blocking)

- Should `data_degraded` be surfaced in the `/api/v1/scanner/results` response so the frontend can also warn at the result level (not just pre-scan)?
- Should the nightly task also backfill `data_degraded` on historical `ScannerRun` rows for the same universe (best-effort, low priority)?
- The issue asks for an alert to fire (>N%) but does not specify the channel. Should this go through the existing `AlertRule`/`AlertDeliveryLog` system or stay Seq/Grafana-only? Recommendation: Seq only for now (observability-layer concern, not scanner-event-level).

## File Impact Summary

| File | Change |
|---|---|
| `backend/app/services/quality_helpers.py` | **New** — extract `_detect_gaps`, `_count_weekdays_between` |
| `backend/app/services/data_quality.py` | Import from `quality_helpers`; remove local definitions |
| `backend/app/tasks/quality.py` | Add `check_aggregate_staleness` task |
| `backend/app/core/celery_app.py` | Add `aggregate-quality-nightly` beat entry (03:00 UTC weekdays) |
| `backend/app/core/metrics.py` | Add two new `Gauge` definitions |
| `backend/app/models/scanner_run.py` | Add `data_degraded` Boolean column |
| `backend/alembic/versions/` | New migration: add `scanner_runs.data_degraded` |
| `backend/app/tasks/scanning.py` | Populate `data_degraded` at scan start |
| `backend/app/routers/universe.py` | Add `GET /api/v1/universes/{id}/data-health` |
| `backend/app/schemas/universe.py` | Add `DataHealthResponse` schema |
| `frontend/src/pages/Scanner/` | Add degradation banner (React Query call + conditional render) |
| `frontend/src/api/universe.ts` | Add `getDataHealth(universeId)` client function |
