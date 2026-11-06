# LT-1b: yfinance Provider (Canadian Bars), lt_dividend, fx_rate_daily — Design Spec

**Issue:** #912
**Date:** 2026-11-06
**Status:** Proposed — pending implementation plan

## 1. Overview / Problem Statement

This is slice 1b of the Long-Term ETF Investing epic (#902). The roster slice (#904 /
LT-1a — `lt_etf` model, static `StockUniverse` kind, `MonitoredStock`/`StockUniverseTicker`
ticker widening) is still `spec-pending-review` and unimplemented, but the epic's rollout is
serial, so by the time this slice is implemented LT-1a's roster table and its
`data_source` population on `MonitoredStock`/`StockUniverseTicker` should already exist.

Today, MarketHawk has no way to fetch bars for Canadian (`.TO`) tickers: Polygon does not
cover the TSX, and the IBKR provider's Canadian market-data entitlement is unknown and
explicitly not depended on (epic §4.2). There is also no dividend data anywhere in the system
(needed later, in LT-2, to build total-return series) and no FX handling at all (needed to
convert CAD-denominated ETFs into a common reporting currency).

This slice closes the three data-fetching gaps the rest of the epic depends on:

1. A new `yfinance`-backed provider that can serve daily bars for `.TO` tickers through the
   existing provider abstraction, and the existing bar-sync plumbing wired to actually route to
   it based on a ticker's `data_source`.
2. A `lt_dividend` table and a fetch task covering both US (Polygon) and Canadian (yfinance)
   tickers.
3. An `fx_rate_daily` table and a fetch task for `USDCAD` (yfinance primary, Polygon fallback).

Backfill, nightly-beat scheduling of the new tasks, and data-health staleness checks are
explicitly out of scope (LT-1c, per the issue and epic §4.9).

## 2. Requirements (from Q&A)

1. `backend/app/providers/yfinance_provider.py`: new `YFinanceDataProvider(BaseDataProvider)`.
   `get_bars()` requests `auto_adjust=False` (raw closes); the app ticker (e.g. `XIU.TO`) is
   passed straight through to Yahoo. Calls are wrapped in a new circuit breaker, matching the
   Massive/IBKR pattern.
2. The existing bar-sync path must actually route Canadian tickers to the new provider once
   LT-1a sets `data_source="yfinance"` on their roster/`MonitoredStock` rows — this slice wires
   that routing through, it does not just prove `get_bars` works in isolation.
3. `fetch_dividends` and `fetch_fx_rate` are explicit-input Celery tasks (ticker list / pair +
   date range), independent of the `lt_etf` roster table, so this slice has no runtime
   dependency on LT-1a's data being populated — only on its schema (`data_source` values)
   existing by the time a caller is wired up in a later slice.
4. `lt_dividend` (ticker, ex_date, cash_amount, currency, source) and `fx_rate_daily` (pair,
   date, rate) tables, each with an Alembic migration, both upserting on their natural key.
5. The new Polygon dividends call (`/v3/reference/dividends`) is a new breaker-wrapped method
   on `MassiveDataProvider`, not a raw unbreakered `httpx` call — consistent with how
   `MassiveDataProvider.get_ticker_details()` already calls a Polygon reference endpoint
   through `POLYGON_BREAKER`.
6. yfinance is pinned to an exact version (`==1.8.0`, latest stable as of this spec) in
   `backend/requirements.txt`.
7. Unit tests mock at the vendor-client boundary (`yfinance.Ticker`, `polygon.RESTClient`), not
   over HTTP, matching `backend/tests/providers/test_ibkr_provider.py`'s pattern. No live
   network calls in tests.
8. "Done when" (verbatim from the issue): `get_bars("XIU.TO", ...)` returns daily bars through
   the provider abstraction; fetching dividends for TLT and XBB.TO, and FX for a one-month
   range, each produce rows; unit tests cover all of the above with the network mocked.

## 3. Architecture / Approach

### 3.1 `YFinanceDataProvider`

New file `backend/app/providers/yfinance_provider.py`, following `massive.py`'s shape:

