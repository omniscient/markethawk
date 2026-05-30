# Pocket Pivot Scanner — Design Spec

**Date:** 2026-05-30
**Status:** Design — pending implementation
**Issue:** #140
**Author:** Refinement session with MarketHawk Factory

---

## 1. Overview

### Problem

Issue #140 requests a new scanner type for the "TA plot volume pocket pivot" pattern, referencing a known technical-analysis system popularised by Gil Morales and Chris Kacher. No pocket-pivot detection exists anywhere in the current codebase. The project's existing scanners cover off-hours liquidity anomalies (`liquidity_hunt_pre/post`) and oversold bounces, but nothing detects institutional accumulation quietly occurring *within* a consolidation base during a regular session.

### What a Pocket Pivot Is

A pocket pivot is a specific end-of-day volume pattern:

- The stock closes up on the day (close ≥ prior close — an up day).
- The day's total session volume exceeds the **highest single down-day volume** recorded in the prior 10 trading days.

The pattern signals institutional accumulation: a fund buys size on an up day, and the volume absorbed is heavier than anything the bears managed on any of the preceding down days. Unlike a breakout, the pocket pivot does not require a gap, a new high, or a move above a resistance level. It can occur quietly inside a base or consolidation — the "pocket" is exactly this low-visibility quality.

The original Morales/Kacher definition uses a 10-day lookback for down-day volume comparison. This spec implements the classic definition using daily bars, consistent with the codebase's existing daily-bar architecture for volume-pattern detection.

### Why It Matters

The pocket pivot fills a gap in the scanner suite: the other scanners detect price and off-hours anomalies, but none detect the specific combination of (a) up close, (b) volume that overwhelms prior selling pressure. This is a meaningful institutional accumulation signal that MarketHawk users currently have no automated way to surface.

---

## 2. Requirements

### Functional

