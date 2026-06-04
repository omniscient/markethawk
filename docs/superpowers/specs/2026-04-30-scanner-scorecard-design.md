# Scanner Scorecard — Outcome Tracking & Signal Quality Analysis

**Date**: 2026-04-30
**Status**: Approved

## Problem

MarketHawk scans for pre-market volume spikes, liquidity hunts, and other patterns — but there is no mechanism to track what happens after a signal fires. Without post-signal outcome data, there is no way to measure signal quality, detect alpha decay, or determine which scanner configurations produce actionable vs. noisy signals. The EdgeExplorer page exists but relies on fragile JSONB extraction from `ScannerEvent.indicators`, which only captures signal-time data, not outcomes.

## Solution

A **Scanner Scorecard** system that:

1. Automatically tracks post-signal price action for every scanner event at configurable intervals
2. Computes industry-standard signal quality metrics (MFE, MAE, R-multiple, expectancy, profit factor)
3. Provides a shared data readiness layer so all subsystems can declare and validate their data requirements
4. Replaces the brittle stats service with reliable outcome-backed queries for EdgeExplorer

## Data Model

### ScannerOutcomeSnapshot

One row per (event x interval). Captures price action at a specific time offset from the signal.

| Column | Type | Purpose |
|--------|------|---------|
| `id` | Integer PK | Auto-increment |
| `scanner_event_id` | FK -> scanner_events.id | Links to the originating signal |
| `interval_key` | String(10) | `"1h"`, `"4h"`, `"eod"`, `"1d"`, `"2d"`, `"5d"` |
| `reference_price` | Numeric | Price at signal time (anchor for %change) |
| `snapshot_price` | Numeric | Price at this interval |
| `pct_change` | Numeric | % change from reference price |
| `high_since_signal` | Numeric | Highest price between signal and this interval |
| `low_since_signal` | Numeric | Lowest price between signal and this interval |
| `volume_since_signal` | BigInteger | Cumulative volume from signal to this interval |
| `captured_at` | DateTime | When this snapshot was recorded |
| `status` | String(20) | `"pending"`, `"captured"`, `"failed"`, `"market_closed"` |

**Indexes**: `(scanner_event_id, interval_key)` unique, `(status)` for the Celery job query.

### ScannerOutcomeSummary

One row per event, derived from its snapshots. This is the primary table EdgeExplorer queries.

| Column | Type | Purpose |
|--------|------|---------|
| `id` | Integer PK | Auto-increment |
| `scanner_event_id` | FK -> scanner_events.id, unique | One summary per event |
| `reference_price` | Numeric | Signal-time price |
| `mfe_pct` | Numeric | Maximum Favorable Excursion % |
| `mfe_time_minutes` | Integer | Minutes from signal to MFE |
| `mae_pct` | Numeric | Maximum Adverse Excursion % (negative) |
| `mae_time_minutes` | Integer | Minutes from signal to MAE |
| `mfe_mae_ratio` | Numeric | MFE / abs(MAE) — reward-to-pain ratio |
| `r_multiple` | Numeric | Move as multiples of ATR-based risk |
| `eod_pct_change` | Numeric | End-of-day return for fast filtering |
| `follow_through` | Boolean | Did the move exceed the configured threshold? |
| `gap_filled` | Boolean, nullable | Only populated for gap-type scanners |
| `is_complete` | Boolean | All configured intervals captured? |
| `completed_at` | DateTime, nullable | When the last interval was captured |

**Indexes**: `(scanner_event_id)` unique, `(is_complete)`.

### ScannerConfig Changes

Two new JSONB columns added to the existing `scanner_configs` table:

#### outcome_config

Defines how outcomes are measured for this scanner type.

```json
{
  "intervals": ["1h", "4h", "eod", "1d", "2d", "5d"],
  "follow_through_threshold_pct": 2.0,
  "reference_price_source": "opening_price",
  "extra_metrics": ["gap_filled"]
}
```

- `intervals`: Which time offsets to track. Swing-focused defaults.
- `follow_through_threshold_pct`: Minimum % move in the expected direction to count as follow-through. This threshold also defines "win" vs. "loss" for win rate calculations — a signal that achieves at least this % move at EOD is a win.
- `reference_price_source`: Which `ScannerEvent` field to use as the baseline price. Typically `"opening_price"` but could be `"previous_close"` for overnight gap analysis.
- `extra_metrics`: Scanner-specific boolean metrics to compute (e.g. `"gap_filled"` for gap scanners).

