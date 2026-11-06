# LT-1c: 5-Year Backfill, Nightly Top-Up and Data-Health for the Long-Term Universe — Design Spec

**Issue:** #913
**Date:** 2026-11-06
**Status:** Proposed — pending implementation plan

## 1. Overview / Problem Statement

Epic #902 ("Long-term ETF investing") needs a curated ~65-ticker roster of US and Canadian
ETFs with 5 years of daily history (bars, dividends, FX) kept current by the existing nightly
sync. This issue is slice 1c of 5: it owns the backfill, the nightly top-up wiring, and the
data-health check for that roster's data. It does **not** own the roster table, the
`StockUniverse.kind="static"` column, or the data sources themselves (yfinance provider,
`lt_dividend`, `fx_rate_daily`) — those belong to sibling issues #904 (LT-1a) and #912 (LT-1b),
both still `spec-pending-review` with no merged implementation as of this writing. This spec
is deliberately forward-looking: it documents what #913 builds, and what it expects to consume
from #904/#912, so the implementer isn't guessing at an interface that doesn't exist yet.

Bars already have a working nightly top-up path for every other universe
(`sync_universe_aggregates_nightly`) and a working one-time backfill endpoint
(`POST /{universe_id}/sync-aggregates`) — #913's bar-related work is mostly making sure that
path copes with a mixed-data-source universe, not building something new. Dividends and FX are
new concerns with no existing nightly task or backfill trigger; #913 builds both, as thin
wrappers around #912's fetch functions. Data-health has an existing aggregate-only check
(`compute_universe_data_health`); #913 extends it with a per-ticker breakdown so a single
broken yfinance ticker (the "expected failure" the issue names) is visible by ticker, not
drowned in a universe-wide percentage.

## 2. Requirements (from Q&A)

1. #913 is implemented only after #904 and #912 land. It must not stub or duplicate their
   models, migrations, or provider code — see §3.1 "Consumed interfaces" for exactly what it
   expects to exist. If any consumed interface doesn't match this spec when #913 is actually
   implemented, the implementer stops and flags the mismatch (issue comment / commit note)
   rather than inventing a replacement.
