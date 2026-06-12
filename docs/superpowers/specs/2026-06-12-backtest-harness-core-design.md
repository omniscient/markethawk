# Backtest Harness Core: Daily-Bar Replay

**Date:** 2026-06-12
**Issue:** #301
**Epic:** #300 (Backtest scanner signals against TradingStrategy definitions)
**Depends on:** None for v1; #387 (degraded-feed handling) is a nullable placeholder
**Status:** Spec

---

## Problem

Scanner strategies produce forward-looking signals, but there is no way to evaluate whether a
given `TradingStrategy` configuration (entry type, stop %, risk/reward ratio) would have been
profitable when applied to those signals historically. Without a replay harness, strategy
parameters are tuned by intuition rather than evidence.

---

## Requirements

1. Accept a request: `scanner_type`, `scanner_config_id` (or inline `parameters`), `universe_id`,
   `strategy_id`, `start_date`, `end_date`, and optional `max_hold_sessions` (default 10).
2. Generate historical signals by querying existing `ScannerEvent` rows first; fall back to
   calling `scan_orchestrator.run()` for dates with no stored events when the scanner descriptor
   has `supports_date_range = True`.
3. Simulate each signal using the `TradingStrategy`'s `entry_type`, `limit_offset_pct`,
   `stop_pct`, and `risk_reward_ratio` against daily `StockAggregate` bars.
4. **Conservative intrabar rule**: if a bar's low ≤ stop AND high ≥ target, count the stop.
5. **Delisting / data-end exit**: if bars end while a position is open, exit at last available
   close and tag `exit_reason = delisted_or_data_end`. Do NOT drop the trade.
6. **Time stop**: exit at next session open after `max_hold_sessions` sessions if neither stop
   nor target was hit. Tag `exit_reason = time_stop`.
7. **No tradability filter**: a ticker is eligible for signals if it has `StockAggregate` bars in
   the replay window, regardless of current `StockUniverseTicker` status.
8. Output per run: `win_rate`, `profit_factor`, `expectancy_r`, `max_drawdown_pct`,
   `avg_hold_sessions`, `median_hold_sessions`, `trade_count`, and the full trade list.
