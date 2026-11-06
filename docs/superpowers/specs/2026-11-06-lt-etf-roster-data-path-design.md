# LT-1: ETF Roster, Static Universe, Canadian Bars, Dividends, FX (Data Path) — Design Spec

**Issue:** #904
**Date:** 2026-11-06
**Status:** Proposed — pending implementation plan

## 1. Overview / Problem Statement

This is rollout slice 1 of 5 for the Long-Term ETF Investing epic (#902; full
design: `docs/superpowers/specs/2026-11-06-long-term-etf-investing-design.md`,
PR #903). It builds only the data path: a curated roster of ~65 US and
Canadian ETFs with 5 years of daily history, kept current by a nightly sync.
Nothing in this slice is user-visible — no new page, REST surface, or MCP
tool. Signals, the Long-Term page, the MCP server, and portfolio/proposal
models are later slices and depend on this one.

Three gaps block the roster from having usable, current data:

1. **Canadian tickers have no data source.** Polygon doesn't serve TSX, and
   the IBKR account's Canadian market-data entitlement is unknown (decided
   with Frank: don't depend on it). A new `yfinance` provider is needed, and
   — more importantly — nothing in the existing sync path reads
   `MonitoredStock.data_source` / `StockUniverseTicker.data_source` today
   (both columns exist but are dead weight): every stock ticker in every
   universe is unconditionally routed to Massive (Polygon). Adding a
   yfinance provider alone does nothing until the sync path is taught to
   route per ticker.
2. **Universes have no concept of a fixed roster.** `StockUniverse.kind`
   doesn't exist; `/refresh` always runs the screener
   (`DiscoveryService.run_screen()`), wiping and recreating members from
   screener criteria. A static, roster-backed universe needs a different
   `/refresh` behavior.
3. **Dividends and FX don't exist in this codebase at all.** No table, no
   provider method, no task. Both need a one-time 5-year backfill and a
   nightly top-up, same as bars, but bars already have a backfill surface
   (`POST /{universe_id}/sync-aggregates`) and dividends/FX don't.

## 2. Requirements (from Q&A)

1. `lt_etf` roster model, Alembic migration, and a seed of the ~65 ETFs from
   the epic design's §4.1 table (ticker, name, segment, country, listing
   currency, exchange, data_source, inception_date, is_active, is_benchmark,
   tags).
2. `StockUniverse.kind` column (`screened` default / `static`). One universe,
   `Long-Term ETFs`, created with `kind="static"` from the roster. Its
   `/refresh` rebuilds `MonitoredStock` + `StockUniverseTicker` from active
   roster rows instead of running the screener, copying each roster row's
   `data_source` onto the created rows.
3. The sync path (`sync_missing_aggregates`, `sync_aggregates`,
   `sync_stock_aggregates`) must route each stock ticker's bar fetch through
   the provider named by its `MonitoredStock.data_source`, not unconditionally
   through Massive — this is the mechanism that makes "new yfinance provider"
   actually take effect, for both nightly top-up and one-time backfill.
4. `StockAggregate.ticker` widened `String(10)` → `String(20)` (`.TO` suffixes
   and longer symbols need the room).
5. New `backend/app/providers/yfinance_provider.py` implementing `get_bars`
   (`auto_adjust=False`, raw closes) and a new, non-abstract
   `get_dividends(symbol, from_date, to_date)` provider method, both wrapped
   in a new `YFINANCE_BREAKER` circuit breaker. Package pinned in
   `requirements.txt`.
6. `lt_dividend` table (ticker, ex_date, cash_amount, currency, source) filled
   by a new nightly task: Polygon `/v3/reference/dividends` for US roster
   rows, the new yfinance provider's dividend method for CA rows, routed by
   each `lt_etf` row's `data_source`.
7. `fx_rate_daily` table (pair, date, rate) filled by a new nightly task:
   `USDCAD` from yfinance `CAD=X` primary, Polygon forex `C:USDCAD` fallback
   on any failure.
8. Both new nightly tasks self-backfill 1830 days on first run (no stored
   rows yet) and top up incrementally thereafter — no separate one-time
   backfill endpoint or script, and no manual rollout step.