```python
class YFinanceDataProvider(BaseDataProvider):
    name = "yfinance"
    supported_asset_classes = ["stocks", "forex"]

    def is_available(self) -> tuple[bool, str]:
        return True, "Ready"  # no API key; always "available" unless the breaker is open

    def get_bars(self, symbol, timespan, multiplier, from_date, to_date, **kwargs):
        try:
            return YFINANCE_BREAKER.call(self._get_bars_impl, symbol, timespan, multiplier, from_date, to_date)
        except pybreaker.CircuitBreakerError as e:
            raise ProviderError("yfinance circuit breaker open — provider temporarily unavailable",
                                 provider="yfinance", endpoint="get_bars", is_retryable=False) from e

    def get_dividends(self, ticker, from_date, to_date):
        ...  # same breaker-wrapped shape, via yf.Ticker(ticker).dividends

    def get_snapshots(self, symbols=None): return []
    def get_ticker_details(self, symbol): return {}
```

- `_get_bars_impl` calls `yfinance.Ticker(symbol).history(start=from_date, end=to_date,
  interval="1d", auto_adjust=False)` for `timespan="day", multiplier=1` (the only combination
  this slice needs — daily resolution is the epic's only resolution, §4.2). Map the returned
  `pandas.DataFrame` rows to the standard bar dict shape (`timestamp`, `open`, `high`, `low`,
  `close`, `volume`, `vwap: None`, `transactions: None` — yfinance doesn't provide vwap/trade
  count). `timestamp` must be converted to a UTC-aware `datetime`, matching every other
  provider's contract.
- An empty/missing-ticker response from yfinance returns `[]` (not an exception), mirroring
  `massive.py`'s "no data" handling.
- Any exception from the `yfinance` call is caught and re-raised as `ProviderError(...,
  provider="yfinance", is_retryable=True)`, counting toward the breaker — same shape as
  `massive.py`'s `_get_bars_impl` exception handling.
- `get_dividends(ticker, from_date, to_date)` uses `yf.Ticker(ticker).dividends`, filtered to
  the date range, converted to `{ "ex_date": date, "cash_amount": float, "currency": ... }`
  rows. yfinance does not reliably expose a per-ticker listing currency on the dividends
  series; derive `currency` the same way the roster will (US tickers → `USD`, `.TO` tickers →
  `CAD`) rather than trusting a field that may not exist — call this out for the implementer to
  confirm against a live yfinance response during implementation (§5).
- Register in `backend/app/providers/__init__.py`:
  `DataProviderFactory.register(YFinanceDataProvider())` alongside the two existing providers.

### 3.2 `BaseDataProvider.get_dividends()`

Add a new method to `backend/app/providers/base.py`:

```python
def get_dividends(self, ticker: str, from_date: str, to_date: str) -> List[Dict[str, Any]]:
    """
    Fetch dividend history for a ticker. Returns a list of dicts:
        { "ex_date": date, "cash_amount": float, "currency": str }
    Providers that don't support this raise NotImplementedError.
    """
    raise NotImplementedError(f"{self.name} does not support get_dividends()")
```

This is a concrete (non-`@abstractmethod`) method with a default implementation, not part of
the abstract contract — so `IBKRDataProvider` does not need a stub override. `MassiveDataProvider`
and `YFinanceDataProvider` both override it.

### 3.3 `MassiveDataProvider.get_dividends()`

New method in `backend/app/providers/massive.py`, mirroring `get_ticker_details()`'s shape
(breaker-wrapped, Polygon reference endpoint):

```python
def get_dividends(self, ticker: str, from_date: str, to_date: str) -> List[Dict[str, Any]]:
    if not self._client:
        return []
    try:
        return POLYGON_BREAKER.call(self._get_dividends_impl, ticker, from_date, to_date)
    except pybreaker.CircuitBreakerError as e:
        raise ProviderError("Polygon circuit breaker open — provider temporarily unavailable",
                             provider="massive", endpoint="dividends", is_retryable=False) from e
```

`_get_dividends_impl` calls Polygon's `/v3/reference/dividends` (via the existing
`polygon.RESTClient`'s `list_dividends` helper, or a direct `httpx` call authenticated the same
way as `_get_bars_impl` if the SDK lacks a convenience method — confirm which at implementation
time) filtered by `ex_dividend_date.gte`/`.lte`, and maps each result to `{ "ex_date",
"cash_amount", "currency": "USD" }` (Polygon dividends are US-listed only, so currency is always
USD here).

### 3.4 Bar-sync routing by `data_source`