#### data_requirements

Declares the aggregate timespans and lookback this scanner type needs to function.

```json
{
  "timespans": [
    {"timespan": "minute", "multiplier": 1, "lookback_days": 5},
    {"timespan": "hour", "multiplier": 1, "lookback_days": 30},
    {"timespan": "day", "multiplier": 1, "lookback_days": 90}
  ]
}
```

Any subsystem (scanner runs, outcome capture, edge analysis) can query this to know what data must be present before proceeding.

## Data Readiness Service

New shared service at `backend/app/services/data_readiness.py`.

### Purpose

Provides a single point of truth for "does the required aggregate data exist for this ticker and scanner type?" Any subsystem can call it before doing work.

### Interface

```python
@dataclass
class TimespanCoverage:
    timespan: str        # "minute", "hour", "day"
    multiplier: int
    required_from: date
    required_to: date
    available_from: date | None
    available_to: date | None
    gap_ranges: list[tuple[date, date]]
    is_ready: bool

@dataclass
class ReadinessReport:
    ticker: str
    scanner_type: str
    coverages: list[TimespanCoverage]
    is_ready: bool       # True only if all timespans are covered
    missing_summary: str # Human-readable, e.g. "minute bars missing Apr 25-28"
```

### Methods

| Method | Purpose |
|--------|---------|
| `check(ticker, scanner_type) -> ReadinessReport` | Queries `stock_aggregates` for each required timespan/lookback. Returns coverage details. |
| `ensure(ticker, scanner_type) -> bool` | Calls `check`, then fetches missing data from Polygon for any gaps. Returns True when all requirements are satisfied. Respects Polygon rate limits via existing provider layer. |
| `check_batch(tickers, scanner_type) -> dict[str, ReadinessReport]` | Batch version for universe-level scans. |

### Integration Points

- **Scanner runs**: Before scanning a universe, call `check_batch`. Skip or auto-fetch for tickers with gaps. Log which were skipped.
- **Outcome capture job**: Before computing a snapshot, call `check`. If data missing, call `ensure` to fetch it. If fetch fails, mark snapshot `"failed"` with reason.
- **EdgeExplorer / Stats**: Can surface data quality warnings (e.g. "analysis based on 85% complete data").
- **UI**: Readiness status can surface on the stock detail page or scanner results.

## Celery Job Architecture

### capture_outcome_snapshots (periodic task)

**Schedule**:
- Every 30 minutes during market hours (9:30-16:00 ET)
- Once at 16:30 ET (post-close cleanup for EOD snapshots)
- Once daily at 20:00 ET (multi-day interval snapshots: +1d, +2d, +5d)

**Job logic per run**:

1. Query all `ScannerOutcomeSnapshot` rows with `status = "pending"` whose interval time has elapsed.
2. For each snapshot, use `DataReadinessService.check()` to verify required aggregate data exists. If missing, call `ensure()` to fetch it.
3. Compute from `stock_aggregates` minute bars:
   - `snapshot_price` — price at the interval offset
   - `pct_change` — % change from `reference_price`
   - `high_since_signal` / `low_since_signal` — extremes in the window
   - `volume_since_signal` — cumulative volume
4. Set status to `"captured"` (or `"failed"` if data unavailable after fetch attempt, `"market_closed"` if interval falls on holiday/weekend).
5. After capturing snapshots, check if any event now has all intervals captured. If so, recompute its `ScannerOutcomeSummary`:
   - MFE = max of all `high_since_signal` % changes
   - MAE = min of all `low_since_signal` % changes
   - Time-to-MFE/MAE derived from which snapshot interval contains the extreme
   - R-multiple = MFE / ATR (ATR sourced from daily bars)
   - follow_through = `eod_pct_change >= follow_through_threshold_pct`
   - gap_filled = signal gap was fully retraced (gap scanners only)
   - is_complete = True, completed_at = now

### Snapshot creation trigger

When a `ScannerEvent` is created, a post-insert hook generates pending `ScannerOutcomeSnapshot` rows based on that scanner type's `outcome_config.intervals`. This happens inline in the scanner service — no separate Celery task needed.

### Summary recomputation

The `ScannerOutcomeSummary` row is upserted every time a new snapshot is captured for that event. This provides progressively more accurate MFE/MAE values as intervals fill in, rather than waiting for the full +5d window.

## Stats Service Refactor

