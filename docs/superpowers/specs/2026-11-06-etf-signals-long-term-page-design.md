# Nightly Total-Return ETF Signals + Read-Only Long-Term Page — Design

**Issue:** #905
**Date:** 2026-11-06
**Status:** Proposed — pending implementation plan
**Depends on:** #904 (LT-1: roster + data path) — unconditional. This spec is written against
#904's planned schema (epic §4.1/§4.2) and cannot be implemented until #904 lands. See
Assumptions.

## 1. Overview / Problem Statement

MarketHawk's intraday scanner has no analog for long-term, buy-and-hold investing. Epic #902
("Long-term ETF investing") adds a separate surface built around a curated roster of ~65 US and
Canadian ETFs, with the first slice (#904) getting bars, dividends, and FX into the database.
This issue (LT-2, slice 2 of 5) is the first slice that produces anything visible: a nightly job
that turns those raw daily bars into a per-ETF signal table (trend, drawdown, percentile
cheapness, a transparent "on sale" score), read endpoints over that table, and a read-only
`/long-term` dashboard page that reuses the existing chart component. Portfolio, proposals, and
the MCP server are later slices and explicitly out of scope here.

The goal of this slice, concretely: every active roster ticker has a signal row for the latest
trading day, computed from a **total-return** close series (raw closes adjusted in memory for
dividends — never stored, so a corrected dividend record is picked up automatically on the next
run), and a human can open `/long-term` and see, at a glance, what's cheap relative to its own
history and how the market is trending.

## 2. Requirements (from Q&A)

1. **Dependency sequencing.** This spec is written in full against #904's planned schema, not
   stubbed. #904 is still `spec-pending-review` as of this writing — see Assumptions for exactly
   what's consumed from it, and Open Questions for the re-verification step this implies.
2. **Signal computation is one nightly batch task**, not fan-out-per-ticker, looping over the
   ~65 active roster rows in one process. Per-ticker failures are caught and logged individually
   so one bad ETF doesn't block the other 64 or roll back the whole run.
3. **The per-ticker signal computation lives in one shared service function** used by both the
   nightly task and an on-demand recompute endpoint — there is exactly one code path that
   produces a signal row, never two.
4. **On-demand recompute is synchronous and in scope** for this slice despite its "read-only"
   framing: "read-only" here means no user-input writes (accounts, positions, constraints,
   proposals — all later slices), not "no endpoint ever issues a DB write." Recomputing derived
   signal data from bars that already exist is idempotent and safe to do synchronously.
5. **Every active roster ticker gets a signal row every trading day**, regardless of how much
   history it has. Columns that can't be computed yet because the required lookback window isn't
   available are stored as SQL `NULL`, not skipped — `close`, `date`, `history_days`, and
   `short_history` are always populated so a short-history ETF (e.g. IBIT/ETHA) still appears on
   the page with an "insufficient history" indicator instead of silently vanishing.
6. **Percentile rank, benchmark self-reference, and NULL propagation follow the exact rules in
   §3.3** below — these are not left to the builder; they were pinned during refinement because
   they affect what the page can correctly display.
7. **Frontend**: read-only `/long-term` page per epic §4.8 items 1–6 only (header strip, on-sale
   cards, movers, trend split, roster table, detail drawer). Portfolio and Proposals tabs are
   explicitly later slices and must not be started here.
8. Acceptance (from the issue): signal rows exist for every active roster ticker for the latest
   trading day; the page renders real data; `npx tsc --noEmit` is clean; backend endpoints are
   curl-verified.

## 3. Architecture / Approach

### 3.1 Data model

New SQLAlchemy model `EtfSignalDaily` (`backend/app/models/etf_signal_daily.py`), table
`etf_signal_daily`, added to `backend/app/models/__init__.py` per the project's "new models"
checklist in `CLAUDE.md`. One row per active roster ticker per trading day:

| Column | Type | Notes |
|---|---|---|
| `id` | `Integer`, PK | |
| `ticker` | `String(20)` | FK-by-convention to `lt_etf.ticker` (string FK, matching the project's existing ticker-as-string convention, not an integer FK to the roster row) |
| `date` | `Date`, indexed | trading day this row is for |
| `close` | `Numeric` | raw close on `date` (not total-return-adjusted — total-return is used only to *derive* the metrics below, per epic §4.2/§4.3, and is never itself stored) |
| `ret_1d`, `ret_1w`, `ret_1m`, `ret_3m`, `ret_6m`, `ret_1y` | `Numeric`, nullable | |
| `sma_50`, `sma_200` | `Numeric`, nullable | |
| `pct_from_sma_50`, `pct_from_sma_200` | `Numeric`, nullable | |
| `above_sma_50`, `above_sma_200`, `golden_cross` | `Boolean`, nullable | |
| `high_52w`, `drawdown_52w_pct` | `Numeric`, nullable | |
| `high_5y`, `drawdown_5y_pct` | `Numeric`, nullable | |
| `pctile_1y`, `pctile_5y` | `Numeric`, nullable | 0–100, 0 = cheapest in window |
| `atr_14_pct` | `Numeric`, nullable | Wilder ATR14, raw closes, as % of close |
| `rsi_14` | `Numeric`, nullable | raw closes |
| `rel_ret_1y_vs_benchmark` | `Numeric`, nullable | `ret_1y - SPY.ret_1y`, same `date` |
| `history_days` | `Integer`, not null | count of stored daily bars as of `date` |
| `short_history` | `Boolean`, not null | `history_days < 756` |
| `on_sale_score` | `Numeric`, nullable | see §3.3 |
| `computed_at` | `DateTime`, default `utc_now` | |

Unique index on `(ticker, date)`; index on `date` alone for the "latest row per ticker" and
market-overview queries. Numeric (not Float) for all price/percentage columns, matching
`StockAggregate`'s existing convention.

### 3.2 Service layer

`backend/app/services/long_term/` (new subpackage, following the `services/replay/` precedent
for a multi-module service area):

- `signals.py` — `compute_signals_for_ticker(db: Session, ticker: str, as_of: date) ->
  EtfSignalDaily`: the single function that builds the total-return close series in memory
  (raw closes from `StockAggregate` + ex-dividend adjustment factors from `lt_dividend`,
  applied cumulatively backwards from the latest close, per epic §4.2), computes every column in
  §3.1, upserts the row, and returns it. Used by both the nightly task and the on-demand
  endpoint — there is no second implementation.
- `roster.py` — read helpers over the `lt_etf` roster (from #904) joined with latest
  `EtfSignalDaily` rows, for the roster-listing and market-overview endpoints.

Indicator implementation: pandas, following `services/trend_pullback_scan.py`'s existing
`_calc_rsi`/`_calc_atr` pattern (Wilder-smoothed) rather than `services/chart_indicators.py`'s
ATR (SMA-smoothed — that one is for the frontend chart overlay, not Wilder, and is not
appropriate for `atr_14_pct` per epic §4.3's explicit "Wilder ATR14" wording). Percentile rank
follows the one existing rank helper in the codebase, `services/pre_market_scan.py`'s
`window.rank(pct=True)` pattern, rescaled per §3.3 below.

### 3.3 Signal formula edge cases (pinned during refinement)

- **Percentile rank.** For `pctile_1y`: trailing window of the most recent 252 bars of the
  total-return series, **inclusive of today's close**. For `pctile_5y`: trailing window of
  `min(history_days, 1260)` bars, inclusive of today. Compute `rank(pct=True)` over the window,
  then rescale `(rank - 1) / (n - 1) * 100` so the cheapest close in the window is exactly `0`
  and the most expensive is exactly `100` (plain `rank(pct=True)` never reaches exactly 0, which
  the spec's "0 = cheapest" wording requires). Ties use pandas' default `method="average"`.
- **NULL vs. skip.** Every active roster ticker gets a row every trading day. `close`, `date`,
  `history_days`, `short_history` are always populated. Columns gated on a 1-year lookback
  (`ret_*`, `sma_50`/`sma_200` and their derived pct/boolean/`golden_cross` columns, `rsi_14`,
  `atr_14_pct`, `high_52w`, `drawdown_52w_pct`, `pctile_1y`) are `NULL` until 252 bars of history
  exist, then compute normally — this can happen while `short_history` is still `true`, since
  that flag's own threshold (756 bars) is independent and higher. Columns gated on the 5-year
  lookback (`high_5y`, `drawdown_5y_pct`, `pctile_5y`) need at least 252 bars (not 1260 — they
  use whatever history exists, capped at 1260) and are `NULL` below that. This asymmetry is
  intentional: the `on_sale_score` short-history rule (drop `pctile_5y` from the mean) only makes
  sense if `pctile_5y` can be non-NULL while `short_history` is still `true`.
- **`on_sale_score`.** `100 - mean(pctile_1y, pctile_5y, clamp(50 + pct_from_sma_200, 0, 100))`;
  drop `pctile_5y` from the mean when `short_history` is `true`. If any input remaining in the
  mean is `NULL`, `on_sale_score` is `NULL` for that row. Keep this in one function
  (`compute_on_sale_score`) so it stays swappable per epic §4.3.
- **Benchmark self-reference.** SPY's own `rel_ret_1y_vs_benchmark` is `0` — the formula
  naturally yields `ret_1y - ret_1y` with no special case. It's `NULL` only if `ret_1y` itself is
  `NULL` for that ticker or for SPY on that date (same NULL-propagation rule for every ticker).
  The nightly task computes/loads SPY's `ret_1y` before the rest of the roster so every other
  ticker's row can reference it within the same run.

### 3.4 Nightly task + on-demand recompute

New Celery task `compute_etf_signals_nightly` in `backend/app/tasks/scanning.py` (or a new
`backend/app/tasks/long_term.py` if the builder prefers a dedicated module — either follows
existing precedent), styled after `sync_universe_aggregates_nightly`: one batch task, loops over
active `lt_etf` roster rows, calls `compute_signals_for_ticker` per ticker, catches and logs
per-ticker exceptions without aborting the run. Registered in `celery_app.conf.beat_schedule`
with its own fixed crontab slot after the nightly aggregate sync's `01:30 UTC Tue–Sat`, e.g.
`02:30 UTC Tue–Sat` — following the existing convention where "runs after X" means a fixed time
offset, not task chaining (there is no chaining mechanism in this codebase today).

On-demand recompute: `POST /api/v1/long-term/etfs/{ticker}/recompute`, calls
`compute_signals_for_ticker` synchronously for `as_of = today`, upserts, and returns the fresh
row in the same schema as the single-ETF GET. Precedent: `POST /api/v1/universes/{id}/refresh-
stats` already does synchronous recompute-and-persist in this codebase; the heavier `.delay()` +
202 + `task_id` pattern (`POST /outcomes/analyze`) is reserved for genuinely long-running jobs,
which per-ticker signal computation is not.

### 3.5 REST API

New router `backend/app/routers/long_term.py`, `APIRouter(prefix="/api/v1/long-term",
tags=["long-term"])`, same cookie auth as every other router (no new auth mechanism — that's
MCP-server territory in a later slice). Pydantic schemas in `backend/app/schemas/long_term.py`.
Read-only-for-user-input endpoints this slice needs:

- `GET /roster` — active roster rows joined with latest `EtfSignalDaily`, filterable by
  `segment`/`country` (query params), for the roster table.
- `GET /etfs/{ticker}` — roster row + latest signal row + daily close/SMA history for the
  detail drawer's chart (reuses `StockDataService`-style historical fetch already used by
  `routers/stocks.py`, scoped to the ticker's own bars).
- `GET /overview` — on-sale top N (by `on_sale_score`), movers (top/bottom by `ret_1w` and
  `ret_1m`), trend split (above/below `sma_50`, grouped by segment), benchmark (SPY) signals —
  the single call the header strip and dashboard sections need.
- `POST /etfs/{ticker}/recompute` — see §3.4.

Movers list length: 5 each (best/worst × 1w/1m) — not specified by the epic beyond "two short
lists"; chosen to mirror the "top 8" on-sale-card count being the only explicit number in the
epic, scaled down for a secondary section. This is a builder-adjustable default, not a hard
requirement.

### 3.6 Frontend

Route `/long-term` in `frontend/src/App.tsx`; sidebar entry in `frontend/src/components/
Layout.tsx`'s `navigation` array. Icon: `LineChart` from `lucide-react` (not yet used elsewhere
in `Layout.tsx`; the epic's suggested `TrendingUp`-style icon is already taken by "Pre-market
Movers"). New API module `frontend/src/api/longTerm.ts` following the existing
`frontend/src/api/stocks.ts` / `frontend/src/api/scanner/` facade conventions (one module per
resource, typed response interfaces, thin wrappers over the shared Axios client). New page
`frontend/src/pages/LongTerm/` with React Query hooks per endpoint, laid out per epic §4.8 items
1–6: header strip, on-sale cards (top 8), movers, trend split, sortable/filterable roster table,
detail drawer.

Detail drawer: reuse the existing `Modal` component (`frontend/src/components/ui/Modal.tsx`)
controlled by local `useState<string | null>` on the page holding the selected ticker, following
the exact pattern already used by `UniverseDetailsModal` + `Universes.tsx` (`isOpen`/`onClose`
props, `enabled: isOpen && !!ticker` on the detail query) — not a separate route, consistent
with how the rest of this codebase handles list→detail drill-in. Inside the drawer: the existing
`StockChart` component (`frontend/src/components/ui/StockChart.tsx`) in daily mode, with
`showDoubleSuperTrend` and `priceLines` built from the signal row's `sma_50`/`sma_200` (two
entries, distinct colors, labeled "SMA50"/"SMA200"), plus the full signal row rendered as a
stat grid below the chart. Builder reads the `dataviz` skill before writing any new chart/card
styling, per the issue body.

## 4. Alternatives Considered

- **Fan-out one Celery task per ticker** for the nightly computation, matching
  `sync_tickers_batch`/`sync_ticker_details`'s per-ticker pattern. Rejected: the roster is small
  (~65) and fixed, unlike the screener's dynamic universes that motivated the fan-out pattern;
  one batch task gives one log line/result per run and is simpler to reason about for a fixed,
  small set.
- **Fire-and-forget on-demand recompute** (`.delay()` + 202 + `task_id`, client re-polls),
  matching `POST /outcomes/analyze`. Rejected: per-ticker signal computation is small and fast
  (it's a bounded pandas computation over at most 1260 cached bars), so a synchronous round trip
  is simpler for the frontend and matches the lighter-weight `refresh-stats` precedent rather
  than the heavy-job precedent.
- **Skip the signal row entirely** for tickers without enough history, rather than storing NULLs.
  Rejected: it would make a short-history ETF (explicitly called out for IBIT/ETHA) disappear
  from the roster table and overview instead of showing with an "insufficient history" indicator,
  and would complicate "every active roster ticker has a row" as a simple invariant to test
  against.
- **Store the total-return-adjusted close series** instead of recomputing it in memory every run.
  Rejected by the epic itself (§4.2): a corrected/late dividend record must be picked up
  automatically on the next run without a backfill/reprocessing step, which only works if the
  adjusted series is never persisted.

## 5. Open Questions (non-blocking)

- Re-verify this spec against #904's final approved spec once #904 clears `spec-pending-review`
  — in particular the exact `lt_etf` column names/types and whether `StockUniverse.kind` lands
  as described, since this spec's data-access code is written against the *planned* shape.
- Exact Pydantic response shapes, pagination (if any, for `GET /roster`), and error codes are
  left to the plan/implement phase, per epic §5.
- Whether a separate whole-roster "recompute everything now" endpoint (enqueuing the nightly
  batch task, 202 + `task_id`) is worth adding in this slice or deferred — not required by the
  issue's "done when" criteria.
- Movers list length (defaulted to 5 in §3.5) is a judgment call, not a requirement; adjust
  freely if it reads awkwardly on the page.

## 6. Assumptions (flagged)

- **This spec depends unconditionally on #904.** It assumes #904 lands with, at minimum: an
  `lt_etf` table with `ticker`, `segment`, `country`, `is_active`, `is_benchmark`, and listing-
  currency columns; an `lt_dividend` table (`ticker`, `ex_date`, `cash_amount`, `currency`,
  `source`); `StockUniverse.kind` distinguishing `static` roster-backed universes from
  `screened` ones; `StockAggregate.ticker` widened to `String(20)` (needed for `.TO`-suffixed
  Canadian tickers); and a roster row for SPY with `is_benchmark=true`. If #904's approved spec
  changes any of these names/shapes, this spec is updated before planning starts (see Open
  Questions).
- Assumes the existing cookie-based auth middleware covers the new router with no changes —
  nothing about this slice's endpoints needs new auth scope.
- Assumes `services/trend_pullback_scan.py`'s `_calc_rsi`/`_calc_atr` are usable as a reference
  implementation (not necessarily imported directly, since they're currently private
  module-level functions) rather than needing to be refactored into a shared module as part of
  this slice — refactoring them out is left to the builder's judgment, not required.
- Assumes "latest trading day" for the acceptance criterion means the most recent day the
  nightly aggregate sync has topped up, not necessarily the calendar's most recent weekday (a
  market holiday or a sync delay both legitimately push this back).