Three existing call sites must thread the ticker's `data_source` through to the `provider`
kwarg so the nightly top-up and manual resyncs actually reach the new provider once LT-1a sets
`data_source="yfinance"` on Canadian roster rows:

1. **`sync_stock_aggregates`** (`backend/app/tasks/sync.py:296`): add `provider: str =
   "massive"` to its signature, pass it to `StockDataService.get_aggregates(..., provider=provider)`.
   Update the "no bars returned" log line to name the actual provider instead of hardcoding
   "Polygon".
2. **`universe_orchestrator.sync_missing_aggregates()`** (`backend/app/services/universe_orchestrator.py:~163`):
   the loop currently only has ticker strings (`stock_tickers = [s.ticker for s in stocks if
   s.asset_class != "futures"]`); build a `{ticker: data_source}` lookup from the already-queried
   `stocks` list instead and pass `provider=lookup[ticker]` into each `sync_stock_aggregates.delay(...)` call.
3. **`universe_orchestrator`'s per-universe resync loop** (`backend/app/services/universe_orchestrator.py:~397`):
   this loop already iterates full `MonitoredStock` rows (`for stock in stocks: ... else:
   sync_stock_aggregates.delay(ticker=stock.ticker, ...)`), so simply add `provider=stock.data_source`.
4. **`POST /{ticker}/sync-missing`** (`backend/app/routers/stocks.py:368`): the non-futures
   branch of this single-ticker endpoint currently has no `MonitoredStock` lookup at all (only
   the futures branch queries it, for `exchange`). Add the same kind of lookup
   (`db.query(MonitoredStock).filter(MonitoredStock.ticker == ticker, MonitoredStock.asset_class
   != "futures").first()`) and pass `provider=(stock.data_source if stock else "massive")` so
   this manual endpoint is consistent with the other two call sites. This call site was found
   during spec recon, not in the issue text — flagged in §5 for implementer confirmation, but
   included here because leaving it unrouted would silently break manual resync for Canadian
   tickers while the other two paths work.

Every existing row's `data_source` defaults to `"massive"` (`MonitoredStock.data_source`,
`backend/app/models/monitored_stock.py:28`), so this change is a no-op for every ticker in the
system today.

### 3.5 `lt_dividend` table + `fetch_dividends` task

New model `backend/app/models/lt_dividend.py`, following `StockSplit`'s shape
(`backend/app/models/stock_split.py`):

```python
class LtDividend(Base):
    __tablename__ = "lt_dividend"
    id = Column(Integer, primary_key=True, index=True)
    ticker = Column(String(20), nullable=False, index=True)
    ex_date = Column(Date, nullable=False, index=True)
    cash_amount = Column(Numeric, nullable=False)
    currency = Column(String(3), nullable=False)
    source = Column(String(20), nullable=False)  # "massive" | "yfinance"
    __table_args__ = (UniqueConstraint("ticker", "ex_date", name="uq_lt_dividend_ticker_ex_date"),)
```

Register in `backend/app/models/__init__.py`. Generate the migration with `alembic revision
--autogenerate`.

New task `fetch_dividends` in `backend/app/tasks/sync.py` (or a new `backend/app/tasks/
long_term.py` if the team prefers keeping LT-prefixed tasks separate from the existing
scanner/universe tasks — either is consistent with the existing single-`tasks/sync.py` file
holding unrelated reference-data tasks like `sync_stock_splits`; pick one and keep all LT-1b
tasks together):

```python
@celery_app.task(bind=True, max_retries=3, name="app.tasks.fetch_dividends")
def fetch_dividends(self, tickers: list[str], from_date: str, to_date: str, source: str):
    """Fetch and upsert dividend rows for `tickers` from `source` ("massive" | "yfinance")."""
```

For each ticker, call `DataProviderFactory.get(source).get_dividends(ticker, from_date,
to_date)`, upsert each returned row into `lt_dividend` on `(ticker, ex_date)`. A `ProviderError`
from an open breaker should not retry (mirrors A4); any other retryable error should
`self.retry(...)`, matching `sync_stock_splits`'s 429-retry shape.

### 3.6 `fx_rate_daily` table + `fetch_fx_rate` task

New model `backend/app/models/fx_rate_daily.py`:

