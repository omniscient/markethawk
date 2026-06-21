# Replay Engine: Execution Task + Metrics Computer — Design

**Date:** 2026-06-21
**Issue:** #487
**Status:** Draft

## Overview

This spec covers the orchestration core of the Canonical Signal Replay Engine (epic #483): a Celery
task `run_signal_replay` that drives a replay manifest to completion, and the `MetricsComputer` that
turns the resulting trade ledger into headline, calendar-decay, holding-period-decay, and
regime-breakdown analytics. Both depend on sub-issues #484 (data model + manifest), #485 (exit
simulator), and #486 (benchmark + regime classifier), which must land first.

## Dependencies

| Sub-issue | What it provides |
|---|---|
| #484 | `replay_run`, `replay_trade` models; `ManifestResolver`; `data_hash` definition |
| #485 | `IntradayExitSimulator` (`services/replay/exit_simulator.py`) |
| #486 | `BenchmarkIngestor`, `RegimeClassifier` (`services/replay/benchmark.py`) |
| #300 | Metric formula conventions (R-multiple arithmetic, profit factor) |

## Requirements

Distilled from Q&A and issue body:

1. **SignalSource** loads `ScannerEvent`s for the frozen `(scanner_type, universe, date range)` from the
   DB. For days with no DB rows, it falls back to `scan_orchestrator.run()` in-memory
   (synchronously via `asyncio`), provided `supports_date_range=True`.

