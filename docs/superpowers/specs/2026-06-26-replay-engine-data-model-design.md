# Replay Engine: Data Model, Manifest Resolver & Data Hash — Design Spec

**Date:** 2026-06-26  
**Issue:** #484  
**Epic:** Canonical Signal Replay Engine  
**Status:** Pending review  
**Parent spec:** `docs/superpowers/specs/2026-06-13-signal-replay-engine-design.md` §5.1, §7

---

## 1. Problem

The existing `BacktestRun`/`BacktestTrade` system (issue #301) is a live feature but lacks two
properties the Replay Engine requires:

1. **Manifest freezing** — a `BacktestRun` captures only a partial strategy snapshot and a loose
   scanner-config reference; it does not freeze the universe ticker list or pin the data contents at
   run time.
2. **Content-addressable data** — there is no `data_hash` column, so there is no way to verify
   that two runs operated on identical market data or to detect silent bar mutations.

This issue builds the persistence + reproducibility foundation: two new tables (`replay_runs`,
`replay_trades`), a `ManifestResolver` service that freezes all inputs at run creation, and a
`compute_data_hash` function that produces a stable SHA-256 fingerprint over the market data in
scope.

## 2. Scope

**In scope (this issue only):**

- `ReplayRun` SQLAlchemy model + Alembic migration
- `ReplayTrade` SQLAlchemy model (same migration)
- `ManifestResolver` class at `backend/app/services/replay/manifest.py`
- `compute_data_hash()` function in the same module
- Unit tests for `ManifestResolver` snapshot stability and `compute_data_hash` determinism

**Out of scope:**

- Exit simulation engine (sub-issue 2)
- Celery execution task (sub-issue 4)
- REST API endpoints (sub-issue 5)
- Frontend UI (sub-issues 6/7)
- Modifications to `BacktestRun`, `BacktestTrade`, or any existing backtest service

## 3. Design decisions

| Dimension | Decision |
|---|---|
| Relationship to backtest tables | **Coexist** — `replay_runs`/`replay_trades` are new, independent tables. Backtest tables are untouched. |
| `trading_strategy_id` nullable | **Yes** — scanner-only replays (signal analysis without trade simulation) are a first-class use case. |
| ManifestResolver shape | **Class** — `ManifestResolver(db)` with `.resolve()` and `.compute_data_hash()` methods; injectable for testing. |
| data_hash timing | **Synchronous at run creation** — computed in the same transaction that writes the `ReplayRun` row. |
| `exit_fidelity` vocabulary | `"daily"` (default) \| `"intraday"` — controls bar resolution used by the exit simulator. |
| Snapshot field scope | **Simulation-affecting fields only** — no scheduling/lifecycle noise. |
| `fill_source` vocabulary | `"daily_open"` \| `"daily_close"` (initial) — `String(20)` for future expansion. |
| `direction` in `replay_trade` | Per-trade resolved `"long"` \| `"short"`, `String(10)`, nullable for scanner-only runs. |

## 4. Models

### 4.1 `ReplayRun` (`backend/app/models/replay_run.py`, table `replay_runs`)

```python
class ReplayRun(Base):
    __tablename__ = "replay_runs"

    id               = Column(Integer, primary_key=True, index=True)
    uuid             = Column(UUID(as_uuid=True), default=uuid.uuid4, unique=True, index=True)

    # ── Status ────────────────────────────────────────────────────────────────
    # queued → running → completed | failed
    status           = Column(String(20), nullable=False, default="queued")

    # ── Frozen manifest ───────────────────────────────────────────────────────
    scanner_type              = Column(String(50), nullable=False)
    scanner_config_snapshot   = Column(JSONB, nullable=False)          # see §5
    trading_strategy_id       = Column(Integer, ForeignKey("trading_strategies.id"), nullable=True)
    strategy_snapshot         = Column(JSONB, nullable=True)           # NULL for scanner-only runs
    universe_id               = Column(Integer, ForeignKey("stock_universes.id"), nullable=False)
    universe_snapshot         = Column(JSONB, nullable=False)          # sorted list of tickers

    # ── Run parameters ────────────────────────────────────────────────────────
    start_date        = Column(Date, nullable=False)
    end_date          = Column(Date, nullable=False)
    max_hold_days     = Column(Integer, nullable=False, default=10)    # calendar days
    exit_fidelity     = Column(String(20), nullable=False, default="daily")  # "daily" | "intraday"
    benchmark_symbol  = Column(String(10), nullable=True)

    # ── Data fingerprint ──────────────────────────────────────────────────────
    data_hash         = Column(String(64), nullable=True)              # SHA-256 hex; NULL if not yet computed or data unavailable

    # ── Results ───────────────────────────────────────────────────────────────
    metrics           = Column(JSONB, nullable=True)                   # NULL until computed
    skipped_count     = Column(Integer, nullable=True, default=0)
    error_message     = Column(Text, nullable=True)

    # ── Timestamps ────────────────────────────────────────────────────────────
    created_at        = Column(DateTime, default=utc_now)
    completed_at      = Column(DateTime, nullable=True)
```

**Notes:**
- `max_hold_days` is calendar days (vs. `BacktestRun.max_hold_sessions` which is trading sessions).
  The exit simulator (sub-issue 2) converts to trading sessions internally.
- `data_hash` is computed synchronously at run creation; if bar data is absent for the window,
  the run is failed at creation (same pattern as backtest's `tickers_with_data` resolution).
- No `celery_task_id` column in this model — the execution task (sub-issue 4) will add it in a
  separate migration when the task exists.
- No `scanner_config_id` FK column — the `ScannerConfig` is captured entirely in
  `scanner_config_snapshot` at creation, so the live config can change without affecting a
  queued run.

### 4.2 `ReplayTrade` (`backend/app/models/replay_trade.py`, table `replay_trades`)

```python
class ReplayTrade(Base):
    __tablename__ = "replay_trades"

    id              = Column(Integer, primary_key=True, index=True)
    replay_run_id   = Column(Integer, ForeignKey("replay_runs.id", ondelete="CASCADE"),
                             nullable=False, index=True)
    scanner_event_id = Column(Integer, ForeignKey("scanner_events.id", ondelete="SET NULL"),
                              nullable=True)

    # ── Signal ────────────────────────────────────────────────────────────────
    ticker          = Column(String(10), nullable=False)
    signal_date     = Column(Date, nullable=False)
    direction       = Column(String(10), nullable=True)   # "long" | "short"; NULL for scanner-only

    # ── Entry ─────────────────────────────────────────────────────────────────
    entry_date      = Column(Date, nullable=True)
    entry_price     = Column(Numeric, nullable=True)
    fill_source     = Column(String(20), nullable=True)   # "daily_open" | "daily_close"

    # ── Levels ────────────────────────────────────────────────────────────────
    stop_price      = Column(Numeric, nullable=True)
    target_price    = Column(Numeric, nullable=True)

    # ── Exit ──────────────────────────────────────────────────────────────────
    exit_date       = Column(Date, nullable=True)
    exit_price      = Column(Numeric, nullable=True)
    exit_reason     = Column(String(30), nullable=True)   # stop | target | time_stop | delisted_or_data_end | no_entry_bar

    # ── P&L ───────────────────────────────────────────────────────────────────
    return_pct      = Column(Numeric, nullable=True)   # percentage return
    return_r        = Column(Numeric, nullable=True)   # return in R-multiples
    mfe_pct         = Column(Numeric, nullable=True)   # max favourable excursion %
    mae_pct         = Column(Numeric, nullable=True)   # max adverse excursion %
    bars_held       = Column(Integer, nullable=True)

    # ── Regime context ────────────────────────────────────────────────────────
    regime_trend    = Column(String(20), nullable=True)  # e.g. "uptrend" | "downtrend" | "sideways"
    regime_vol      = Column(String(20), nullable=True)  # e.g. "low" | "normal" | "high"

    created_at      = Column(DateTime, default=utc_now)
```

**Composite index** on `(replay_run_id)` — the non-nullable FK column already gets a single-column
index (declared inline above). No additional composite indexes needed until query patterns emerge.

## 5. ManifestResolver

**Location:** `backend/app/services/replay/manifest.py` (new sub-package; add
`backend/app/services/replay/__init__.py`).

### 5.1 Snapshot field scope

**`scanner_config_snapshot`** — simulation-affecting fields only:

```python
{
    "scanner_type": config.scanner_type,
    "parameters": config.parameters,
    "criteria": config.criteria,
    "outcome_config": config.outcome_config,
    "data_requirements": config.data_requirements,
}
```

Excluded: `id`, `uuid`, `name`, `description`, `is_active`, `run_frequency`, `last_run`,
`next_run`, `universe_id`, `created_at`, `updated_at`.

**`strategy_snapshot`** — simulation-affecting fields only (NULL when no strategy):

```python
{
    "direction": strategy.direction,
    "entry_type": strategy.entry_type,
    "limit_offset_pct": str(strategy.limit_offset_pct),
    "stop_pct": str(strategy.stop_pct),
    "risk_reward_ratio": str(strategy.risk_reward_ratio),
    "max_slippage_pct": str(strategy.max_slippage_pct),
    "allowed_sessions": strategy.allowed_sessions,
    "risk_per_trade_pct": str(strategy.risk_per_trade_pct),
    "max_position_usd": str(strategy.max_position_usd) if strategy.max_position_usd else None,
    "max_trades_per_day": strategy.max_trades_per_day,
    "max_concurrent_positions": strategy.max_concurrent_positions,
}
```

Excluded: `id`, `name`, `description`, `is_active`, `paper_mode`, `requires_approval`,
`created_at`, `updated_at`, `alert_rules`, `auto_trade_orders`.

**`universe_snapshot`** — sorted list of active tickers at freeze time:

```python
{
    "tickers": sorted([t.ticker for t in active_tickers]),
    "universe_id": universe_id,
    "frozen_at": utc_now().isoformat(),
}
```

Queried from `StockUniverseTicker` where `universe_id == universe_id AND is_active == True`.

### 5.2 Class interface

```python
class ManifestResolver:
    def __init__(self, db: Session) -> None:
        self._db = db

    def resolve(
        self,
        scanner_config_id: int,
        universe_id: int,
        start_date: date,
        end_date: date,
        strategy_id: int | None = None,
    ) -> ResolvedManifest:
        """
        Freeze config/strategy/universe snapshots for a new ReplayRun.
        Returns a dataclass with scanner_type, scanner_config_snapshot,
        strategy_snapshot (or None), and universe_snapshot.
        Raises ValueError if the ScannerConfig or StockUniverse is not found.
        """
        ...

    def compute_data_hash(
        self,
        tickers: list[str],
        start_date: date,
        end_date: date,
    ) -> str:
        """
        SHA-256 over a canonical serialization of all (ticker, trading_day) cells
        in [start_date, end_date] for the given tickers. See §5.3 for the algorithm.
        Returns the hex digest.
        """
        ...
```

`ResolvedManifest` is a `@dataclass(frozen=True)` with fields:
`scanner_type: str`, `scanner_config_snapshot: dict`, `strategy_snapshot: dict | None`,
`universe_snapshot: dict`.

### 5.3 `compute_data_hash` algorithm

For each `(ticker, trading_day)` pair — ticker from `universe_snapshot.tickers`, trading_day in
chronological order across `[start_date, end_date]`:

1. Fetch the daily-bar row from `StockAggregate` where `ticker == ticker AND date(timestamp) == trading_day AND timespan == "day"`.
   If no daily bar exists for this cell, the cell is `{"ticker": ticker, "date": str(trading_day), "missing": true}`.
2. Fetch the minute-bar count from `StockAggregate` where `ticker == ticker AND date(timestamp) == trading_day AND timespan == "minute"`.
3. Fetch applied splits: `StockSplit` rows where `ticker == ticker AND execution_date > trading_day AND adjustments_applied_at IS NOT NULL`, ordered by `execution_date ASC`. This is the "split-adjustment version" — the set of future splits already applied to this day's adjusted prices.
4. Build the cell dict:
   ```python
   {
       "ticker": ticker,
       "date": str(trading_day),   # YYYY-MM-DD
       "open": str(bar.open),      # Decimal → str; never float
       "high": str(bar.high),
       "low": str(bar.low),
       "close": str(bar.close),
       "volume": bar.volume,
       "minute_bar_count": minute_count,
       "applied_splits": [
           {"execution_date": str(s.execution_date), "from": str(s.split_from), "to": str(s.split_to)}
           for s in applied_splits
       ],
   }
   ```
5. After building all cells, canonicalize: `json.dumps(cells, sort_keys=True, separators=(",", ":"))`, then `hashlib.sha256(canonical.encode()).hexdigest()`.

**Stability invariants:**
- Cells are ordered: tickers alphabetically, then dates chronologically. This order is deterministic.
- `Numeric`/`Decimal` values serialized as `str()` — never `float()` — to avoid cross-platform
  precision divergence.
- The hash changes whenever any OHLCV bar is updated, a new minute bar is ingested, or a new split
  adjustment is applied retroactively to a day in the range.

## 6. Migration

One Alembic migration creates both tables:

```
python -m alembic revision --autogenerate -m "add_replay_runs_and_replay_trades"
python -m alembic upgrade head
```

Constraints:
- `replay_trades.replay_run_id` → `replay_runs.id` with `ON DELETE CASCADE`
- `replay_trades.scanner_event_id` → `scanner_events.id` with `ON DELETE SET NULL`
- `replay_runs.trading_strategy_id` → `trading_strategies.id` (no cascade — strategy deletion
  must not cascade; NULL the FK via a separate `SET NULL` trigger or leave unhandled until needed)
- `replay_runs.universe_id` → `stock_universes.id` (no cascade)

## 7. Registration

Add to `backend/app/models/__init__.py`:
```python
from app.models.replay_run import ReplayRun
from app.models.replay_trade import ReplayTrade
```

Add `"ReplayRun"` and `"ReplayTrade"` to `__all__`.

## 8. Acceptance criteria

| Criterion | Verification |
|---|---|
| Migration applies cleanly on fresh DB | `alembic upgrade head` exits 0 |
| Migration applies on current schema without errors | Run against dev DB |
| `ManifestResolver.resolve()` snapshots do not change when source config/universe later mutates | Unit test: freeze, mutate source, re-query, assert snapshot unchanged |
| `compute_data_hash` is stable for identical inputs | Unit test: call twice on same data, assert equal hex digests |
| `compute_data_hash` changes when a bar is mutated | Unit test: mutate one bar, recompute, assert different digest |
| `ReplayRun.metrics` defaults to NULL until computed | Assert column has no `default=` |
| Models are importable without import errors | `from app.models import ReplayRun, ReplayTrade` |
| `trading_strategy_id` accepts NULL | Assert nullable=True; test scanner-only ReplayRun creation |

## 9. Alternatives considered

### A — Extend `BacktestRun` with new columns

Add `data_hash`, `exit_fidelity`, `universe_snapshot`, `skipped_count`, and the additional
`ReplayTrade` fields (MFE/MAE, regime, `fill_source`) to the existing backtest tables via migration.

**Rejected:** The schemas differ at a structural level — `BacktestRun.strategy_id` is NOT NULL (no
scanner-only mode), `max_hold_sessions` vs. `max_hold_days` semantics diverge, and the existing
backtest system is live with a router, Celery task, and tests that would all require risk-bearing
changes. Adding nullable columns to a live table is safe, but retrofitting the `ManifestResolver`
logic into `backtest_service.py` entangles two feature areas.

### B — Store `universe_snapshot` in a separate join table instead of JSONB

Rather than a JSONB ticker list, create a `replay_run_tickers` table with `(replay_run_id, ticker)`.

**Rejected:** The ticker list is read-only after freeze; no per-ticker metadata needs to be queried
independently. JSONB avoids an extra FK table and an extra query on every run-fetch. Consistent
with `BacktestRun.scanner_config_params` using JSONB for similar immutable snapshot data.

## 10. Open questions (non-blocking)

1. **`max_hold_days` units** — confirmed as calendar days in this spec, but the exit simulator
   (sub-issue 2) must align its counting logic accordingly. Verify before sub-issue 2 implementation.
2. **`data_hash` on missing-data runs** — the spec says fail the run at creation if data is absent.
   A partial-data mode (hash what exists, set `skipped_count`) is possible but deferred until the
   execution task (sub-issue 4) defines the error contract.
3. **`regime_trend`/`regime_vol` vocabulary** — exact string values will be defined by the
   `RegimeService` (already in `backend/app/services/regime_service.py`). The exit simulator
   sub-issue should confirm the value set.

## 11. Assumptions

- `StockSplit.adjustments_applied_at IS NOT NULL` is the reliable indicator that a split factor has been
  applied to `StockAggregate` bars (confirmed from the existing `split_adjustment.py` service).
- `StockAggregate` stores adjusted OHLCV in-place (destructive update) — no separate un-adjusted
  price column exists.
- `max_hold_days` is calendar days; conversion to trading sessions is the exit simulator's
  responsibility.
- The `replay_runs` / `replay_trades` tables will get `user_id` FK columns when the authorization
  model (issue #373) rolls out `BacktestRun` to `ReplayRun` as part of the "Personal" bucket
  migration (per the authz spec §3.①).
