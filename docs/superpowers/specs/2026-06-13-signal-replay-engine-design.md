# Canonical Signal Replay Engine — Design

**Status:** Approved 2026-06-13
**Epic:** #483 — "Canonical Signal Replay Engine"
**Depends on:** #300 (Backtest scanner signals against TradingStrategy definitions)
**Source:** Best-in-class features brainstorm, feature #5 — "MarketHawk must not be dismissed as 'just a scanner UI.'"

## 1. Problem & goal

MarketHawk can generate scanner signals historically and accumulate *forward* outcome
evidence (price snapshots after a signal fires), but it has no **reproducible backtest**:
no simulated entries/exits against a strategy, no edge-decay or regime analysis tied to a
pinned dataset, and nothing you can re-run and prove identical months later.

The goal is a **canonical Signal Replay Engine**: given a scanner config, a frozen
universe, a date range, a `TradingStrategy`, and a max-hold, produce a persisted,
reproducible **replay run** — a per-trade ledger with simulated intraday-accurate
entries/exits plus the analytics that make a backtest credible (hit rate, expectancy,
profit factor, max drawdown, MFE/MAE, calendar + holding-period edge decay, regime
breakdown) and a four-view UI to explore it.

"Canonical" means: every run carries an **immutable manifest + data hash**, so a re-run
with the same inputs is provably identical and silent data drift (splits/backfills
rewriting history) is detected.

## 2. Three-layer context (what exists vs. what this adds)

| Layer | What it is | State |
|---|---|---|
| **Forward outcomes** | `OutcomeService` + `ScannerOutcomeSnapshot`/`Summary`: live price snapshots after a signal fires; MFE/MAE/follow-through; `/api/v1/outcomes/edge-decay` over accumulating evidence. No strategy, no entry/exit, not reproducible. | Built |
| **#300 MVP harness** | Daily-bar replay pairing scanner signals × `TradingStrategy` exits → win-rate / profit-factor report. Owns the `ExitSimulator` interface, the **daily** implementation, and the metric formulas. | Planned |
| **Canonical Signal Replay Engine** (this epic) | Reproducible, manifest-pinned, **intraday-accurate** replay *runs* as first-class persisted entities + regime/holding-period analytics + benchmark ingestion + full replay UI. | This design |

## 3. Scope

**In scope:** reproducible replay runs (manifest + data hash); intraday-accurate exit
simulation with daily fallback; per-trade ledger; headline metrics; calendar-time **and**
holding-period edge decay; regime breakdown via a configurable benchmark; four UI views
(run summary + equity curve, edge-decay & regime charts, per-signal drill-down, run
comparison).

**Non-goals:** portfolio-level cross-position risk; multi-leg/options; live-trading
wiring; parameter optimization / walk-forward sweeps (future epic); re-implementing
#300's daily engine (we depend on it — see §11).

## 4. Decisions (approved 2026-06-13)

1. **Relation to #300:** two epics with an explicit dependency. #300 stays the standalone
   MVP harness; this epic layers the canonical differentiators on top.
2. **Reproducibility:** immutable manifest + content **data hash** (detects silent drift).
3. **Exit fidelity:** intraday-accurate against minute bars, with a conservative daily
   fallback when minute data is missing.
4. **Regime source:** ingest a configurable benchmark (default **SPY**), derive trend × vol
   regimes; benchmark symbol is a manifest field so QQQ/IWM/sector ETF/VIX swap in without
   code changes.
5. **Edge decay:** both calendar-time (by quarter) and holding-period (by days-since-entry).
6. **UI:** all four views in scope.
7. **`max_hold_days`** lives on the **manifest**, not on `TradingStrategy` (which has no
   time-stop field); promotable to the strategy later.
8. **Benchmark storage:** reuse `StockAggregate` (benchmark is just another ticker), no
   parallel table.
9. **Equity curve:** **R-multiples** as the primary, sizing-independent series; dollar
   equity (using `risk_per_trade_pct`) optional/secondary.

## 5. Architecture (Approach A — first-class persisted runs)

### 5.1 Data model (new)

**`replay_run`** — manifest + lifecycle:
- `id`, `uuid`, `status` (`queued`/`running`/`complete`/`failed`)
- `scanner_type`, `scanner_config_snapshot` (JSONB, frozen params)
- `trading_strategy_id` (FK), `strategy_snapshot` (JSONB, frozen)
- `universe_id` (FK), `universe_snapshot` (JSONB — ticker list frozen at creation)
- `start_date`, `end_date`, `max_hold_days`
- `exit_fidelity` (`intraday`/`daily`), `benchmark_symbol`
- `data_hash` (SHA256, see §7)
- `metrics` (JSONB — cached aggregates computed at completion)
- `skipped_count`, `error_message`, `created_at`, `completed_at`