9. Persist the run for comparison. Every run record carries anti-bias metadata:
   `signals_skipped_no_data`, `trades_exited_on_data_end`, `universe_as_of` (today's date),
   `bars_source` (e.g. `polygon_adjusted`), and a nullable `degraded_input` column (reserved
   for #387 — always NULL in v1).
10. Execution is async (Celery task); the endpoint returns immediately with a run UUID for
    polling.
11. Deterministic: same inputs → same stats.
12. Unit tests cover: stop/target/time-stop precedence, the conservative intrabar rule, and
    the delisting exit path.

---

## Architecture / Approach

### New tables

#### `backtest_runs`

| Column | Type | Notes |
|--------|------|-------|
| `id` | Integer PK | |
| `uuid` | UUID | unique, indexed |
| `scanner_type` | String(50) | |
| `scanner_config_snapshot` | JSONB | snapshot of parameters at run time (determinism) |
| `universe_id` | Integer FK → `stock_universes` | |
| `strategy_id` | Integer FK → `trading_strategies` | |
| `strategy_snapshot` | JSONB | snapshot of strategy fields at run time (determinism) |
| `start_date` | Date | |
| `end_date` | Date | |
| `max_hold_sessions` | Integer | resolved value (default 10) |
| `status` | String(20) | `queued`, `running`, `completed`, `failed` |
| `celery_task_id` | String(64) | nullable, indexed |
| `trade_count` | Integer | nullable (set on completion) |
| `win_rate` | Numeric | nullable |
| `profit_factor` | Numeric | nullable |
| `expectancy_r` | Numeric | nullable |
| `max_drawdown_pct` | Numeric | nullable |
| `avg_hold_sessions` | Numeric | nullable |
| `median_hold_sessions` | Numeric | nullable |
| `signals_skipped_no_data` | Integer | nullable |
| `trades_exited_on_data_end` | Integer | nullable |
| `universe_as_of` | Date | set to `today()` at run start |
| `bars_source` | String(50) | e.g. `polygon_adjusted` |
| `degraded_input` | Boolean | nullable; always NULL in v1 (reserved for #387) |
| `error_message` | Text | nullable |
| `created_at` | DateTime | |
| `completed_at` | DateTime | nullable |

#### `backtest_trades`

| Column | Type | Notes |
|--------|------|-------|
| `id` | Integer PK | |
| `backtest_run_id` | Integer FK → `backtest_runs` CASCADE | indexed |
| `ticker` | String(10) | |
| `signal_date` | Date | date the signal fired |
| `entry_date` | Date | nullable (next session open) |
| `entry_price` | Numeric | nullable |
| `stop_price` | Numeric | nullable |
| `target_price` | Numeric | nullable |
| `exit_date` | Date | nullable |
| `exit_price` | Numeric | nullable |
| `exit_reason` | String(30) | `stop`, `target`, `time_stop`, `delisted_or_data_end`, `no_entry_bar` |
| `hold_sessions` | Integer | nullable |
| `pnl_r` | Numeric | nullable (P&L in R units; negative for losses) |
| `signal_indicators` | JSONB | snapshot of signal indicators for the trade record |
| `source_event_id` | Integer FK → `scanner_events` SET NULL | nullable; populated when signal came from DB |

### New service: `backend/app/services/backtest_service.py`

```
BacktestService
  ├── run(backtest_run_id, db) → None          # orchestrates full replay; called by Celery task
  ├── _get_signals(scanner_type, parameters, tickers, event_date, db) → list[dict]
  │     # 1. query ScannerEvent for (tickers, event_date, scanner_type)
  │     # 2. if empty and descriptor.supports_date_range: call scan_orchestrator.run()
  │     # 3. returns list of signal dicts with added source_event_id where available
  ├── _simulate_trade(signal, strategy_snapshot, bars, max_hold_sessions) → BacktestTradeDict
  │     # pure function; no DB access; applies stop/target/time-stop rules
  └── _compute_stats(trades) → StatsDict
        # win_rate, profit_factor, expectancy_r, max_drawdown_pct, avg/median hold
```

`_simulate_trade` is pure (no DB, no side effects) so it is straightforwardly unit-testable.

### Replay loop (inside `BacktestService.run`)

```
1. Load BacktestRun record (strategy_snapshot, scanner_config_snapshot, universe_id, dates)
2. Fetch all tickers from StockUniverseTicker WHERE universe_id = run.universe_id
   — do NOT filter by is_active or current state; eligibility is determined by bar presence
3. Bulk-load daily StockAggregate bars for all tickers over [start_date, end_date + max_hold_sessions]
   into a per-ticker dict keyed by date
4. For each business day d in [start_date, end_date]:
     signals = _get_signals(scanner_type, params, tickers, d, db)
     for each signal in signals:
       entry_bar = bars[signal.ticker].get(d + 1 session)
       if no entry_bar: record exit_reason=no_entry_bar, skip simulation
       compute entry_price (market: open; limit: open adjusted by limit_offset_pct, capped at open)
       open position → simulate forward day by day:
         for each subsequent bar:
           apply conservative intrabar rule (low ≤ stop AND high ≥ target → stop)
           else: check stop (low ≤ stop_price), check target (high ≥ target_price)
           else: check time stop (hold_sessions ≥ max_hold_sessions → exit next open)
         if bars exhausted before any exit: delisted_or_data_end at last close
5. Compute aggregate stats from completed trades
6. INSERT BacktestTrade rows; UPDATE BacktestRun with stats and status=completed
```

### Celery task: `backend/app/tasks/backtest.py`

```python
@celery_app.task(name="app.tasks.run_backtest", bind=True, max_retries=0)
def run_backtest(self, backtest_run_id: int) -> None:
    ...
```

No retry (deterministic; re-run by the user if needed). Sets `status=failed` + `error_message` on exception.

### New router: `backend/app/routers/backtest.py`

| Method | Path | Purpose |
|--------|------|---------|
| `POST` | `/api/v1/backtest/runs` | Create run, enqueue task, return `{uuid, status}` |
| `GET` | `/api/v1/backtest/runs` | List runs (paginated; filter by scanner_type, strategy_id) |
| `GET` | `/api/v1/backtest/runs/{uuid}` | Get run status + summary + trade list once complete |

Request body for `POST`:
```json
{
  "scanner_type": "pre_market_volume_spike",
  "scanner_config_id": 1,
  "universe_id": 1,
  "strategy_id": 3,
  "start_date": "2025-01-01",
  "end_date": "2025-12-31",
  "max_hold_sessions": 10
}
```

### Entry price for limit orders

When `entry_type = "limit"`:
- `limit_price = signal_previous_close * (1 + limit_offset_pct / 100)`
  where `signal_previous_close` is the `previous_close` field from the signal dict / `ScannerEvent`.
- Fill rule: if `next_session_open <= limit_price` → fill at `next_session_open` (got a better
  price than the limit). If `next_session_open > limit_price` → record `exit_reason = no_entry_bar`
  and skip the trade (limit not reached on the entry bar).
- This is the conservative fill model; see Open Question #1 for the alternative.

### Signal source resolution

```
if ScannerEvent rows exist for (ticker, event_date, scanner_type):
    use them; set source_event_id on BacktestTrade
elif descriptor.supports_date_range:
    call scan_orchestrator.run() in read-only mode (skip _persist step)
    do NOT write to scanner_events
else:
    increment signals_skipped_no_data; skip date
```

Generated signals are never written to `scanner_events` — see §Alternatives §A.

---

## Alternatives Considered

### A. Write generated signals to `scanner_events`
Rejected. The `UniqueConstraint(ticker, event_date, scanner_type)` produces IntegrityErrors on
overlapping real events. Writing synthetic rows pollutes live operational history (alerts,
outcome snapshots, clustering). Keeping replay in its own tables preserves the clean separation
between live signals and historical simulations.

### B. Store trade list as JSONB on `BacktestRun`
Rejected in favor of a separate `backtest_trades` table. A 1-year replay over a large universe
produces hundreds of trades; a JSONB blob cannot be efficiently queried for cross-run trade-level
comparisons (issue #302). Normalized rows match the `ScannerRun` + `ScannerEvent` pattern.

### C. Synchronous endpoint (no Celery)
Rejected. A 1-year replay with signal re-generation for a universe of hundreds of tickers can
run for minutes; a synchronous handler would time out and block a backend worker thread. Celery
async with polling matches all other long-running operations in this codebase.

### D. Add `max_hold_sessions` to `TradingStrategy`
Rejected. `TradingStrategy` is a live-trading model consumed by `auto_trade_service.py` and
`tasks/trading.py`. The live executor has no time-stop logic and would silently ignore the
column. Placing a backtest-only parameter there is a latent footgun. Per-run parameter keeps
the experiment config fully contained in `BacktestRun` for determinism and reproducibility.

---

## Assumptions

- `StockAggregate` rows for `timespan='day'` exist for the replay window; the harness does NOT
  download missing bars (that is the Catch Up / Sync feature).
- The harness is long-only (consistent with `TradingStrategy.direction = 'long_only'` default).
  Short simulation is out of scope for v1.
- "Next session open" means the open price of the `StockAggregate` bar for the following
  calendar day that has a bar. If that bar is missing, `exit_reason = no_entry_bar`.
- `bars_source` is a free-form string set from a constant in the service (`"polygon_adjusted"`
  until #387 introduces a more structured source-tracking mechanism).
- The harness does not adjust for splits during simulation. Until #387's adjustment policy
  is settled, a `bars_source` field on each run makes runs comparable post-adjustment.

---

## Open Questions (non-blocking)

1. **Limit fill model**: should a limit order that gaps above the limit price on open be filled
   at the open (aggressive fill) or marked `no_entry_bar` (strict limit)? Spec uses strict
   (conservative). Can be relaxed by config parameter later.
2. **Parallel date processing**: the replay loop processes dates sequentially. For large
   universes + long date ranges, parallelising date chunks via `asyncio.gather` could reduce
   runtime. Out of scope for v1; determinism is simpler to guarantee with sequential execution.
3. **Benchmark / equity curve**: max drawdown is computed on cumulative R; a calendar-aligned
   equity curve (for plotting) is not included in v1. Deferred to the UI phase.