2. **Unsupported scanners.** When `supports_date_range=False` and no DB rows exist for one or more
   days in the range, `run_signal_replay` must set `status=failed` with a clear `error_message`
   (e.g. `"Scanner 'pre_market_v2' does not support historical generation and N days in the range
   have no ScannerEvents"`). `skipped_count` is reserved for per-signal simulation failures (no
   bars), not for structural coverage gaps. Additionally, the manifest-create endpoint (sub-issue
   #488) should perform a pre-flight check on this condition and reject the request before queuing
   the Celery task.

3. **Config provenance.** Because `ScannerEvent` carries no FK to the `ScannerConfig` that
   produced it, deep per-event config verification is not possible. Verification is limited to
   checking that each loaded event's `scanner_type` matches the run's frozen `scanner_type`. A
   `signal_source` field (`"db"` | `"generated"`) on `replay_run` records which path was taken for
   observability.

4. **data_hash** is computed and written by `run_signal_replay` after bars and signals are
   materialised — not by `ManifestResolver` at manifest creation time. `ManifestResolver` freezes
   only the *parameters* (config snapshot, universe list, date range); the task computes the
   *content fingerprint* over actual OHLCV + split-adj version + minute-bar count per
   `(ticker, day)`. A rerun that produces a different hash must surface the divergence rather than
   mask it.

5. **Headline metrics** are stored as individual scalar columns on `replay_run` (matching the
   `BacktestRun` pattern) so they are SQL-queryable for filtering and comparison. The complex
   analytics (calendar decay, holding-period decay, regime breakdown) are stored in the
   `replay_run.metrics` JSONB column as a nested dict with top-level keys `calendar_decay`,
   `holding_period_decay`, `regime_breakdown`. The JSONB blob may also mirror headline scalars
   for a single self-contained API payload, but scalar columns remain the source of truth.

6. **Celery task** uses `max_retries=0` (replay is deterministic — a retry produces the same result
   or the same error; transient failures need a new run, not an automatic retry).

7. **Metrics unit-tested** against a known hand-computed ledger with at least five controlled
   trades covering positive/negative/zero expectancy; calendar_decay and regime_breakdown
   verified from the same fixture.

8. **Benchmark failure** → `status=failed` with `error_message` set.

9. **Determinism:** re-running an identical manifest (same frozen snapshots) against unchanged bars
   yields an identical trade ledger and identical `data_hash`.

## Architecture

### Module layout

```
backend/app/
  services/
    replay/
      signal_source.py      # SignalSource — DB load + in-memory fallback
      metrics.py            # MetricsComputer
      # manifest.py, exit_simulator.py, benchmark.py from sub-issues 484/485/486
  tasks/
    replay.py               # run_signal_replay Celery task
```

### SignalSource (`services/replay/signal_source.py`)

```python
@dataclass
class LoadedSignals:
    signals: list[ScannerEvent | GeneratedSignal]
    signal_source: str          # "db" | "generated" | "mixed"
    days_missing: int           # days with no DB rows that required fallback
    days_unsupported: int       # days unreachable because supports_date_range=False
```

**Algorithm:**

1. Query `ScannerEvent` for `(scanner_type, ticker ∈ frozen_universe, date ∈ range)`.
2. Determine which trading days in the range have no DB events.
3. For missing days:
   - If `supports_date_range=True`: call `scan_orchestrator.run()` via
     `asyncio.new_event_loop()` (one loop, reused across all missing days — pattern from
     `backtest_service.py`), passing the frozen universe tickers. Events stay in-memory only
     (never written to `scanner_events`).
   - If `supports_date_range=False` and any day is missing: raise `SignalSourceError` with
     `days_missing` count. Caller sets `status=failed`.
4. Verify all loaded DB events have `scanner_type == run.scanner_type`; skip and log any that
   don't (defensive; should never happen given the query filter).
5. Return `LoadedSignals`.

### Celery task `run_signal_replay` (`tasks/replay.py`)

Follows the `run_backtest` pattern (`tasks/backtest.py`) as the thin orchestrator:

```
queued → running → {completed | failed}
```

**Pipeline (in order):**

```
1. Load replay_run from DB; set status=running; commit
2. Resolve manifest (ManifestResolver.verify_frozen_snapshots)
3. BenchmarkIngestor.ensure(benchmark_symbol, start_date, end_date, db)
   → failure raises BenchmarkError → status=failed
4. SignalSource.load(run, db)
   → SignalSourceError (unsupported + missing days) → status=failed
5. RegimeClassifier.build_regime_map(benchmark_symbol, start_date, end_date, db)
6. For each signal:
     trade = IntradayExitSimulator.simulate(signal, strategy_snapshot, bars)
     regime = regime_map[trade.entry_date]
     write replay_trade(…, regime_trend=regime.trend, regime_vol=regime.vol,
                        fill_source=trade.fill_source)
     if trade.exit_reason == "eod-no-fill" or bars_missing: skipped_count += 1
7. data_hash = compute_data_hash(tickers, date_range, db)   # SHA256 per #484 spec
8. MetricsComputer.compute(run_id, db) → MetricsResult
9. Persist headline scalars + metrics JSONB + data_hash + signal_source to replay_run
10. status=completed; completed_at=utc_now(); commit
```

All DB work in a single `SessionLocal()` context; `finally: db.close()`. Prometheus counters
mirror `run_backtest` (`celery_tasks_total`, `celery_task_duration_seconds`).

### MetricsComputer (`services/replay/metrics.py`)

**Input:** `run_id: int`, `db: Session` (reads committed `replay_trade` rows for the run).

**Outputs a `MetricsResult` dataclass:**

```python
@dataclass
class MetricsResult:
    # ── Headline (also written to scalar columns) ──────────────────────────────
    total_trades: int
    hit_rate: float | None          # wins / total_trades
    expectancy_r: float | None      # mean(result_r)
    profit_factor: float | None     # sum(+R) / abs(sum(-R))
    max_drawdown_r: float | None    # max peak-to-trough on R equity curve
    avg_bars_held: float | None
    median_bars_held: float | None
    avg_mfe_pct: float | None
    avg_mae_pct: float | None
    mfe_mae_ratio: float | None     # avg_mfe_pct / avg_mae_pct

    # ── Multi-dimensional (written to metrics JSONB) ───────────────────────────
    calendar_decay: list[dict]      # [{period, n, hit_rate, expectancy_r, …}, …]
    holding_period_decay: list[dict] # [{day, avg_return_r, avg_mfe_pct}, …] for day 1…max_hold_days
    regime_breakdown: list[dict]    # [{trend, vol, n, hit_rate, expectancy_r, …}, …]
```

**calendar_decay shape** mirrors `/api/v1/outcomes/edge-decay` response: list of dicts keyed by
`period` (a `"YYYY-Qn"` string, e.g. `"2025-Q4"`), plus the headline subset per bucket
(`n`, `hit_rate`, `expectancy_r`, `profit_factor`, `avg_mfe_pct`). Sourced from
`replay_trade.signal_date` quarter.

**holding_period_decay:** for each `day` from 1 to `run.max_hold_days`, compute mean
`return_r` and mean `mfe_pct` across all trades that were still open at day `day`
(i.e. `bars_held >= day`).

**regime_breakdown:** group `replay_trade` by `(regime_trend, regime_vol)`, compute headline
subset per cell.

### Headline scalar columns on `replay_run`

The `replay_run` model (from #484) already has `metrics` JSONB and `skipped_count`. The following
scalar columns must be added (via Alembic migration in this issue):

| Column | Type | Notes |
|---|---|---|
| `total_trades` | Integer | |
| `hit_rate` | Float | wins / total_trades |
| `expectancy_r` | Float | mean result_r |
| `profit_factor` | Float | |
| `max_drawdown_r` | Float | |
| `avg_bars_held` | Float | |
| `median_bars_held` | Float | |
| `avg_mfe_pct` | Float | |
| `avg_mae_pct` | Float | |
| `mfe_mae_ratio` | Float | |
| `signal_source` | String(20) | "db" \| "generated" \| "mixed" |

## Alternatives considered

### A. Single-file monolith (all logic in `tasks/replay.py`)

Simple to navigate initially. Rejected because it makes unit-testing individual stages (SignalSource,
MetricsComputer) difficult; each stage has distinct test fixtures and distinct failure modes.
The scanner decomposition `[PATTERN]` in backend memory (`_detect / _enrich / _persist`) endorses
separation.

### B. All metrics in JSONB only (no scalar columns)

Avoids a schema addition. Rejected because headline metrics like `hit_rate`, `expectancy_r`,
`profit_factor` are natural filter/sort dimensions for a run-list API (sub-issue #488). Querying
into JSONB keys for comparisons is fragile and slow without GIN indices. `BacktestRun` establishes
the scalar-column pattern for the same reason.

### C. ManifestResolver computes data_hash at manifest creation

Rejected because the hash covers actual OHLCV bars + minute-bar counts, which are not materialised
until the Celery task loads them. Computing the hash at creation time would either require a
full bar-load during the HTTP request (unacceptable latency) or hash only the parameter set
(not the content — defeating the purpose).

## Assumptions

- `replay_run` model from sub-issue #484 already has `metrics` (JSONB), `skipped_count` (Integer),
  `status`, `error_message`, `data_hash`, `max_hold_days`, `benchmark_symbol`, and the standard
  audit fields. Scalar headline columns listed above are additions introduced by this issue.
- `IntradayExitSimulator` (from #485) returns `bars_held` as a calendar-day count.
  `MetricsComputer` treats it uniformly as `bars_held` regardless of intraday vs daily resolution.
- `RegimeClassifier.build_regime_map()` returns a `dict[date, RegimeLabel]` covering every
  trading day in the run range. Missing dates (benchmark data gap) → raise `BenchmarkError` (not
  silently skip), consistent with requirement 8.
- `skipped_count` counts `replay_trade` rows where `exit_reason == "eod-no-fill"` plus signals
  that had no bars at all (written to `replay_trade` with `exit_reason="no_bars"`). It does NOT
  count structural coverage gaps from `supports_date_range=False` — those are run-level failures.

## Open questions (non-blocking)

1. **Config fingerprinting on ScannerEvent.** The Q&A revealed that `ScannerEvent` carries no link
   to the `ScannerConfig` that produced it. This means a future replay of the same date range
   could silently load events generated under a different config version. A `config_fingerprint`
   column on `ScannerEvent` (or a separate run-to-event provenance table) would close this gap.
   Not required for #487 but worth a follow-up ticket.

2. **signal_source at the trade level.** The current design records `signal_source` at the run
   level. If a run uses a mix of DB events (early dates) and generated events (recent dates),
   per-trade tracking could be more informative. Deferred to the UI drill-down issue (#490).

3. **Parallel signal simulation.** For large universes (1000+ tickers × multi-year ranges), sequential
   simulation may be slow. Celery task currently runs single-threaded. A thread-pool for the
   simulation loop could be explored later without changing the API contract.
