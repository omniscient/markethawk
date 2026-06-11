# Trend Pullback Scanner — Design

**Date:** 2026-06-10
**Status:** Approved (brainstorming session with Frank)

## Goal

Add a new daily-chart scan strategy with a favorable win/loss character: stocks in
confirmed uptrends pulling back in an orderly way to a rising moving average
("strong stock, routine dip"). Complements the existing scanners — `oversold_bounce`
covers "beaten down, snap back", `pocket_pivot` covers volume thrust; nothing covers
trend continuation entries.

## Decisions made during brainstorming

1. **Phased validation.** The scan ships first with outcome tracking; a backtest
   harness is backlogged (see §4). "Positive win/loss ratio" becomes measurable
   via the harness later; until then the existing outcome-snapshot system
   accumulates forward evidence.
2. **Strategy style: trend-following pullback** (chosen over deeper Connors-style
   mean reversion, which overlaps `oversold_bounce`, and over breakouts, whose
   ~35–45% win rate fails the win-rate criterion).
3. **No new exit/outcome modeling.** Win/loss semantics belong to the existing
   `TradingStrategy` model (`stop_pct`, `risk_reward_ratio`, entry type). The scan
   produces signals only. Outcome measurement reuses
   `ScannerConfig.outcome_config` + `OutcomeService` snapshots/summaries.

## §1 Signal definition: `trend_pullback`

Daily-bar scan, runs after close (same scheduling model as `pocket_pivot`),
long-only. A ticker fires on `event_date` when **all** criteria hold on daily
aggregates (`StockAggregate`, `timespan='day'`, ~260 bars lookback):

| Criterion | Rule | Parameters (seed defaults) |
|---|---|---|
| Established uptrend | close > SMA(50) > SMA(200), and SMA(50) rising over the last 20 sessions | `trend_sma_fast=50`, `trend_sma_slow=200`, `sma_rising_lookback=20` |
| Near highs (strength) | close within 15% of the 252-day high | `max_pct_off_high=15` |
| Pullback in progress | day's low ≤ SMA(20) × 1.01 (tagged the 20-day MA) after ≥5 consecutive prior closes above it | `pullback_sma=20`, `pullback_sma_tolerance_pct=1`, `min_days_above_sma=5` |
| Orderly, not breakdown | pullback depth from the 20-day swing high between 3% and 12%; no close below SMA(50) during the pullback | `pullback_min_pct=3`, `pullback_max_pct=12` |
| Reset confirmed | RSI(5) < 40 (local RSI computation, same pattern as `oversold_bounce_scan`) | `rsi_period=5`, `rsi_max=40` |
| Liquid enough | 20-day average dollar volume ≥ $5M and close ≥ $5 | `min_dollar_vol=5000000`, `min_price=5` |

All thresholds live in `ScannerConfig.parameters` — tunable without code changes.

**Event payload:**

- `indicators`: SMA(20/50/200), RSI(5), pct_off_252d_high, pullback_depth_pct,
  consecutive days above SMA(20) before the tag, ATR(14) (for downstream sizing
  by `TradingStrategy`), 20-day avg dollar volume.
- `criteria_met`: one boolean per row of the table above.
- `severity`: `high` when pullback depth ≤ 8% **and** RSI(5) < 30; `medium`
  otherwise. (Severity values stay within the frontend's `low|medium|high` set.)

## §2 Outcome tracking (existing harness, one expansion)

Seed `outcome_config` on the config row, same shape as the existing scanners:

```json
{
  "intervals": ["1d", "2d", "5d", "10d"],
  "follow_through_threshold_pct": 2.0,
  "reference_price_source": "opening_price",
  "extra_metrics": []
}
```

**Only harness change:** add `"10d": timedelta(days=10)` to the `interval_map` in
`OutcomeService.capture_snapshot` (`backend/app/services/outcome_service.py:92`).
A 3–10 day swing setup needs a horizon past 5d; the addition is one line and
backward compatible (other scanners simply don't request it).

Everything else — pending snapshot creation, MFE/MAE capture, follow-through
flag, `ScannerOutcomeSummary` rollups — is reused untouched.

## §3 Integration points

- **Service:** `backend/app/services/trend_pullback_scan.py`, modeled on
  `pocket_pivot.py` — helpers for fetching daily bars / computing indicators,
  per-(ticker, date) evaluation loop, `_save_event(...)`, registered via
  `@register(ScannerDescriptor(key="trend_pullback", supports_date_range=True))`.
- **Task map:** add `"trend_pullback"` entry to `scanner_map` in
  `backend/app/tasks/scanning.py`.
- **Seed migration:** one Alembic revision inserting the `scanner_configs` row —
  `scanner_type='trend_pullback'`, `is_active=true` (note: a prior seed bug set
  `is_active=false` and hid the scanner from the UI — see memory/migration
  `c7e2a9f4b1d3`), `parameters` from §1, `outcome_config` from §2,
  `data_requirements` matching the existing daily scanners.
- **Frontend:** none — auto-discovered via `/api/v1/scanner/types` and
  `/api/v1/scanner/configs`.

## §4 Backlogged follow-ups (tickets, not built now)

1. **Backtest harness (epic):** replay `TradingStrategy` definitions
   (stop/target/entry) against historical `ScannerEvent` signals from any
   registered scanner; report win rate, profit factor, expectancy, max drawdown
   per (scanner × strategy) pair. Daily-bar replay first; historical signals
   generated via the scanners' existing `supports_date_range` mode.
2. **Comparison run:** execute the harness for `trend_pullback` + the 4 existing
   scanners over ≥1 year of history; publish a comparison table.
3. **Outcome dashboard (optional):** surface `ScannerOutcomeSummary` win-rate
   aggregates per scanner in the UI.

## Acceptance criteria

- Running the scan over a historical date range on a liquid universe produces
  `ScannerEvent` rows with full `indicators`/`criteria_met` payloads and graded
  severity; tickers in downtrends or fresh breakdowns do not fire.
- Pending outcome snapshots (including `10d`) are created for each event and
  capture successfully once bars exist.
- Scanner appears in the UI scanner dropdown with its parameters, no frontend
  changes.
- Backend validated live per CLAUDE.md rules (reload check, `curl` the scan
  trigger + results endpoints, `alembic upgrade head` clean) before commit.

## Out of scope

- Backtesting engine (ticketed separately, §4).
- Short-side signals, intraday refinement of entries, auto-trading wiring
  (`AlertRule` → `TradingStrategy` linkage is user configuration, not code).
- New indicator infrastructure in `chart_indicators.py` (that module is
  intraday-pattern focused; the scan computes its own daily indicators like the
  other daily scanners do).
