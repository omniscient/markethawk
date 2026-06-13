# Backtest Comparison Run: 5 Scanners × Representative Strategies

**Date:** 2026-06-13
**Issue:** #302
**Epic:** #300 (Backtest scanner signals against TradingStrategy definitions)
**Depends on:** #301 (backtest harness core — `BacktestRun`, `BacktestTrade`, `BacktestService`, Celery task, API)
**Status:** Spec

---

## Problem

Five scanner strategies are live and accumulating signals, but there is no evidence-based
answer to "which scanner performs best under which exit parameters?" This comparison run
executes the backtest harness across all five scanners and 3 representative exit profiles,
producing a committed Markdown table that quantifies win rate, profit factor, expectancy,
drawdown, and signal count for each combination.

---

## Requirements

1. Run the #301 harness for all five scanners — `pre_market_volume_spike`,
   `oversold_bounce`, `pocket_pivot`, `trend_pullback`, `liquidity_hunt` — against
   3 representative `TradingStrategy` definitions (defined below) on universe id=1.
2. Date range defaults to trailing 12 months ending at the last completed month; accepts
   `--start YYYY-MM-DD` / `--end YYYY-MM-DD` CLI overrides.
3. Produce a Markdown document committed to `docs/backtest/comparison-YYYY-MM-DD.md`
   containing: YAML frontmatter (run parameters), one 5×3 table per metric (scanners as
   rows, strategies as columns), and a Findings section identifying which combos have
   `expectancy_r > 0` with a trade-count credibility note (flag any cell with < 20 trades
   as low-sample).
4. No new DB models, no new API endpoints, no new Celery tasks beyond what #301 delivers.
5. The script (`scripts/run_backtest_comparison.py`) runs inside the backend Docker
   container and imports `SessionLocal` / `BacktestService` directly — no HTTP auth needed.
6. Strategy rows are created idempotently (get-or-create by `name`) so re-runs are safe.
7. Known limitation — `pre_market_volume_spike` depends on intraday pre-market minute bars
   stored in `StockAggregate (timespan='minute', is_pre_market=True)`. Over a 1-year replay
   window those are unlikely to be fully present; where missing the harness falls back to
   stored `ScannerEvent` rows or produces 0 signals. The comparison table must call out
   this limitation and instructs readers to interpret that scanner's row against its
   `trade_count`.

---

## Strategy Definitions

Three exit profiles cover the space the issue requests:

| Slug | entry_type | stop_pct | risk_reward_ratio | limit_offset_pct | allowed_sessions |
|------|-----------|----------|-------------------|-----------------|-----------------|
| `backtest-tight-2pct-2to1` | market | 2.0 | 2.0 | 0.0 | ["regular"] |
| `backtest-loose-4pct-1.5to1` | market | 4.0 | 1.5 | 0.0 | ["regular"] |
| `backtest-pullback-limit-2pct-2to1` | limit | 2.0 | 2.0 | -0.5 | ["regular", "pre"] |

- **Tight/market** (`backtest-tight-2pct-2to1`) — the issue's literal baseline ("2% stop / 2:1 R:R
  market entry"). The control row.
- **Loose/market** (`backtest-loose-4pct-1.5to1`) — wider stop, lower target. Tests whether scanners
  with noisy entries (oversold_bounce, liquidity_hunt) survive better with more room.
- **Pullback/limit** (`backtest-pullback-limit-2pct-2to1`) — limit entry 0.5% below trigger,
  `allowed_sessions: ["regular", "pre"]`. The "pre" session is required for
  pre_market_volume_spike signals (fired before open) to be simulatable at all under this
  profile. Harmless for the other four scanners.

All profiles: `paper_mode=True`, `requires_approval=False`, `risk_per_trade_pct=1.0`,
`direction="long_only"`, `max_trades_per_day=99`, `max_concurrent_positions=99`
(sizing irrelevant for R-unit stats; high caps prevent artificial signal exclusion).

---

## Architecture / Approach

### Script: `scripts/run_backtest_comparison.py`

```
Usage (inside the backend container):
  docker-compose exec backend python scripts/run_backtest_comparison.py [--start YYYY-MM-DD] [--end YYYY-MM-DD]

Steps:
1. Parse CLI args; compute default date range (first day of month 12 months ago → last day of prior month).
2. Open SessionLocal(); get-or-create the 3 TradingStrategy rows by name.
3. For each of the 5 scanner types × 3 strategy IDs → call BacktestService.enqueue_run()
   (creates BacktestRun row + dispatches Celery task). Collect 15 run UUIDs.
4. Poll BacktestRun.status every 5 seconds until all 15 reach "completed" or "failed".
   Print progress. Timeout after 30 minutes; exit with error if any run fails.
5. Fetch stats from each completed BacktestRun.
6. Render Markdown (see §Output Format).
7. Write to docs/backtest/comparison-{end_date}.md
```