9. A new per-ticker, trading-day-aware staleness check for the roster,
   flagging any active roster ticker whose latest bar is more than 2 trading
   days old, surfaced via log warning + a new Prometheus gauge (no REST/DB
   surface yet — nothing consumes one in this slice).
10. Acceptance (from the issue's "Done when"): ~1250 daily `stock_aggregates`
    rows per roster ticker (fewer for short-history names like IBIT/ETHA);
    dividend rows exist for TLT/SCHD/XBB.TO/ZPR.TO; `fx_rate_daily` has a row
    per trading day for 5 years; the nightly jobs run clean against the
    static universe.

## 3. Architecture / Approach

### 3.1 `lt_etf` roster model and seed

New model `backend/app/models/lt_etf.py`, table `lt_etf`:

| Column | Type | Notes |
|---|---|---|
| `id` | `Integer`, PK | |
| `ticker` | `String(20)`, unique, indexed | app-wide form, `.TO` suffix for TSX |
| `name` | `String(255)` | |
| `segment` | `String(50)`, indexed | grouping unit — see table below |
| `country` | `String(2)` | `US` or `CA` |
| `currency` | `String(3)` | listing currency, e.g. `USD`/`CAD` |
| `exchange` | `String(20)` | e.g. `ARCA`, `TSX` |
| `data_source` | `String(50)`, default `"massive"` | `massive` or `yfinance` — same vocabulary as `MonitoredStock.data_source` |
| `inception_date` | `Date`, nullable | |
| `is_active` | `Boolean`, default `True`, indexed | |
| `is_benchmark` | `Boolean`, default `False` | SPY only, for now |
| `tags` | `JSON`, default `list` | free-form sub-segment labels, e.g. `["energy"]` — same shape as `NewsArticle.tickers`; cross-country grouping (e.g. "energy" = XLE + XEG.TO) is a later-slice concern, this slice just stores the column |
| `created_at` / `updated_at` | `DateTime` | standard `utc_now` pattern |

Seeded by a data migration (idempotent `INSERT ... WHERE NOT EXISTS`, following
the `f7e8d9c0b1a2_seed_trend_pullback_scanner_config.py` pattern: pre-check by
a distinguishing value, bulk `INSERT` via `sa.text()`, matching `DELETE` in
`downgrade()`) with the ~65 tickers from the epic design's §4.1 table:

| Segment | US | Canada |
|---|---|---|
| Broad market | SPY (benchmark), QQQ, DIA, IWM, VTI | XIU.TO, XIC.TO, VFV.TO |
| Style & size | VTV, VUG, VBR, MTUM, QUAL, SCHD | — |
| Sectors | XLK, XLF, XLE, XLV, XLI, XLY, XLP, XLU, XLB, XLRE, XLC | XEG.TO, XFN.TO, ZEB.TO, XIT.TO, XMA.TO, XGD.TO, ZUT.TO, XRE.TO, ZPR.TO |
| Bonds & rates | BND, TLT, IEF, SHY, LQD, HYG, TIP | XBB.TO, XSB.TO, ZFL.TO |
| Commodities & miners | GLD, SLV, USO, DBC, GDX | — |
| International | VEA, VWO, EWJ, EWZ | XEF.TO, XEC.TO |
| Crypto | IBIT, ETHA | BTCC.TO, ETHX.TO |
| Tech themes | SMH, BOTZ, AIQ, CIBR, CLOU, ARKK | — |

All Canadian (`.TO`) rows get `data_source="yfinance"`, `country="CA"`,
`currency="CAD"`, `exchange="TSX"`; all US rows get `data_source="massive"`,
`country="US"`, `currency="USD"`, `exchange` per actual primary listing (ARCA
for most ETFs). SPY gets `is_benchmark=True`. Roster editing (add/deactivate/
re-segment via page or MCP) is out of scope — this slice only seeds and reads.

### 3.2 `StockUniverse.kind` and static `/refresh`

Add `kind = Column(String(20), nullable=False, default="screened")` to
`StockUniverse`. Migration backfills existing rows to `"screened"` (matches
the model default, so existing behavior is unchanged).

In `backend/app/services/universe_orchestrator.py`, add
`refresh_from_roster(universe_id: int, db: Session) -> dict`, structurally
mirroring `discover_and_refresh()`: wipe `MonitoredStock` +
`StockUniverseTicker` for the universe, then bulk-insert one row per active
`lt_etf` (`is_active=True`) into each, copying `ticker`, `data_source`
(critical — this is what makes §3.3's per-ticker provider routing work),
`asset_class="stocks"`, and `company_name=lt_etf.name`. Recompute cached stats
via `UniverseStatsService.compute()` exactly as `discover_and_refresh()` does.

`backend/app/routers/universe.py`'s `POST /{universe_id}/refresh` branches on
`universe.kind`: `"static"` → `refresh_from_roster`, `"screened"` (default) →
existing `discover_and_refresh`.

One universe row, `name="Long-Term ETFs"`, `kind="static"`, `criteria={}` (the
column is `NOT NULL`; static universes have no screener criteria — an empty
object, not `null`, keeps the column's existing NOT NULL contract and reads
unambiguously as "no criteria" to anything that later inspects it), is
created by the same migration that seeds `lt_etf` (or an immediately-following
one), with `is_active=True` so it participates in `sync_universe_aggregates_nightly`'s
"all active universes" sweep automatically — no new nightly task is needed
for bar top-up, confirmed by A1/A2.

### 3.3 Per-ticker provider routing for bars (closes gap #1)

Per **A1**: register the new yfinance provider as `"yfinance"` in
`DataProviderFactory` (`backend/app/providers/__init__.py`), alongside
`"massive"` and `"ibkr"`.

`backend/app/tasks/sync.py::sync_stock_aggregates` gains
`provider: str = "massive"`, passed straight through to
`StockDataService.get_aggregates(..., provider=provider)` (which already
accepts this kwarg — IBKR already uses it for futures). The default preserves
every existing call site unchanged.

`backend/app/services/universe_orchestrator.py::sync_missing_aggregates()`
and `::sync_aggregates()` — in the stocks (non-futures) branch of both
functions — build a `ticker -> data_source` map from the `MonitoredStock`
rows already queried (`{s.ticker: s.data_source for s in stocks if s.asset_class != "futures"}`)
and pass `provider=data_source_map.get(ticker, "massive")` into each
`sync_stock_aggregates.delay(...)` call, instead of the current unconditional
call with no `provider` kwarg. This is the same shape as the existing
`asset_class` branch for futures vs. stocks one level up — a second branch
inside the stocks half, keyed on `data_source` instead.

This single change makes **both** paths route correctly, since both already
funnel through `sync_stock_aggregates`:
- **Nightly top-up**: `sync_universe_aggregates_nightly` → `sync_missing_aggregates`
  (unchanged caller, now provider-aware).
- **One-time backfill**: `POST /{universe_id}/sync-aggregates` → `sync_aggregates`
  (unchanged caller, now provider-aware) — this is the existing endpoint,
  already capped at 1830 days per request, so a manual
  `POST /{long_term_universe_id}/sync-aggregates?from_date=...&to_date=...`
  (1830 days back) is how the 5-year bars backfill for roster tickers is
  actually triggered (bars already had a backfill surface; only dividends and
  FX needed a new one per §3.5).

Per **A1**'s stated risk: if only one of the two call sites got this branch,
`.TO` tickers would silently fetch empty from Massive on the other path and
only surface later as a stale-bar data-health flag (§3.6) instead of an
obvious failure — hence both get it in the same change.

### 3.4 `yfinance` provider

New `backend/app/providers/yfinance_provider.py`, `YFinanceDataProvider`,
implementing `BaseDataProvider`:

- `name` → `"yfinance"`; `supported_asset_classes` → `["stocks"]`.
- `is_available()` → `True, "Ready"` (no API key; yfinance scrapes Yahoo
  directly — nothing to validate at startup beyond the import succeeding).
- `get_bars(symbol, timespan, multiplier, from_date, to_date, **kwargs)`:
  only `timespan="day"`, `multiplier=1` is exercised by this feature (daily
  resolution only, per the epic design). Calls `yfinance.Ticker(symbol).history(start=from_date, end=to_date, auto_adjust=False)`
  and maps the returned frame into the standard `get_bars` dict shape
  (raw/unadjusted OHLCV — `auto_adjust=False` is required so stored closes
  are raw, consistent with how Massive stores bars). The app ticker form
  (`XIU.TO`) passes straight through — Yahoo uses the identical suffix, no
  translation needed.
- `get_dividends(symbol, from_date, to_date)`: new, non-abstract method added
  to `BaseDataProvider` (default implementation raises `NotImplementedError`,
  so Massive and IBKR don't need a no-op override — only providers that
  support dividends implement it). Calls
  `yfinance.Ticker(symbol).dividends`, filters to the date range, returns
  `[{"ex_date": ..., "cash_amount": ..., "currency": ...}, ...]`.
- `get_snapshots`, `get_ticker_details`: not used by this feature; implement
  as empty-return stubs consistent with `BaseDataProvider`'s documented
  contract for providers that don't support an operation.

Both `get_bars` and `get_dividends` are wrapped in a new
`YFINANCE_BREAKER` (`backend/app/core/circuit_breakers.py`, same shape as
`POLYGON_BREAKER`: `pybreaker.CircuitBreaker` built from new `YFINANCE_CB_FAIL_MAX`
/ `YFINANCE_CB_RESET_TIMEOUT` settings, with a `HealthRecordingListener("yfinance")`).
This satisfies the issue's "wrap in the existing circuit-breaker pattern" and
gives yfinance's known fragility (unofficial client, breaks on Yahoo-side
changes) the same graceful-degradation behavior Polygon already has.

`yfinance` is pinned in `backend/app/requirements.txt` (exact version left to
the builder — follow the existing pin style, e.g. `yfinance==<latest-stable-at-implementation-time>`).

### 3.5 Dividends and FX (closes gap #3)

Per **A3**, both are self-backfilling nightly tasks — no new REST endpoint,
no one-off script, no manual rollout step:

**`backend/app/tasks/sync.py::sync_lt_dividends_nightly`** (new task):
iterates active `lt_etf` rows directly (dividends are a roster concept, not a
universe-membership concept — doesn't go through `MonitoredStock`). For each
row, routes via `DataProviderFactory.get(row.data_source or "massive")`:
- Massive gets a new `get_dividends` implementation calling Polygon
  `/v3/reference/dividends?ticker=...`, wrapped in `POLYGON_BREAKER.call(...)`
  the same way `get_bars`/`_get_bars_impl` is split (so dividend calls count
  toward the shared Polygon breaker and health listener) — this endpoint is
  reference data, separate from the existing ad-hoc `sync_stock_splits`
  task's unwrapped `httpx` call to `/v3/reference/splits`; dividends go
  through the provider/breaker path instead of a second bespoke `httpx` call.
- yfinance uses the `get_dividends` from §3.4.

Date range: start from the day after the latest stored `lt_dividend.ex_date`
for that ticker, or `today - 1830 days` if no rows exist yet (so the first
run is the backfill). Additionally re-fetch a trailing ~30-day window every
run regardless of the last stored date, since Polygon publishes/corrects
dividend records around the ex-date and a strict "resume from last row" start
would miss corrections. Upsert on `(ticker, ex_date)`.

**`backend/app/tasks/sync.py::sync_fx_rates_nightly`** (new task): one pair,
`USDCAD`, for now. Primary: yfinance `CAD=X` via a provider method wrapped in
`YFINANCE_BREAKER`. Fallback (any exception from the primary, including a
`ProviderError` from an open breaker, or an empty result for the requested
range): `DataProviderFactory.get("massive").get_bars("C:USDCAD", timespan="day", multiplier=1, from_date=..., to_date=...)`
— already wrapped in `POLYGON_BREAKER`; Polygon's aggs endpoint accepts forex
tickers directly, so no new Massive code is needed for the fallback leg
itself. Per **A3**, this is a plain try/except, not a third
`DataProviderFactory` entry — FX is one fixed pair with a primary/fallback,
not a routable "source" the way bars/dividends are. Same date-range logic as
dividends (resume from last stored `fx_rate_daily.date` for `pair="USDCAD"`,
or 1830 days back if empty). Upsert on `(pair, date)`. Log which source
supplied each run's data.

Both tasks are added to `celery_app.conf.beat_schedule`
(`backend/app/core/celery_app.py`) in a new Tue–Sat slot around 01:45 UTC —
after the existing 01:30 UTC `sync-universe-aggregates-nightly` entry, before
the 03:00 UTC `check-aggregate-staleness-nightly` entry — as two separate
beat entries (not folded into `sync_universe_aggregates_nightly`, per **A3**:
that task is per-universe and only queues work, FX has no ticker/universe
membership, and a dividend/FX failure shouldn't pollute bars-sync metrics).

New models:
- `backend/app/models/lt_dividend.py`: `id`, `ticker` (`String(20)`,
  indexed), `ex_date` (`Date`, indexed), `cash_amount` (`Numeric`),
  `currency` (`String(3)`), `source` (`String(50)` — `"massive"` or
  `"yfinance"`), `created_at`. Unique constraint on `(ticker, ex_date)`.
- `backend/app/models/fx_rate_daily.py`: `id`, `pair` (`String(10)`,
  indexed, e.g. `"USDCAD"`), `date` (`Date`, indexed), `rate` (`Numeric`),
  `source` (`String(50)`), `created_at`. Unique constraint on `(pair, date)`.

Both registered in `backend/app/models/__init__.py` per CLAUDE.md's "New
Models" rule, with a migration generated via
`alembic revision --autogenerate` (table creation only — no seed needed,
these fill from the nightly tasks).

### 3.6 Per-ticker roster staleness check (closes gap in existing data-health coverage)

Per **A2**: the existing `check_aggregate_staleness` / `compute_universe_data_health()`
sweep (`backend/app/tasks/quality.py`) is universe-aggregate and
percentage-based, with global `SystemConfig`-driven calendar-hour thresholds
(`quality_staleness_hours`, default 48; `quality_alert_pct`, default 20) — it
flags a *universe* degraded only once a meaningful fraction of its tickers
are stale, and "stale" there means calendar hours, not trading days. That
mechanism is left untouched (it still runs against `Long-Term ETFs` like any
other active universe, satisfying the "nightly job runs clean" acceptance
criterion at the universe level) because changing its meaning would also
change behavior for every existing screened universe.

New function `find_stale_roster_tickers(db: Session, max_trading_days: int = 2) -> list[dict]`
(co-located with the roster/data-path service code), scoped to active
`lt_etf` rows: for each, compare its latest `stock_aggregates` day-bar date
(`timespan="day", multiplier=1`) against "the most recent trading day minus
`max_trading_days`", using the weekday + `MarketHoliday`-aware helpers already
in `backend/app/services/quality_helpers.py` (the same ones
`compute_universe_data_health`'s gap detector uses). A ticker with zero
stored bars counts as stale. Returns the list of violations (ticker,
data_source, last bar date) so a later slice can expose it via REST/MCP
without rework — this slice has no consumer for the return value beyond
logging and a metric.

Called from inside the existing `check_aggregate_staleness` task (03:00 UTC
weekdays — after the 01:30 UTC nightly sync has had time to run and land
bars), in its own `try/except` block so a failure here can't break the
existing universe sweep and vice versa — *not* appended directly to
`sync_universe_aggregates_nightly`, since that task only queues per-ticker
Celery sync tasks and returns before they finish, which would race the
still-running syncs and produce false positives.

Each violation gets one `logger.warning` (ticker, data_source, last bar date)
and sets a new Prometheus gauge, `markethawk_roster_ticker_stale_trading_days{ticker}`
(`backend/app/core/metrics.py`, same style as the existing
`aggregate_staleness_hours{universe_id}` gauge; ~65 labels is a negligible
cardinality addition).

**Accepted gap:** `MarketHoliday` is US-only (`exchange="NYSE"` filter in
`compute_universe_data_health`); a TSX-only holiday (Victoria Day, Canada
Day) will count as a missed trading day for `.TO` tickers in this check too.
With a 2-trading-day threshold, a single such holiday doesn't by itself push
a healthy ticker over the line, so this is accepted for this slice per A2 and
noted in the code; a TSX calendar is a later improvement if false flags
actually appear in practice.

### 3.7 `StockAggregate.ticker` widening

Single-column migration, `String(10)` → `String(20)`, following the
`fa2957d31876_expand_column_lengths.py` precedent (`op.alter_column` with
`existing_type`/`type_`). `stock_aggregates` has no dependent view (unlike
`monitored_stocks` in that precedent), so no view drop/recreate is needed
here.

## 4. Alternatives Considered

- **Suffix-sniffing (`.TO` → yfinance) instead of reading `data_source`.**
  Rejected — the epic design explicitly decided provider selection happens
  through the roster row's `data_source` column, not string matching on the
  ticker, so a future non-`.TO` yfinance-sourced row (or a `.TO` row that
  later needs to move providers) doesn't require a code change. `data_source`
  also already exists on `MonitoredStock`/`StockUniverseTicker` precisely for
  this purpose; suffix-sniffing would be a second, inconsistent routing
  mechanism living alongside a dead column.
- **A dedicated Celery task for yfinance-sourced bars instead of extending
  `sync_stock_aggregates`.** Rejected per A1 — would duplicate the
  fetch/delete/insert logic already in `sync_stock_aggregates` for no
  behavioral gain, since the only difference is which provider answers
  `get_bars`, which `StockDataService.get_aggregates`'s existing `provider`
  kwarg already parameterizes.
- **Extending `compute_universe_data_health()` for `kind="static"` universes**
  instead of a separate per-ticker check. Rejected per A2 — would change the
  return shape/meaning of a function also used by every screened universe's
  staleness banner, and conflate two different thresholds (global
  percentage/hours vs. this feature's fixed per-ticker/trading-days rule).
- **A new REST endpoint for one-time dividend/FX backfill**, mirroring
  `POST /{universe_id}/sync-aggregates`. Rejected per A3 — nothing in this
  slice calls such an endpoint (no page, no MCP tool yet), and self-filling
  nightly tasks remove the need for any manual rollout step entirely, which a
  dedicated endpoint wouldn't.
- **A third `DataProviderFactory` entry for Polygon-forex-as-FX-fallback.**
  Rejected per A3 — FX fallback is a fixed primary/fallback pair, not a
  routable per-ticker "source"; the existing Massive provider's `get_bars`
  already serves Polygon forex tickers (`C:USDCAD`) with no new code, so a
  factory entry would add structure without adding routing value.

## 5. Open Questions (non-blocking)

- Exact `yfinance` version to pin, and its retry/batching policy within the
  provider (e.g. whether to call `Ticker.history()` per symbol or
  `yf.download()` for a batch) — left to the builder, consistent with the
  epic design's "Left to the builder" section.
- Whether Polygon's `/v3/reference/dividends` response needs pagination
  handling for ETFs with a long dividend history within the 1830-day window
  — left to the builder to confirm against the live API during
  implementation.
- Exact Prometheus metric registration details (label cardinality guard, if
  any) for `markethawk_roster_ticker_stale_trading_days` — follow whatever
  pattern `aggregate_staleness_hours` uses today.

## 6. Assumptions (flagged)

- The epic design doc (PR #903, branch `spec/long-term-etf-investing`) is
  treated as approved-in-substance for the decisions it states outright
  (roster-is-source-of-truth, daily-only resolution, `data_source`-based
  routing, 1830-day backfill window, total-return deferred to slice 2); this
  spec only resolves the *implementation* gaps the issue's scope left open,
  per the Q&A above, and does not re-litigate those epic-level decisions.
  Should PR #903 change materially before merge, this spec may need a
  revisit.
- `fa2957d31876_expand_column_lengths.py` found no dependent view on
  `stock_aggregates`; this is assumed still true (no view has been added
  since) and should be a quick confirmation at implementation time rather
  than a blocking question.
- The reporting-currency conversion that will eventually *consume*
  `fx_rate_daily`, and the total-return adjustment that will eventually
  *consume* `lt_dividend`, are both out of scope for this slice (they belong
  to later slices per the epic's rollout order) — this slice is responsible
  only for populating both tables correctly and keeping them current.