- **Core criterion**: For each ticker on each trading day, check whether the up-day condition holds AND today's total session volume exceeds the maximum single down-day volume in the prior 10 trading days.
- **Up-day definition**: `today_close >= prior_trading_day_close` (prior regular close, not today's open).
- **Down-day identification**: Any day in the lookback window where `close < prior_close` for that day.
- **Volume comparison**: `today_volume > max_down_day_volume_in_lookback`. Strict inequality — exactly matching the max does not qualify.
- **Minimum price floor**: Today's close must be ≥ $5.00. Configurable via `ScannerConfig.parameters`.
- **Minimum volume floor**: Today's session volume must be ≥ 100,000 shares. Configurable via `ScannerConfig.parameters`.
- **Lookback window**: 10 trading days (days with actual bar data). Configurable via `ScannerConfig.parameters`.
- **Minimum data requirement**: If fewer than 5 prior trading days of daily-bar data exist for the ticker, skip it (insufficient baseline).
- **No down-day requirement**: If there are no down days in the lookback window (all prior 10 days were up days), the volume criterion is treated as **not satisfied** — there is no meaningful max-down-day-volume to compare against.
- **No gap requirement**: The pattern explicitly allows pocket pivots with no gap. A gap is not a disqualifier or a requirement.
- **No MA filter in core scanner**: MA proximity is not a core criterion. If desired, it should be added as a `signal_ranker` weight.
- **No base/consolidation filter in core scanner**: Consolidation proximity is not a core criterion. Same rationale.

### Non-Functional

- **EOD batch only**: No intraday or pre-market detection. Runs once per trading day after close.
- **Schedule**: 02:00 UTC Mon–Fri (same slot as `liquidity_hunt_scheduled`), ensuring all daily bars are locked in.
- **Data source**: `StockAggregate` table, `timespan='day'` rows. No minute-bar queries.
- **On-demand support**: Historical backfill via the existing `/api/v1/scanner/run` REST endpoint — no additional code needed.
- **Output**: `ScannerEvent` rows with `scanner_type='pocket_pivot'`, indicators JSONB, and metadata.
- **Signal ranking**: Compatible with the existing `signal_ranker.py` weighted-sum scorer via standard indicator field names.

---

## 3. Algorithm

### Per (ticker, event_date)

1. **Fetch today's daily bar** — query `StockAggregate` for `ticker`, `timespan='day'`, `timestamp` on `event_date`. Extract `close` (today's close), `volume` (today's total session volume).
   - If no daily bar exists for `event_date` (holiday, halt, data gap), skip this ticker.

2. **Fetch prior day's close** — query `StockAggregate` for the most recent `timespan='day'` bar strictly before `event_date`. Extract `close` as `prior_close`.
   - If `prior_close` is missing (first bar ever), skip this ticker.

3. **Check up-day condition** — `today_close >= prior_close`. If false, skip (not an up day).

4. **Fetch lookback window** — query `StockAggregate` for `ticker`, `timespan='day'`, `timestamp` strictly before `event_date`, ordered descending, limited to the 10 most recent trading days with data (i.e., up to 10 rows, all of which have actual bar data).
   - If fewer than 5 rows returned, skip ticker (insufficient baseline).

5. **Classify lookback days as up or down** — for each of the N lookback bars (up to 10), determine its direction by comparing that bar's close to the close of the bar immediately preceding it in the series. A day is a **down day** if its close < the close of the day before it.
   - Note: this requires fetching N+1 bars (10 lookback days plus the one before them) to have a prior close for each lookback day.

6. **Identify down-day volumes** — collect the `volume` of every down-day bar in the lookback set. If the list is empty (no down days), skip ticker — criterion cannot be evaluated.

7. **Compute max down-day volume** — `max_down_day_vol = max(down_day_volumes)`.

8. **Check volume criterion** — `today_volume > max_down_day_vol`. If false, skip.

9. **Apply materiality floors**:
   - `today_close < price_floor` → skip.
   - `today_volume < volume_floor` → skip.

10. **Persist event** — call `_save_event` with `scanner_type='pocket_pivot'` and the indicators payload (see Section 4).

### Default Thresholds

All thresholds are stored in `ScannerConfig.parameters` and can be overridden per config:

| Parameter | Default | Description |
|---|---|---|
| `lookback_days` | `10` | Number of prior trading days to examine for down-day volumes |
| `min_lookback_days` | `5` | Minimum days of data required to proceed |
| `price_floor` | `5.00` | Minimum close price (USD) |
| `volume_floor` | `100000` | Minimum session volume (shares) on the pivot day |

### Fetch Pattern (Daily Bars)

To classify N lookback days, the query fetches up to N+1 daily bars before `event_date`:

```python
rows = (
    db.query(StockAggregate)
    .filter(
        StockAggregate.ticker == ticker,
        StockAggregate.timespan == "day",
        StockAggregate.timestamp < event_date_start_utc,
    )
    .order_by(desc(StockAggregate.timestamp))
    .limit(lookback_days + 1)
    .all()
)
rows.reverse()  # ascending order: oldest first
```

Then for each of `rows[-lookback_days:]` (the N most recent), classify as down if `row.close < rows[i-1].close`.

---

## 4. Indicators Payload

Stored in `ScannerEvent.indicators` (JSONB). Field names follow existing conventions where possible.

```json
{
  "today_close": 14.72,
  "prior_close": 14.15,
  "up_day_pct": 0.0403,
  "today_volume": 487000,
  "max_down_day_vol": 312000,
  "volume_over_max_down_pct": 0.5609,
  "down_days_in_lookback": 4,
  "lookback_days_available": 10,
  "volume_floor": 100000,
  "price_floor": 5.00,
  "split_in_lookback": false
}
```

| Field | Type | Description |
|---|---|---|
| `today_close` | float | Today's closing price |
| `prior_close` | float | Prior trading day's closing price |
| `up_day_pct` | float | `(today_close - prior_close) / prior_close`, rounded to 4 dp |
| `today_volume` | int | Today's total session volume (shares) |
| `max_down_day_vol` | int | Highest down-day volume in the lookback window |
| `volume_over_max_down_pct` | float | `(today_volume / max_down_day_vol) - 1.0`, rounded to 4 dp |
| `down_days_in_lookback` | int | Count of down days identified in the lookback window |
| `lookback_days_available` | int | Actual trading days found (may be < `lookback_days` near IPO) |
| `volume_floor` | int | Absolute volume floor applied (from config) |
| `price_floor` | float | Absolute price floor applied (from config) |
| `split_in_lookback` | bool | `true` if a stock split occurred within the lookback window |

Existing enrichment fields (`market_cap`, `outstanding_shares`, `recent_split_date`, `catalyst_tags`, `catalyst_summary`, `float_rotation_pct`) are stored in `ScannerEvent.metadata_` via the shared `_get_enrichment` helper from `liquidity_hunt.py`, unchanged.

### Signal Ranker Compatibility

The `signal_ranker.py` weighted-sum scorer can pick up `volume_over_max_down_pct` as a normalized feature by adding it to `_NORM_CAPS` (suggested cap: `5.0`, i.e., 500% over max-down-day volume). No code change is required to the core scanner; it is a separate tuning step.

---

## 5. Scanner Registration

**Module key**: `pocket_pivot`
**Display name**: `Pocket Pivot`
**Description**: `Detects up-days where session volume exceeds the highest down-day volume in the prior 10 trading days (classic Morales/Kacher pocket pivot).`

Registration at module import time:

```python
from app.services.scan_orchestrator import ScannerDescriptor, register

register(
    ScannerDescriptor(
        key="pocket_pivot",
        display_name="Pocket Pivot",
        description=(
            "Detects up-days where session volume exceeds the highest "
            "down-day volume in the prior 10 trading days "
            "(classic Morales/Kacher pocket pivot)."
        ),
        run=_orchestrator_run,
        supports_date_range=True,
    )
)
```

`_orchestrator_run` adapts the standard `ScannerFn(tickers, db, event_date)` signature to `run_pocket_pivot_scan(tickers, db, start_date=event_date, end_date=event_date)`.

---

## 6. Scheduling

### Nightly Celery Beat Job

Add to `backend/app/core/celery_app.py`:

```python
# Pocket pivot scan: runs at 02:00 UTC Mon–Fri
# Daily bars are locked in by this time; 02:00 UTC = 21:00 EST / 22:00 EDT — always post-close.
"run-pocket-pivot-scan-evening": {
    "task": "app.tasks.run_pocket_pivot_scheduled",
    "schedule": crontab(minute="0", hour="2", day_of_week="1-5"),
},
```

This runs in the same time slot as `run-liquidity-hunt-scan-evening`, which is intentional — both are EOD daily-bar scanners and the slot is already validated as post-close for all US market sessions.

### Scheduled Task

New Celery task `run_pocket_pivot_scheduled` in `backend/app/tasks/scanning.py`, mirroring `run_liquidity_hunt_scheduled`:

- Query all `ScannerConfig` rows with `scanner_type='pocket_pivot'` and `is_active=True`.
- For each active config, resolve `universe_id` from `parameters`, query the universe's active `MonitoredStock` list, and call `run_pocket_pivot_scan(tickers, db, start_date=event_date, end_date=event_date)`.
- Log result count per universe.

### On-Demand Support

No additional code required. The existing `/api/v1/scanner/run` endpoint uses `scan_orchestrator.enqueue_scan`, which dispatches by `scanner_type` via `run_universe_scan`. Once `pocket_pivot` is registered in the orchestrator, the on-demand path works automatically for historical backfills.

### `compute_next_run` Update

Add `'pocket_pivot'` to the set of scheduled types in `scan_orchestrator.compute_next_run()` so the frontend can display the next scheduled run time:

```python
if scanner_type not in {
    "liquidity_hunt",
    "liquidity_hunt_pre",
    "liquidity_hunt_post",
    "pocket_pivot",
}:
    return None
```

---

## 7. Code Organization

| File | Change |
|---|---|
| `backend/app/services/pocket_pivot.py` | **NEW** — algorithm, helpers, and orchestrator self-registration |
| `backend/app/tasks/scanning.py` | Add `run_pocket_pivot_scheduled` Celery task (mirror of `run_liquidity_hunt_scheduled`) |
| `backend/app/core/celery_app.py` | Add `run-pocket-pivot-scan-evening` to `beat_schedule` |
| `backend/app/services/scan_orchestrator.py` | Add `'pocket_pivot'` to `compute_next_run` scheduled-type set |
| `backend/app/alembic/versions/<rev>_seed_pocket_pivot_scanner_config.py` | **NEW** — idempotent seed migration for default `ScannerConfig` row |
| `backend/tests/services/test_pocket_pivot.py` | **NEW** — unit tests (see Section 9) |

### `pocket_pivot.py` Public API

```python
async def run_pocket_pivot_scan(
    tickers: list[str],
    db: Session,
    start_date: date | None = None,
    end_date: date | None = None,
    config: dict | None = None,
    diagnostics_out: dict | None = None,
) -> list[dict[str, Any]]: ...
```

`config` accepts `ScannerConfig.parameters`; if `None`, module-level `DEFAULT_CONFIG` is used. `diagnostics_out` is populated with per-bucket counts matching the pattern in `liquidity_hunt.py`.

No changes to `scanner.py` — pocket pivot is a standalone module, not added to the monolithic scanner service.

---

## 8. Edge Cases

| Case | Handling |
|---|---|
| **Fewer than 5 prior trading days of data** | Skip ticker — insufficient baseline. Counted in `diagnostics_out["no_baseline"]`. |
| **No down days in lookback window** | Skip ticker — the core criterion (`today_vol > max_down_day_vol`) cannot be evaluated without any down-day reference. Not an error; counted in `diagnostics_out["no_down_days"]`. |
| **Stock split within lookback window** | Set `split_in_lookback: true` in indicators. Do not skip — the event still fires, but the `split_in_lookback` flag allows reviewers to discount or filter it. Check is identical to `liquidity_hunt.py` (split date within 28 calendar days of `event_date`). |
| **Exactly one down day in lookback** | Valid — `max_down_day_vol` is that single day's volume. The criterion fires if today exceeds it. |
| **Today is a down day on its own** | The up-day check (`today_close >= prior_close`) fails first. Skip. No need to evaluate volume. |
| **All 10 lookback days are down days** | Valid but unusual; `max_down_day_vol` is computed normally from all 10. |
| **Missing daily bar for `event_date`** | `_get_today_bar` returns `None`. Skip ticker. Counted in `diagnostics_out["no_today_bar"]`. |
| **Missing prior close** | `_get_prior_close` returns `None`. Skip ticker. Counted in `diagnostics_out["no_prior_close"]`. |
| **`event_date` is today, market still open** | Caller's responsibility. The scheduled job runs at 02:00 UTC, always post-close. On-demand callers passing today's date mid-session will see an incomplete daily bar; the results are unreliable but the code does not block the request — documented as a known limitation. |
| **Ticker near IPO with 5–9 days of data** | `lookback_days_available` is < 10 but ≥ `min_lookback_days`. The scanner proceeds using only the available days. `lookback_days_available` is recorded in the indicators payload for reviewer awareness. |
| **Enrichment failure** | Log a warning; proceed with empty enrichment dict (same fallback as `liquidity_hunt.py`). Never skip an event due to enrichment failure. |

---

## 9. Testing

### Unit Tests — `backend/tests/services/test_pocket_pivot.py`

All tests use in-memory `StockAggregate` fixture rows of `timespan='day'` spanning 15 trading days for a synthetic ticker.

| # | Scenario | Expected |
|---|---|---|
| 1 | **Clean pocket pivot** — today's close > prior close (up day), today's volume (350K) > max down-day volume in prior 10 days (280K), price ≥ $5, volume ≥ 100K | Event fires; `scanner_type='pocket_pivot'`; `volume_over_max_down_pct` ≈ 0.25 |
| 2 | **Down day** — today's close < prior close | No event; up-day check fails |
| 3 | **Volume below max down-day** — today is an up day, today's volume (200K) < max down-day volume (280K) | No event; volume criterion fails |
| 4 | **Volume equals max down-day exactly** — today's volume == max down-day volume | No event; strict inequality (`>`) required |
| 5 | **Below price floor** — all other criteria pass, today's close = $4.50 | No event; price floor fails |
| 6 | **Below volume floor** — all other criteria pass, today's volume = 80K | No event; volume floor fails |
| 7 | **Only 4 prior days of data** | Skip; no event; counted in `no_baseline` |
| 8 | **No down days in lookback** — all prior 10 days were up days | Skip; no event; counted in `no_down_days` |
| 9 | **Stock split 10 days before event_date** | Event fires; `split_in_lookback == true` in indicators |
| 10 | **Exactly 5 prior days (near IPO)** — volume criterion passes | Event fires; `lookback_days_available == 5` in indicators |
| 11 | **Missing today's daily bar** | Skip; no event; counted in `no_today_bar` |
| 12 | **`diagnostics_out` populated correctly** — run over a batch of 3 tickers, 2 qualifying | `diagnostics_out["evaluated"] == 3`, `diagnostics_out["fired"] == 2` |

### Integration Validation

Per `CLAUDE.md` development rules:

1. After deployment, trigger the on-demand scan for a known historical date with a ticker that should show a pocket pivot (select a day where the ticker closed up with heavy volume after a quiet prior week).
2. Confirm the returned `indicators` payload matches the expected shape (all fields present, no nulls on required fields).
3. Confirm `ScannerEvent` row is persisted with `scanner_type='pocket_pivot'`.
4. Manually cross-check the event against a daily chart — the day should visually show heavy volume on a quiet-to-moderate up-close day within a base or consolidation.
5. Verify the nightly Celery beat fires at 02:00 UTC using Flower (`http://localhost:5555`) and produces log output matching the expected format.

---

## 10. Out of Scope

- **Intraday / live pocket pivot detection** — The live scanner (`backend/live_scanner/conditions.py`) is stateless and runs on minute bars. Adding a live pocket pivot condition would require database-backed historical state loading, which is architecturally incompatible with the current live conditions model. Deferred to a separate future issue.
- **Moving-average filter as a core criterion** — MA proximity is explicitly excluded from the core scanner. If desired, it belongs in `signal_ranker.py` as a configurable scoring weight, not as a gating criterion.
- **Base/consolidation filter** — Algorithmic detection of "within a consolidation base" is too ambiguous to implement as a core criterion. Deferred to signal ranker if needed.
- **Down-pivot variant** — A down-close day where volume exceeds max up-day volume (distribution signal). Excluded; the pattern is accumulation-specific. Could be a separate issue.
- **Gap filter** — A gap-up pocket pivot is a specific sub-variant. Not filtered for or against; gaps are visible in the daily bar and can be inspected by reviewers.
- **Frontend changes** — The Scanner page already renders any `scanner_type` via the generic event list. No UI changes are required for `pocket_pivot` events to appear.
- **Refactoring other scanners** — `pre_market_scan.py`, `oversold_bounce_scan.py`, and the legacy `scanner.py` monolith are untouched.
- **Pre-aggregated daily rollup table** — If query-time daily-bar aggregation becomes a performance bottleneck, that is a separate architectural initiative.

---

## 11. Alternatives Considered

### Alternative 1: Intraday Pocket Pivot Detection (Compare Accumulated Volume to Prior Down-Day High)

**Description**: Add a live condition to `backend/live_scanner/conditions.py` that monitors intraday accumulated volume in real time. When the day's accumulated volume exceeds the historical max-down-day volume (pre-loaded at session start), fire an intraday alert.

**Why rejected**: The classic pocket pivot definition is an end-of-day pattern that requires the full session close to confirm the up-day condition. An intraday signal would be a fundamentally different pattern (a volume-rate anomaly, not a confirmed pocket pivot). Additionally, the live scanner architecture is explicitly stateless per bar — loading 10-day historical baselines per ticker at minute-bar frequency would require a significant architectural change (Redis cache layer with daily refresh). This complexity is not justified for a first implementation. The EOD batch approach is correct for this pattern.

### Alternative 2: Additional MA and Base-Proximity Filters as Core Criteria

**Description**: Gate the scanner on `close > SMA_50` and `close within 15% of 52-week high` (a "within a base" proxy), matching popular pocket-pivot screener implementations.

**Why rejected**: Adding these filters reduces sensitivity (misses valid pocket pivots occurring below the 50-day MA or outside the 15% band) and introduces a hidden parameterization dependency (MA lookback, % band). The project's `signal_ranker.py` already provides a post-hoc scoring layer purpose-built for this kind of quality differentiation. The correct division of responsibility is: core scanner = detect the pattern (up day, volume exceeds max down-day); signal ranker = score for quality context (MA proximity, consolidation depth, float rotation). This also matches the philosophy in `liquidity_hunt.py`, which does not encode trend filters in its core criteria.

### Alternative 3: Use Minute Bars with Session Flags Instead of Daily Bars

**Description**: Compute the pocket pivot using minute-bar data (same approach as `liquidity_hunt.py`) by summing volumes for the regular session and comparing to a rolling baseline built from minute-bar daily sums.

**Why rejected**: Daily bars (`timespan='day'`) are available in `StockAggregate` and are the semantically correct data source for an EOD daily pattern. Using minute bars would require aggregating O(390 rows/day × 10 days) per ticker instead of reading 11 daily bar rows. The daily-bar approach is simpler, faster, and less error-prone. The liquidity hunt scanner uses minute bars specifically because it needs intraday session segmentation (pre/post/regular windows). Pocket pivot only needs full-session daily totals, making daily bars the right choice.

---

## 12. Assumptions

- **Daily bars are available and up to date** before 02:00 UTC on weekdays. This matches the existing assumption in `run-liquidity-hunt-scan-evening` and has been validated in production. If the data ingestion pipeline is delayed past 02:00 UTC, the pocket pivot scheduled job will run on stale or missing data; this is an existing system-level risk, not specific to this scanner.
- **`StockAggregate.timespan='day'` rows represent complete sessions** (open, high, low, close, volume for the full regular session). The scanner does not attempt to reconstruct daily bars from minute aggregates.
- **`prior_close` for up-day determination is the prior day's daily bar close**, not the prior day's minute-bar final close. If a daily bar is missing for the prior day (data gap), the scanner skips the ticker rather than falling back to minute bars. This is simpler and more conservative than the liquidity hunt fallback.
- **Down-day classification uses daily bar close vs. the immediately preceding daily bar close** — not close vs. open. This matches the Morales/Kacher definition.
- **Celery runs in UTC** (`celery_app.py` does not set `timezone`; beat_schedule hours are UTC). The 02:00 UTC schedule is validated against the existing liquidity hunt job in production.
- **`ScannerConfig.parameters.universe_id`** identifies the universe of tickers to scan. The scheduled task resolves active `MonitoredStock` rows from this universe at run time, matching the liquidity hunt scheduled task pattern exactly.
- **The `_save_event` helper from `alert_service.py`** is the correct persistence layer (same as `liquidity_hunt.py`). No direct ORM writes to `ScannerEvent`.