The existing `StatsService` in `backend/app/services/stats.py` gets new methods that query outcome tables instead of parsing indicators JSONB.

| Method | Source Table | Purpose |
|--------|-------------|---------|
| `get_scorecard(scanner_type, date_range)` | `ScannerOutcomeSummary` | Aggregate signal quality: win rate, avg MFE/MAE, expectancy, profit factor, follow-through rate |
| `get_edge_decay(scanner_type, date_range)` | `ScannerOutcomeSummary` | Group by week/month, track how MFE and follow-through rate change over time |
| `get_interval_performance(scanner_type, interval_key)` | `ScannerOutcomeSnapshot` | Avg pct_change, median, stddev at a specific interval |
| `get_distribution(scanner_type, metric)` | `ScannerOutcomeSummary` | Histogram/scatter data for any metric (MFE, MAE, R-multiple) |

Existing `get_edge_stats()` and `get_distribution_data()` methods remain for backward compatibility during migration, then are removed once EdgeExplorer is fully switched over.

### Scorecard Response Shape

```json
{
  "scanner_type": "liquidity_hunt",
  "period": "2026-03-01 to 2026-04-30",
  "total_signals": 142,
  "complete_signals": 128,
  "win_rate_pct": 61.7,
  "avg_mfe_pct": 4.2,
  "avg_mae_pct": -1.8,
  "mfe_mae_ratio": 2.33,
  "avg_r_multiple": 1.45,
  "expectancy": 0.82,
  "profit_factor": 2.1,
  "follow_through_rate_pct": 54.3,
  "edge_decay": [
    {"period": "2026-W12", "win_rate": 65.0, "avg_mfe": 4.8},
    {"period": "2026-W13", "win_rate": 58.3, "avg_mfe": 3.9}
  ],
  "interval_breakdown": {
    "1h":  {"avg_pct": 1.2, "win_rate": 55.0},
    "4h":  {"avg_pct": 2.1, "win_rate": 58.0},
    "eod": {"avg_pct": 2.8, "win_rate": 61.0},
    "1d":  {"avg_pct": 3.1, "win_rate": 60.0},
    "2d":  {"avg_pct": 3.5, "win_rate": 59.0},
    "5d":  {"avg_pct": 4.0, "win_rate": 57.0}
  }
}
```

## API Endpoints

New router at `backend/app/routers/outcomes.py`.

| Method | Path | Purpose |
|--------|------|---------|
| `GET` | `/api/outcomes/scorecard` | Scorecard aggregates. Query params: `scanner_type`, `start_date`, `end_date`, `severity` |
| `GET` | `/api/outcomes/scorecard/{scanner_type}` | Scorecard for a specific scanner type |
| `GET` | `/api/outcomes/intervals/{scanner_type}` | Per-interval breakdown (avg pct_change, win rate per interval) |
| `GET` | `/api/outcomes/distribution/{scanner_type}` | Histogram/scatter data. Query param: `metric` (mfe_pct, mae_pct, r_multiple) |
| `GET` | `/api/outcomes/edge-decay/{scanner_type}` | Time-series of signal quality by period |
| `GET` | `/api/outcomes/event/{event_id}` | Single event's full outcome: summary + all snapshots |
| `GET` | `/api/outcomes/readiness/{ticker}` | Data readiness report for a ticker across scanner types |
| `POST` | `/api/outcomes/backfill` | Trigger backfill for historical events. Body: `scanner_type`, `start_date`, `end_date` |

All GET endpoints support optional `severity` filter to compare signal quality across high/medium/low signals.

## Scope

### In scope

- Two new models: `ScannerOutcomeSummary`, `ScannerOutcomeSnapshot`
- Two new JSONB columns on `ScannerConfig`: `outcome_config`, `data_requirements`
- `DataReadinessService` shared service
- Celery periodic task `capture_outcome_snapshots`
- Post-insert hook on `ScannerEvent` to create pending snapshots
- API endpoints (outcomes router)
- Refactored `StatsService` with outcome-backed query methods
- Backfill endpoint for historical events
- Seed default `outcome_config` and `data_requirements` for existing scanner types (`pre_market_volume`, `liquidity_hunt`)
- Alembic migration for new tables and columns

### Out of scope (future work)

- EdgeExplorer frontend redesign — it consumes the new APIs but layout/UX changes are a separate effort
- Dashboard scorecard widget
- Alert rules based on outcome metrics (e.g. "notify when win rate drops below 50%")
- A/B comparison of scanner configs against each other
