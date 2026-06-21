# Replay Engine: Data Model + Manifest Resolver + Data Hash — Design

**Date:** 2026-06-21
**Issue:** #484
**Status:** Spec pending review

## Overview

This spec covers the persistence and reproducibility foundation for the Canonical
Signal Replay Engine: two new database tables (`replay_runs`, `replay_trades`), a
`ManifestResolver` service that freezes config/strategy/universe snapshots at run
creation time, and a `compute_data_hash` function that produces a SHA-256 content
fingerprint over the market data in scope for a run.

This is sub-issue 1 of the Replay Engine epic. It establishes the schema foundation
that later sub-issues (exit simulation, Celery task, API, UI) will build on. No
dependency on #300.

### Why a new table, not an extension of BacktestRun?

`BacktestRun`/`BacktestTrade` (implemented in #301) is a live, fully-wired system
with its own router, service, Celery task, Pydantic schemas, and tests. The replay
engine is a separate, richer system with content-hashing, full manifest freezing, and
per-trade MFE/MAE/regime enrichment. Creating new tables avoids scope spillover into
the backtest subsystem and keeps the two systems independently evolvable.

---

## §1 Requirements

1. `ReplayRun` model with all fields from the issue (see §2).
2. `ReplayTrade` model with all fields from the issue (see §3).
3. Both models registered in `backend/app/models/__init__.py`.
4. `ManifestResolver` class at `backend/app/services/replay/manifest.py` that
   freezes `ScannerConfig`, optional `TradingStrategy`, and universe-ticker list
   into snapshot JSONB fields at run creation.
5. `compute_data_hash(scanner_config_snapshot, universe_snapshot, start_date, end_date, db)` function that returns a stable SHA-256 hex string over the market data in scope.
6. Alembic migration that applies cleanly on both a fresh DB and the current
   production schema.
7. `metrics` defaults to `None` (NULL in DB) until computed by the execution task.
8. `trading_strategy_id` is nullable to support scanner-only (no-trade) replays.
9. `data_hash` is stable for identical inputs and changes when any in-scope bar is
   mutated.

---

## §2 `ReplayRun` model

File: `backend/app/models/replay_run.py`
Table: `replay_runs`

| Column | Type | Nullable | Notes |
|---|---|---|---|
| `id` | Integer PK | — | auto |
| `uuid` | UUID | unique | `uuid.uuid4` default |
| `status` | String(20) | NOT NULL | `queued` \| `running` \| `completed` \| `failed` |
| `scanner_type` | String(50) | NOT NULL | denormalized from `ScannerConfig.scanner_type` |
| `scanner_config_snapshot` | JSONB | NOT NULL | frozen at run creation by `ManifestResolver` |
| `trading_strategy_id` | Integer FK → `trading_strategies.id` | NULL | NULL for scanner-only runs |
| `strategy_snapshot` | JSONB | NULL | NULL when no strategy; frozen by `ManifestResolver` |
| `universe_id` | Integer FK → `stock_universes.id` | NOT NULL | |
| `universe_snapshot` | JSONB | NOT NULL | sorted list of tickers at freeze time |
| `start_date` | Date | NOT NULL | |
| `end_date` | Date | NOT NULL | |
| `max_hold_days` | Integer | NOT NULL | |
| `exit_fidelity` | String(20) | NOT NULL | `daily` \| `intraday`; default `daily` |
| `benchmark_symbol` | String(10) | NULL | e.g. `"SPY"` |
| `data_hash` | String(64) | NULL | SHA-256 hex; set by `ManifestResolver` at creation |
| `metrics` | JSONB | NULL | NULL until computed by execution task |
| `skipped_count` | Integer | NULL | signals skipped due to missing data |
| `error_message` | Text | NULL | populated on `status = failed` |
| `created_at` | DateTime | NOT NULL | `utc_now` default |
| `completed_at` | DateTime | NULL | set by execution task on finish |

Use `ondelete="SET NULL"` for `trading_strategy_id` FK; `ondelete="RESTRICT"` for
`universe_id` (universe deletion blocked while a replay run references it).

---

## §3 `ReplayTrade` model

File: `backend/app/models/replay_trade.py`
Table: `replay_trades`

| Column | Type | Nullable | Notes |
|---|---|---|---|
| `id` | Integer PK | — | auto |
| `replay_run_id` | Integer FK → `replay_runs.id` CASCADE | NOT NULL | indexed |
| `scanner_event_id` | Integer FK → `scanner_events.id` SET NULL | NULL | NULL when signal generated in-memory |
| `ticker` | String(10) | NOT NULL | |
| `signal_date` | Date | NOT NULL | |
| `entry_date` | Date | NULL | |
| `entry_price` | Numeric | NULL | |
| `direction` | String(10) | NULL | `long` \| `short` |
| `stop_price` | Numeric | NULL | |
| `target_price` | Numeric | NULL | |
| `exit_date` | Date | NULL | |
| `exit_price` | Numeric | NULL | |
| `exit_reason` | String(30) | NULL | `stop` \| `target` \| `time_stop` \| `delisted_or_data_end` \| `no_entry_bar` |
| `return_pct` | Float | NULL | percentage return |
| `return_r` | Float | NULL | return in R-multiples |
| `mfe_pct` | Float | NULL | max favourable excursion % |
| `mae_pct` | Float | NULL | max adverse excursion % |
| `bars_held` | Integer | NULL | calendar days held |
| `regime_trend` | String(20) | NULL | regime classification at signal date |
| `regime_vol` | String(20) | NULL | volatility regime at signal date |
| `fill_source` | String(20) | NULL | `daily_open` \| `minute_bar` \| `vwap` |
| `created_at` | DateTime | NOT NULL | `utc_now` default |

Index: composite `(replay_run_id)` on `replay_trades` (as specified in issue).

---

## §4 `ManifestResolver`

File: `backend/app/services/replay/manifest.py`
Package init: `backend/app/services/replay/__init__.py` (empty)

```python
class ManifestResolver:
    def resolve(
        self,
        scanner_config: ScannerConfig,
        universe: StockUniverse,
        db: Session,
        trading_strategy: TradingStrategy | None = None,
    ) -> ReplayManifest:
        ...
```

Returns a `ReplayManifest` dataclass with:
- `scanner_type: str`
- `scanner_config_snapshot: dict`
- `strategy_snapshot: dict | None`
- `universe_snapshot: list[str]`  (sorted ticker list)

### Scanner config snapshot fields

From `ScannerConfig`: `scanner_type`, `parameters`, `criteria`, `outcome_config`,
`data_requirements`. **Excluded**: `id`, `uuid`, `name`, `description`, `is_active`,
`run_frequency`, `last_run`, `next_run`, `universe_id`, `created_at`, `updated_at`.

Rationale: scheduling/lifecycle fields are mutable noise that do not affect simulation
outcomes. Excluding them ensures two runs using the same logic but different schedules
produce identical config snapshots.

### Strategy snapshot fields

From `TradingStrategy` (when not None): `direction`, `entry_type`, `limit_offset_pct`,
`stop_pct`, `risk_reward_ratio`, `max_slippage_pct`, `allowed_sessions`,
`risk_per_trade_pct`, `max_position_usd`, `max_trades_per_day`,
`max_concurrent_positions`. **Excluded**: `id`, `uuid`, `name`, `description`,
`is_active`, `paper_mode`, `requires_approval`, `created_at`, `updated_at`.

This follows the existing precedent in `backtest_service.py` (curated subset snapshot)
and extends it to all simulation-affecting fields.

### Universe snapshot

Query `StockUniverseTicker` rows for `universe_id`, extract the `ticker` strings,
sort lexicographically, return as `list[str]`. Stores the point-in-time membership;
later changes to the universe do not affect existing replay run snapshots.

### Decimal serialization

All `Numeric`/`Decimal` fields must be serialized as their canonical decimal string
(`str(value)`) in all snapshot dicts. Use
`json.dumps(obj, sort_keys=True, separators=(",", ":"))` as the canonical serialization
form for hashing (see §5).

---

## §5 `compute_data_hash`

Also in `backend/app/services/replay/manifest.py`.

```python
def compute_data_hash(
    universe_snapshot: list[str],
    start_date: date,
    end_date: date,
    db: Session,
) -> str:
```

Returns a 64-character SHA-256 hex string.

### Algorithm

For each `(ticker, trading_day)` where `ticker` in `universe_snapshot` and
`trading_day` in `[start_date, end_date]` (trading days only — days with a
`StockAggregate` daily bar present):

1. Fetch the daily `StockAggregate` bar: `open`, `high`, `low`, `close`, `volume`,
   `vwap`. Serialize `Numeric` fields as `str(value)`, `volume` as `int`.
2. Fetch the minute-bar count: `COUNT(*)` of `StockAggregate` rows with
   `ticker = ticker`, `timespan = 'minute'`, and `timestamp` within the trading day.
3. Compute the split-adjustment version: fetch `StockSplit` rows for the ticker where
   `execution_date > trading_day` AND `adjustments_applied_at IS NOT NULL`. Sort by
   `(execution_date, split_from, split_to)`. Serialize as a list of
   `[str(execution_date), str(split_from), str(split_to)]` triples.

Build a canonical dict for the `(ticker, trading_day)` cell:
```json
{
  "ticker": "AAPL",
  "day": "2026-01-15",
  "open": "182.3400",
  "high": "185.1000",
  "low": "181.9200",
  "close": "184.5600",
  "volume": 42391000,
  "vwap": "183.7821",
  "minute_bar_count": 390,
  "split_adjustment_version": [["2026-03-10", "2", "1"]]
}
```

Collect all cell dicts, sort the list by `(ticker, day)`, then:

```python
import hashlib, json

canonical = json.dumps(cells, sort_keys=True, separators=(",", ":"))
return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
```

### Stability guarantee

- Identical inputs → identical hash (JSON key order fixed by `sort_keys=True`; list
  order fixed by explicit sort on `(ticker, day)`).
- Any OHLCV mutation → hash changes (OHLCV fields included per cell).
- Any new applied split → hash changes (split-adjustment version changes for all
  days prior to the split's execution date).
- New minute bars ingested → hash changes (minute-bar count changes).

---

## §6 Registration

Add to `backend/app/models/__init__.py`:
```python
from app.models.replay_run import ReplayRun
from app.models.replay_trade import ReplayTrade
```
And add `"ReplayRun"`, `"ReplayTrade"` to `__all__`.

---

## §7 Alembic Migration

One migration file in `backend/app/alembic/versions/`. Creates `replay_runs` then
`replay_trades` (order matters for FK). Migration must:
- Apply cleanly on a fresh DB.
- Apply cleanly on the current production schema (no backtest table interactions).
- Include `downgrade()` that drops `replay_trades` then `replay_runs`.

No data migration required (new tables, no existing rows).

---

## §8 Alternatives Considered

### Alt A: Extend `BacktestRun` in-place
Add the missing columns (`data_hash`, `scanner_config_snapshot`, `exit_fidelity`, etc.)
via migration and rename the tables.

**Rejected:** `BacktestRun`/`BacktestTrade` are live — the router, service, Celery task,
schemas, and tests all reference the current column names. An in-place rename would
require coordinated changes to at least 6 files outside this issue's scope. The schemas
also differ enough (backtest uses R-multiple summary stats; replay uses content hashing
+ full manifest freezing) that force-fitting them would produce a muddled model.

### Alt B: Single combined `simulation_run` table
One table with a `simulation_type` discriminator column covering both backtest and
replay semantics.

**Rejected:** YAGNI. The backtest system is in use and working. A merged table would
require touching the backtest router/service, increases blast radius, and gains no
near-term benefit.

---

## §9 Open Questions (non-blocking)

1. **`exit_fidelity` enum values** — the spec doc referenced by the issue
   (`docs/superpowers/specs/2026-06-13-signal-replay-engine-design.md`, §5.1) is not
   present in the repo. This spec uses `"daily"` / `"intraday"` based on codebase
   evidence (existing daily-bar backtest + `StockAggregate` minute-bar support + the
   `data_hash` minute-bar count component). Confirm exact valid values against the
   parent epic spec before the exit-simulation sub-issue (2) builds the simulator.

2. **`scanner_config_id` FK** — the issue does not include an FK from `replay_run`
   back to `scanner_configs` (only `scanner_type` string + snapshot). This means
   deleted or renamed configs remain representable via snapshot. If cross-run
   filtering by original config ID becomes a UI requirement, a nullable
   `scanner_config_id` FK can be added in a follow-up without breaking this design.

3. **`data_hash` when no bars exist** — if `universe_snapshot` contains tickers with
   no `StockAggregate` rows in the date range, the cell list for those tickers is
   empty. Confirm whether: (a) they are excluded from hashing silently, (b) they
   produce an entry with zeroed/null OHLCV to signal their absence, or (c) the run is
   rejected. Recommendation: exclude silently and increment `skipped_count`.

---

## §10 Assumptions

- `StockSplit.adjustments_applied_at` is the reliable indicator of whether a split's
  factor has been applied to `StockAggregate` bars. (Confirmed: `SplitAdjustmentService`
  sets this field on completion.)
- `StockAggregate` stores adjusted prices in-place (destructive UPDATE). The
  `data_hash` therefore reflects the current adjustment state, not a historical one.
  This is acceptable for the "detect drift / invalidate replay" use case.
- The `services/replay/` sub-package is new. The empty `__init__.py` is the standard
  pattern for sub-packages in `backend/app/services/`.
- `max_hold_days` (replay) maps to calendar days, unlike `BacktestRun.max_hold_sessions`
  (trading sessions). Implementer should confirm units with the execution sub-issue.