```python
class FxRateDaily(Base):
    __tablename__ = "fx_rate_daily"
    id = Column(Integer, primary_key=True, index=True)
    pair = Column(String(10), nullable=False, index=True)  # "USDCAD"
    date = Column(Date, nullable=False, index=True)
    rate = Column(Numeric, nullable=False)
    __table_args__ = (UniqueConstraint("pair", "date", name="uq_fx_rate_daily_pair_date"),)
```

New task `fetch_fx_rate`:

```python
@celery_app.task(bind=True, max_retries=3, name="app.tasks.fetch_fx_rate")
def fetch_fx_rate(self, pair: str, from_date: str, to_date: str):
    """Fetch and upsert FX rate rows for `pair` (e.g. "USDCAD")."""
```

Tries `DataProviderFactory.get("yfinance").get_bars(symbol="CAD=X", timespan="day",
multiplier=1, from_date=from_date, to_date=to_date)` first, using each bar's `close` as that
day's rate. On a `ProviderError` from yfinance (including an open `YFINANCE_BREAKER`), falls
back to `DataProviderFactory.get("massive").get_bars(symbol="C:USDCAD", ...)`. Upsert on
`(pair, date)`. This mirrors A2/A3: the fallback is internal to the task, not exposed as a
caller-visible parameter.

### 3.7 Circuit breaker

New `YFINANCE_BREAKER` in `backend/app/core/circuit_breakers.py`, built the same way as
`POLYGON_BREAKER`:

```python
YFINANCE_BREAKER: pybreaker.CircuitBreaker = pybreaker.CircuitBreaker(
    fail_max=settings.YFINANCE_CB_FAIL_MAX,
    reset_timeout=settings.YFINANCE_CB_RESET_TIMEOUT,
    exclude=[_non_retryable_provider_error],
    listeners=[HealthRecordingListener("yfinance")],
)
```

New settings in `backend/app/core/config.py`, next to the Polygon/IBKR breaker settings:
`YFINANCE_CB_FAIL_MAX: int = 3`, `YFINANCE_CB_RESET_TIMEOUT: int = 300`. These are more
conservative than Polygon's `5`/`60` because yfinance is an unofficial client used only in
nightly batch jobs (not latency-sensitive scans), and aggressive retrying against an
undocumented endpoint risks a Yahoo-side rate-limit ban. One breaker covers every yfinance call
(bars, dividends, FX) — a Yahoo-side outage opens it once and `fetch_fx_rate` falls through to
the Polygon fallback immediately rather than retrying yfinance per call type. Document both new
settings in `ENV_VARIABLES.md` next to the existing `POLYGON_CB_*`/`IBKR_CB_*` entries.

### 3.8 Dependency pin

Add `yfinance==1.8.0` to `backend/requirements.txt` (latest stable release at spec time, per
`pip index versions yfinance`), in the "Financial Data" section next to `polygon-api-client`
and `ib_insync`.

### 3.9 Testing

- `backend/tests/providers/test_yfinance_provider.py`: construct via
  `YFinanceDataProvider.__new__(YFinanceDataProvider)` (no `__init__`, matching
  `test_ibkr_provider.py`), patch `app.providers.yfinance_provider.yf.Ticker` to return a small
  hand-built `pandas.DataFrame`/`Series`. Cover: `get_bars` → standard bar-dict shape with
  `auto_adjust=False` passed through; `.TO` ticker passed to `yf.Ticker` unchanged; empty-frame
  → `[]`; a raised exception from the mocked `yf.Ticker` surfaces as `ProviderError` and counts
  toward `YFINANCE_BREAKER`; `get_dividends` → dividend-row shape.
- `backend/tests/providers/test_massive_dividends.py` (or extend an existing Massive test
  file): patch the `polygon.RESTClient` the same way existing Massive tests do; cover
  `get_dividends` success, empty result, and breaker-open → `ProviderError`.