**`replay_trade`** — one row per simulated trade:
- `id`, `replay_run_id` (FK), `scanner_event_id` (FK, nullable), `ticker`
- `signal_date`, `entry_date`, `entry_price`, `direction`
- `stop_price`, `target_price`
- `exit_date`, `exit_price`, `exit_reason` (`stop`/`target`/`time`/`eod-no-fill`)
- `return_pct`, `return_r` (R-multiple), `mfe_pct`, `mae_pct`, `bars_held`
- `regime_trend`, `regime_vol`, `fill_source` (`intraday`/`daily-fallback`)

`metrics` is cached on the run so the report view is a single-row read; per-trade,
decay, and regime drill-downs query `replay_trade`.

### 5.2 Components

1. **ManifestResolver** — freezes config/strategy/universe snapshots, resolves the date
   range, computes the data hash, ensures the benchmark is ingested.
2. **SignalSource** — gets historical signals for the range. Reuses `scan_orchestrator`
   historical generation (`supports_date_range`); if matching `ScannerEvent`s already
   exist for the range *and* match the frozen config, loads them instead of regenerating.
3. **ExitSimulator** — protocol `simulate(signal, strategy, bars) -> Trade`. **#300 provides
   the interface, the daily implementation, and the metric formulas; this epic adds
   `IntradayExitSimulator`** (minute bars, real stop/target ordering, daily fallback).
4. **RegimeClassifier** — given a benchmark symbol, classifies each trading day into
   `(trend, vol)`.
5. **MetricsComputer** — aggregates the trade ledger into headline metrics, calendar decay,
   holding-period decay, and regime breakdown.
6. **BenchmarkIngestor** — pulls the benchmark's daily bars via the Polygon provider on demand.
7. **ReplayAPI** + **ReplayUI**.

### 5.3 Execution flow — Celery task `run_signal_replay`

```
create replay_run (status=queued)
 → resolve manifest: freeze snapshots, compute data_hash, ensure benchmark ingested
 → SignalSource: load/generate signals for (config, universe, range)
 → RegimeClassifier: build per-day regime map over the range
 → for each signal: ExitSimulator.simulate(...) → write replay_trade (+ regime at entry)
 → MetricsComputer: compute aggregates → replay_run.metrics
 → status=complete (or failed + error_message)
```

Deterministic: same manifest + same `data_hash` ⇒ identical trades.

## 6. Exit simulation