### Output format: `docs/backtest/comparison-YYYY-MM-DD.md`

```markdown
---
universe_id: 1
universe_name: <resolved from DB>
ticker_count: <count of active tickers in universe>
start_date: YYYY-MM-DD
end_date: YYYY-MM-DD
max_hold_sessions: 10
strategies:
  backtest-tight-2pct-2to1:    {entry: market, stop_pct: 2.0, rr: 2.0, sessions: [regular]}
  backtest-loose-4pct-1.5to1:  {entry: market, stop_pct: 4.0, rr: 1.5, sessions: [regular]}
  backtest-pullback-limit-2pct-2to1: {entry: limit, limit_offset_pct: -0.5, stop_pct: 2.0, rr: 2.0, sessions: [regular, pre]}
generated_at: YYYY-MM-DDTHH:MM:SSZ
harness_issue: "301"
---

> **Note — `pre_market_volume_spike`**: this scanner fires on intraday pre-market minute bars.
> Where those are absent in the replay window the harness uses stored `ScannerEvent` rows only.
> Interpret its row against `trade_count`; a low count indicates limited historical data coverage.

## Expectancy (R)

| Scanner | tight-2pct-2to1 | loose-4pct-1.5to1 | pullback-limit |
|---------|-----------------|-------------------|----------------|
| trend_pullback | ... | ... | ... |
| oversold_bounce | ... | ... | ... |
| pocket_pivot | ... | ... | ... |
| pre_market_volume_spike | ... | ... | ... |
| liquidity_hunt | ... | ... | ... |

## Profit Factor

<same 5×3 grid>

## Win Rate (%)

<same 5×3 grid>

## Max Drawdown (%)

<same 5×3 grid>

## Trade Count

<same 5×3 grid>
⚠ Cells with fewer than 20 trades are marked with *.

## Findings

Combos with positive expectancy (expectancy_r > 0, trade_count ≥ 20):
- <bulleted list of scanner × strategy pairs that pass>

Best combo: <scanner>/<strategy> (expectancy_r = X.XX R, N trades)

Scanners negative across all strategies: <list, or "none">
```

---

## Alternatives Considered

### A. New `BacktestComparisonRun` DB model + API endpoint
Rejected. The issue is size:M and the ACs ask only for a committed document. A new model requires
Alembic migration + router + schemas + validation, which is its own M-sized issue. The #301 spec
already normalized `backtest_trades` into a queryable table specifically for cross-run comparisons
— the script can use those rows directly without a grouping entity.

### B. Celery chord fan-out task
Rejected. Workers don't have git context; committing a file from a Celery task is not a pattern
anywhere in the codebase and introduces a new deployment concern. The poll-then-render script
keeps commit in the developer's hands (or CI).

### C. HTTP API calls with auth token
Rejected in favor of direct DB/service import. The script runs inside the backend container where
`SessionLocal` is available; auth token management adds friction for a one-shot comparison run
with no external-service benefit.

---

## Open Questions (non-blocking)

1. **`max_hold_sessions`**: the spec hardcodes 10 (from the #301 default). If certain scanners
   commonly produce multi-week setups (trend_pullback especially), a larger value might surface
   more target hits. Configurable via a `--max-hold N` CLI flag in a follow-up.
2. **Pre-market minute bar backfill**: to get credible `pre_market_volume_spike` rows the
   universe's minute-bar history needs to cover the replay window. That's a Sync / Catch-Up
   operation outside this issue's scope; the comparison doc's note documents the gap.
3. **Automated re-run cadence**: once #302 ships, this comparison is a point-in-time document.
   If the spec is run again after more history accumulates, a new file is created (date-stamped
   name prevents overwrite). No automated refresh is in scope.

---

## Assumptions

- `BacktestService.enqueue_run()` (or equivalent) from #301 is callable from Python without
  going through the HTTP layer; if the #301 implementation exposes only an HTTP endpoint, the
  script will call `POST /api/v1/backtest/runs` with a token from `$BACKTEST_API_TOKEN`.
- `StockAggregate` daily bars (timespan='day') exist for universe_id=1 for the chosen date range;
  tickers without bars are naturally skipped by the harness per #301 requirement 7.
- Universe id=1 is the "main liquid universe" referenced in the issue (confirmed by DB migration
  seed). If the operator has a different primary universe, they pass `--universe-id N`.
- `docs/backtest/` directory is created by the script if absent.