- `backend/tests/tasks/test_fetch_dividends.py`, `test_fetch_fx_rate.py`: mock
  `DataProviderFactory.get(...)` (per `backend/tests/fixtures/providers.py`'s pattern) and
  assert the upsert behavior (idempotent re-run, correct `source`/`currency`) against a test DB.
  Cover the "Done when" cases directly: dividends for `TLT` and `XBB.TO`, FX for a one-month
  range.
- `backend/tests/tasks/test_sync_stock_aggregates_routing.py`: assert
  `sync_stock_aggregates.delay(...)` is called with `provider="yfinance"` for a `.TO`-ticker
  `MonitoredStock` row and `provider="massive"` for a plain US ticker, at all three call sites
  in §3.4, with the provider factory mocked.

## 4. Alternatives Considered

1. **Roster-querying tasks** (`fetch_dividends`/`fetch_fx_rate` read `lt_etf`/`MonitoredStock`
   internally, like `sync_universe_aggregates_nightly` does for bars). Rejected: creates a hard
   runtime dependency on LT-1a's roster table being populated, which this slice cannot
   guarantee at test time and doesn't need — the issue's "Done when" only requires the tasks to
   work against an explicit ticker list. Deferred to LT-1c, which already owns backfill/scheduling
   and will naturally build the ticker list from the (by-then-populated) roster.
2. **Raw `httpx` call for Polygon dividends**, following `sync_stock_splits`'s existing
   precedent. Rejected: `MassiveDataProvider.get_ticker_details()` already proves Polygon
   reference-endpoint calls go through `POLYGON_BREAKER` in this provider; a raw call would keep
   hitting Polygon while the breaker is open and would be invisible to `provider_health.py`.
   `sync_stock_splits` is treated as an older exception, not the pattern to extend.
3. **No new circuit breaker; reuse `POLYGON_BREAKER`'s pattern inline per-call, or skip breaking
   yfinance entirely** since it's a new, low-traffic, batch-only provider. Rejected: yfinance is
   explicitly flagged in the epic as an unofficial client that "can break on Yahoo-side
   changes" — wrapping it with its own breaker costs nothing (the `HealthRecordingListener`
   infra is generic) and gives LT-1c's data-health work breaker-state visibility for free.
4. **Separate breakers per yfinance call type** (bars vs. dividends vs. FX). Rejected: adds
   configuration surface for no behavioral benefit at this scale — a Yahoo-side outage affects
   all three uniformly, and a single breaker means `fetch_fx_rate`'s Polygon fallback engages
   immediately on any yfinance degradation, not just FX-specific failures.

## 5. Open Questions (non-blocking)

- Whether `yf.Ticker(ticker).dividends` exposes a reliable per-row currency, or whether
  currency must always be derived from the ticker's country (US → USD, `.TO` → CAD) as
  described in §3.1 — confirm against a live yfinance call during implementation.
- Whether Polygon's `polygon-api-client` SDK (`polygon.RESTClient`) has a built-in
  `list_dividends`/equivalent helper, or whether `_get_dividends_impl` needs a direct `httpx`
  call inside `MassiveDataProvider` (still breaker-wrapped) the way `_get_bars_impl` uses the
  SDK's `get_aggs` — check the installed `polygon-api-client==1.16.3` surface at implementation
  time.
- Whether `fetch_dividends`/`fetch_fx_rate` belong in the existing `backend/app/tasks/sync.py`
  or a new `backend/app/tasks/long_term.py` — left to the builder (§3.5); either is consistent
  with existing conventions.
- The `POST /{ticker}/sync-missing` routing fix (§3.4, item 4) was found during spec recon, not
  stated in the issue body — confirm it's wanted in this slice rather than deferred, though
  leaving it out would mean this one manual endpoint silently stays on Massive for Canadian
  tickers while the nightly/universe paths route correctly.

## 6. Assumptions (flagged)

- LT-1a (#904) merges before LT-1b implementation begins, so `MonitoredStock.data_source`
  and `StockUniverseTicker.data_source` are populated with `"yfinance"` for `.TO` roster rows
  by the time this slice's routing change (§3.4) has real Canadian tickers to route. Nothing in
  this slice breaks if that's not yet true — every existing row defaults to `"massive"`.
- `yfinance==1.8.0` installs cleanly alongside the existing pinned stack (`pandas==2.3.3`,
  `numpy==2.3.3`, etc.) — not verified in this spec; if it conflicts, the implementer bumps the
  pin and notes why in the commit, per A4.
- Yahoo's `.TO` suffix convention and `CAD=X` forex ticker format remain stable — this is the
  same external-stability risk the epic already flags for `yfinance_provider.py` generally
  (§4.2), not a new one introduced by the dividends/FX tasks.
- Daily resolution (`timespan="day", multiplier=1`) is the only resolution this slice's
  provider needs to support, per the epic's "daily resolution" decision (§6) — `get_bars` is
  not required to handle minute/hour bars for yfinance.