- **Entry:** next session **open** after the signal (matches #300). `entry_type=limit` →
  fill only if the limit (`trigger × (1 ± limit_offset_pct/100)`) trades within the entry
  day's minute bars, else `exit_reason=eod-no-fill` (no trade recorded as a position).
  Direction from `TradingStrategy.direction`; long-biased scanners under `short_only` are
  inverted.
- **Stop/target:** derived from `stop_pct` and `risk_reward_ratio`. **Intraday:** walk minute
  bars in time order; the first level touched wins. **Daily fallback** (no minute data that
  day): conservative **stop-first** when a daily bar's range touches both levels.
- **Time exit:** close at the open of `entry_date + max_hold_days` if neither level is hit.
- **Returns:** recorded in both `%` and **R-multiples** (1R = entry→stop distance), so
  expectancy and the equity curve are sizing-independent.
- **MFE/MAE:** max favorable / adverse excursion over the held window, from the same bars.

## 7. Manifest & data hash

`data_hash = SHA256` over a canonical (sorted, stable-serialized) sequence of, for each
`(ticker in frozen universe, trading day in range)`:
the daily bar OHLCV + split-adjustment version + that day's minute-bar count.

Rationale: cheap (≈ tickers × trading-days rows; e.g. 500 × 252 ≈ 126k, hashed in-process)
and it catches the one failure mode that breaks reproducibility — splits/backfills silently
rewriting history. Stored on the run; recomputed and compared on re-run. A mismatch creates
a new run and the comparison view flags the pair as **not strictly comparable**.

## 8. Regime classification

Per benchmark trading day:
- **trend** = benchmark close above/below its SMA200 → `bull` / `bear`.
- **vol** = realized-volatility (or ATR) bucket → `calm` / `normal` / `turbulent`
  (thresholds in run config, with documented defaults).

`benchmark_symbol` is a manifest field (default `SPY`). Each trade records the regime at
its entry date (`regime_trend`, `regime_vol`).

## 9. Metrics

- **Headline:** hit rate, expectancy (R), profit factor, max drawdown (off the R equity
  curve), avg & median hold (`bars_held`), avg MFE / MAE, MFE/MAE ratio, total trades.
- **Calendar decay:** the headline set bucketed by quarter (response shape mirrors the
  existing `/api/v1/outcomes/edge-decay`, but sourced from `replay_trade`).
- **Holding-period decay:** avg cumulative return + MFE by day-since-entry (1 … `max_hold_days`).
- **Regime breakdown:** the headline set per `(trend × vol)` cell.

## 10. API surface — `/api/v1/replay`

- `POST /runs` — create + enqueue; returns the run.
- `GET /runs` — list (filter by scanner_type, strategy, status).
- `GET /runs/{id}` — manifest + cached metrics.
- `GET /runs/{id}/trades` — paginated/sortable ledger.
- `GET /runs/{id}/analytics` — calendar decay + holding-period decay + regime breakdown.
- `GET /runs/compare?ids=a,b[,c]` — side-by-side metrics; flags data-hash mismatch.

## 11. UI views — `/replay`

1. **Run summary + equity curve** — headline panel + cumulative R equity curve over the range.
2. **Edge-decay & regime charts** — calendar-decay bars, holding-period curve, regime grid.
3. **Per-signal drill-down** — sortable trade table; clicking a trade opens the ticker's
   Lightweight Chart with entry/stop/target/exit markers (reuses the existing chart component).
4. **Run comparison** — compare two+ runs on the same metrics; mismatched data hashes flagged.

## 12. Dependency on #300 (the seam)

- **#300 owns:** the `ExitSimulator` *interface*, the **daily** implementation, and the
  metric formulas.
- **This epic owns:** `IntradayExitSimulator`, reproducible run orchestration (manifest +
  hash), benchmark ingestion + regime, holding-period decay, and the UI.
- **Parallelizable:** data model, benchmark/regime, and manifest work do not block on #300;
  only the simulator/metrics consumption does. If #300 slips, this epic absorbs the
  interface + daily implementation as part of sub-issue 2.

## 13. Error handling & edge cases

- Insufficient bars for a signal → skip the trade, increment `replay_run.skipped_count`
  (logged, run still succeeds).
- Missing benchmark → ingest on demand; if ingestion fails → run fails with a clear message.
- Universe changed after run creation → irrelevant (membership is frozen in the snapshot).
- Data-hash mismatch on re-run → new run; comparison view flags the pair.
- `eod-no-fill` limit entries → recorded as no-position, surfaced in the run summary.

## 14. Testing

- **Exit simulator:** deterministic fixture of synthetic minute/daily bars with hand-computed
  outcomes (stop-first, target-first, time-exit, no-fill, daily-fallback) → assert exact trades.
- **Metrics:** unit-tested against a known ledger (R-multiple expectancy, profit factor, max DD).
- **Regime classifier:** scripted benchmark series → asserted trend/vol labels.
- **Manifest hash:** stability (same inputs ⇒ same hash) + drift detection (mutated bar ⇒
  changed hash).
- Per CLAUDE.md: live `curl` validation of each endpoint + clean `alembic upgrade head`
  before commit.

## 15. Epic decomposition (sub-issues of #483)

1. **#484 — Replay data model + manifest resolver + data hash** — `replay_run` /
   `replay_trade` tables, frozen snapshots, hash function, Alembic migration. *(size: M)*
2. **#485 — Intraday-accurate exit simulator** — implements #300's `ExitSimulator` interface
   using minute bars + daily fallback; deterministic; direction handling. *(size: L, depends on #300)*
3. **#486 — Benchmark ingestion + regime classifier** — on-demand benchmark ingest
   (configurable symbol) + per-day trend × vol classification + lookup service. *(size: M)*
4. **#487 — Replay execution task + metrics** — Celery `run_signal_replay` pipeline + headline /
   calendar / holding-period / regime metrics. *(size: L, depends on #300, #484, #485, #486)*
5. **#488 — Replay API** — runs CRUD, trades, analytics, compare endpoints + schemas.
   *(size: M, depends on #484, #487)*
6. **#489 — Replay UI (report)** — run summary + equity curve + edge-decay & regime charts.
   *(size: L, depends on #488)*
7. **#490 — Replay UI (explore)** — per-signal drill-down (chart markers) + run comparison.
   *(size: M, depends on #488)*