2. One-time backfill of 1830 days of daily bars, dividends, and FX for every roster ticker,
   routed by the ticker's data source. Bars reuse the existing
   `POST /{universe_id}/sync-aggregates` endpoint unchanged. Dividends + FX get a new endpoint,
   `POST /{universe_id}/sync-dividends-fx`, which queues a Celery task rather than running
   synchronously (matching `sync-aggregates`'s async, pollable shape) and is re-runnable
   whenever the roster changes.
3. Nightly top-up: two new Celery tasks, `sync_lt_dividends_nightly` and
   `sync_fx_rates_nightly`, each with their own `beat_schedule` entry, scheduled between the
   existing bar sync (01:30 UTC) and the existing health sweep (03:00 UTC) so a fresh dividend/FX
   read happens before health is evaluated the same night.
4. Data-health: `compute_universe_data_health()` gains a per-ticker `stale_tickers` field (new,
   additive, empty by default) so individual stale tickers are nameable, not just a percentage.
   The Long-Term ETFs universe specifically uses a 2-trading-day staleness threshold instead of
   the existing global `quality_staleness_hours` setting; every other universe is unaffected.
5. No changes to the existing aggregate response shape consumed by the Scanner page staleness
   banner, no changes to the existing global `quality_staleness_hours`/`quality_alert_pct`
   defaults, no changes to `sync_universe_aggregates_nightly`'s or
   `check_aggregate_staleness`'s existing behavior for any other universe.
6. Out of scope (per issue): signals, the Long-Term page, the MCP server, portfolio/holdings.
7. Done when: `stock_aggregates` has ~1250 daily rows per roster ticker (fewer for
   short-history ones like IBIT/ETHA); dividend rows exist for income ETFs (TLT, SCHD, XBB.TO,
   ZPR.TO); `fx_rate_daily` has a row per trading day for 5 years; the nightly job runs clean
   against the static universe; data-health shows green (no entries in `stale_tickers`).

## 3. Architecture / Approach

### 3.1 Consumed interfaces (owned by #904 / #912 — not built here)

This spec assumes the following exist by the time #913 is implemented. If any of these differ
from what #904/#912 actually ship, stop and reconcile before writing code against this spec.

| Interface | Owner | Expected shape |
|---|---|---|
| `StockUniverse.kind` | #904 | New column, `"static"` for the Long-Term ETFs universe, `"screened"` default for existing rows. Used to gate the new dividend/FX backfill endpoint to the right universe and to let the health check apply the 2-trading-day override only to this universe. |
| Roster table + seed | #904 | One row per ETF with at least `ticker`, `country`, `data_source` (`massive` \| `yfinance`). `StockUniverseTicker.data_source` (already exists today, `String(50)`, default `"massive"`) is the field the bar sync and the new dividend/FX tasks route on per ticker — #904 populates it from the roster on `/refresh`, #913 only reads it. |
| `backend/app/providers/yfinance_provider.py` | #912 | Implements the base-provider `get_bars` contract for Canadian (`.TO`) tickers. #913's bar backfill/top-up never calls this directly — it goes through the existing `sync_missing_aggregates`/`sync_stock_aggregates` path, which must already route by `data_source`. #913's job is to confirm that routing works end-to-end for a yfinance-sourced ticker, not to build it. |
| `lt_dividend` table | #912 | Columns `ticker`, `ex_date`, `cash_amount`, `currency`, `source`, per epic §4.2. |
| `fx_rate_daily` table | #912 | Columns `pair`, `date`, `rate`, per epic §4.2. |
| Fetch-dividends function | #912 | Expected signature shape: `fetch_dividends(ticker: str, from_date: date, to_date: date) -> list[DividendRow]`, routing to Polygon's `/v3/reference/dividends` for US tickers and the yfinance provider's dividend history for Canadian tickers, returning rows ready to upsert into `lt_dividend`. #913's nightly task and backfill endpoint call this per roster ticker; #913 does not implement the fetch logic itself. |
| Fetch-FX function | #912 | Expected signature shape: `fetch_fx_rates(pair: str, from_date: date, to_date: date) -> list[FxRateRow]`, for `USDCAD`, from the yfinance provider's `CAD=X` with Polygon forex `C:USDCAD` as fallback, returning rows ready to upsert into `fx_rate_daily`. #913's nightly task and backfill endpoint call this once per run (single pair), not per ticker. |

### 3.2 One-time backfill

**Bars.** Unchanged — `POST /{universe_id}/sync-aggregates` with `from_date`/`to_date` spanning
1830 days, `timespan="day"`, `multiplier=1`, `adjusted=true`, run once against the Long-Term
ETFs universe after #904's roster seed and `/refresh` have populated `StockUniverseTicker`.
This already fans out one Celery task per ticker via `universe_orchestrator.sync_aggregates`
and dedupes in-flight syncs through the existing `universe:{id}:sync` Redis key — no changes
needed for #913 to use it, beyond confirming it tolerates the mix of `massive`/`yfinance`
`data_source` values once #904/#912 populate them.

**Dividends + FX.** New endpoint `POST /{universe_id}/sync-dividends-fx` in
`backend/app/routers/universe.py`, alongside `sync_universe_aggregates`:

- Params: optional `from_date`/`to_date` (default to 1830 days back from today / today).
- Validates `universe.kind == "static"` (404/400 otherwise — this backfill mode only makes
  sense for the roster-driven universe; running it against a screened universe with no fixed
  roster and no FX/dividend relevance would be a user error worth rejecting explicitly).
- Queues a single Celery task (new, see §3.3) that loops the universe's active tickers, calls
  #912's fetch-dividends function per ticker and the fetch-FX function once for `USDCAD`, and
  upserts into `lt_dividend`/`fx_rate_daily`. Returns a task id immediately, matching
  `sync-aggregates`'s async/pollable shape (per CLAUDE.md's endpoint-validation convention,
  this is curl-testable: trigger, then poll `AsyncResult(task_id)` or the task's own log line).
- Re-runnable: calling it again (e.g. after the roster changes) re-fetches and upserts; no
  separate "already backfilled" guard is needed since the underlying tables are keyed for
  upsert (per #912's schema) and a re-fetch of already-correct ranges is a no-op in effect.

### 3.3 Nightly top-up

Two new Celery tasks in a new file `backend/app/tasks/long_term.py` (not `sync.py` — these are
long-term-ETF-specific concerns, not generic universe/scanner tasks, matching the epic's `lt_`
naming convention for the domain). Both are thin: they resolve the Long-Term ETFs universe's
active tickers (or the single `USDCAD` pair) and call #912's fetch functions for the window
since the last stored row, the same "top up from last stored point" shape
`sync_universe_aggregates_nightly` already uses for bars.

```python
# backend/app/tasks/long_term.py

@celery_app.task(bind=True, max_retries=0, name="app.tasks.sync_lt_dividends_nightly")
def sync_lt_dividends_nightly(self):
    """Nightly top-up of lt_dividend rows for every active Long-Term ETFs roster ticker."""
    ...

@celery_app.task(bind=True, max_retries=0, name="app.tasks.sync_fx_rates_nightly")
def sync_fx_rates_nightly(self):
    """Nightly top-up of fx_rate_daily rows for the USDCAD pair."""
    ...
```

Both follow `sync_universe_aggregates_nightly`'s structure: resolve the Long-Term ETFs universe
by `kind == "static"`, loop tickers (dividends) or the single pair (FX), log success/failure
per item without aborting the whole run on one failure, increment
`celery_tasks_total`/`celery_task_duration_seconds` like every other task in `sync.py`/
`quality.py`. Both must be imported into `backend/app/tasks/__init__.py`'s explicit import
list (the package the Celery app's `include=["app.tasks"]` config loads) for Celery to
discover them — adding the file alone is not sufficient.

Beat schedule additions in `backend/app/core/celery_app.py`, placed after
`sync-universe-aggregates-nightly` (01:30 UTC Tue–Sat) and before
`check-aggregate-staleness-nightly` (03:00 UTC weekdays) so dividend/FX data is fresh before
that night's health sweep runs:

```python
"sync-lt-dividends-nightly": {
    "task": "app.tasks.sync_lt_dividends_nightly",
    "schedule": crontab(minute="0", hour="2", day_of_week="2-6"),
},
"sync-fx-rates-nightly": {
    "task": "app.tasks.sync_fx_rates_nightly",
    "schedule": crontab(minute="15", hour="2", day_of_week="2-6"),
},
```

(`day_of_week="2-6"` matches the existing bar-sync entry's Tue–Sat cadence, which covers each
Mon–Fri trading session the night after it closes.)

### 3.4 Data-health: per-ticker breakdown + 2-trading-day threshold

Extend `compute_universe_data_health()` in `backend/app/tasks/quality.py` with a new, additive
`stale_tickers: list[{ticker, last_bar_date}]` field (empty list when nothing is stale, for
every universe — not just the Long-Term one). The existing nine keys
(`ticker_count`/`stale_count`/`gapped_count`/`stale_pct`/`gapped_pct`/`worst_staleness_hours`/
`worst_gap_days`/`degraded`/`grade`) are unchanged in meaning and value, so the Scanner page's
staleness banner and `check_aggregate_staleness`'s Prometheus gauges need no changes.

Threshold override: a module-level constant,

```python
_LONG_TERM_STALE_TRADING_DAYS = 2
```

applied only when `universe.kind == "static"` (i.e., only the Long-Term ETFs universe today).
For that universe, a ticker's `MAX(timestamp)` day bar is stale when it is older than 2
trading days — trading days computed the same way the function's existing day-hole detection
already does, by walking back from today skipping weekends and `MarketHoliday` rows where
`event_type == "full_close"`. Every other universe keeps using the existing global
`quality_staleness_hours` (`_load_quality_thresholds`, default 48h) path unchanged. This is a
deliberately narrow, hardcoded special case rather than a new per-universe config column — a
second universe needing its own override is not anticipated by this issue, and adding config
surface for a one-off would be premature.

Rationale for per-ticker visibility: the existing `quality_alert_pct` default (20%) means a
single broken ticker in a roster of ~65 (≈1.5%) would never flip `degraded` under the
aggregate check alone — the issue's "flags any roster ticker" requirement needs the individual
name, not just the percentage, to actually be useful for catching the yfinance-breakage
scenario the issue calls out.

No changes to `check_aggregate_staleness`'s nightly sweep behavior beyond it incidentally
picking up the new `stale_tickers` field in its `compute_universe_data_health()` call — it
already logs a `degraded` summary per universe and does not need to separately enumerate
`stale_tickers` in its log line for this issue's scope (the field exists for the
`GET /{universe_id}/data-health` consumer, i.e. a future Long-Term page or manual check, not
for the nightly sweep's own logging).

## 4. Alternatives Considered

- **Combine dividend + FX top-up into a single Celery task.** Rejected: the existing codebase
  convention (`sync_universe_aggregates_nightly` vs. `check_aggregate_staleness` vs.
  `sync_stock_splits`) is one task per concern, which keeps failures isolated (a dividend-fetch
  bug shouldn't block the FX top-up) and keeps each task's Prometheus duration/status metric
  meaningful on its own.
- **Make the 2-trading-day staleness threshold a new per-universe `SystemConfig` setting**
  instead of a hardcoded constant. Rejected for this slice: there is exactly one universe that
  needs a non-default threshold today; a config column for a single consumer is speculative
  surface this issue doesn't need. Revisit if a second universe needs its own override.
- **One-off management/CLI script for the dividend+FX backfill** instead of a REST endpoint.
  Rejected: the endpoint is re-runnable (useful whenever the roster changes), consistent with
  `sync-aggregates`'s existing shape, and directly curl-testable per CLAUDE.md's validation
  convention — a CLI script would need a separate, undocumented invocation path and wouldn't be
  pollable the same way.
- **Build #913 with stubs for the roster/`kind` column/yfinance provider** so it doesn't block
  on #904/#912. Rejected: §4.2/§4.9 of the epic design assign those pieces to #904/#912
  explicitly; stubbing them in #913 risks colliding with those issues' own migrations and
  models when they land, and the issue is sized S on the assumption its dependencies exist.

## 5. Open Questions (non-blocking)

- Exact column types/upsert keys for `lt_dividend`/`fx_rate_daily` are #912's to finalize; this
  spec's fetch-function signatures (§3.1) are a reasonable expectation, not a contract #912 is
  bound to verbatim. Reconcile at implementation time per Requirement 1.
- Whether the dividend/FX backfill task should report partial-failure detail (e.g. which
  tickers' dividend fetch failed) back through the task result for the caller to see, beyond
  what's logged to Seq — left to the builder, following the project's existing task-logging
  conventions.

## 6. Assumptions (flagged)

- #904 and #912 land before #913 is implemented, and expose the interfaces listed in §3.1.
- The Long-Term ETFs universe is identifiable at the time #913 is implemented via
  `StockUniverse.kind == "static"` (per #904) and is the only universe with that `kind` value —
  if #904 ships a different discriminator, the health-check and backfill-endpoint gating in
  §3.2/§3.4 need the equivalent update.
- "Two trading days" means NYSE trading days (via the existing `MarketHoliday` `full_close`
  rows already used for day-hole detection), not a separate Canadian/TSX holiday calendar — US
  and Canadian market holidays mostly but not entirely coincide; this is a deliberate
  simplification consistent with the rest of the codebase's single holiday calendar.
