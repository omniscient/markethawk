# LT-1b: yfinance Provider (Canadian Bars), lt_dividend, fx_rate_daily — Implementation Plan

**Issue:** #912

**Spec:** `docs/superpowers/specs/2026-11-06-lt1b-yfinance-provider-dividends-fx-design.md`

**Goal:** Fetch Canadian (`.TO`) daily bars, dividends for both markets, and the USDCAD rate on demand,
all through the existing provider abstraction. Bar sync routes each ticker by its `data_source`.

**Architecture:** A new `YFinanceDataProvider` (a `BaseDataProvider` subclass registered in
`DataProviderFactory`, with every call wrapped by a new `YFINANCE_BREAKER`) serves daily bars and
dividend history. `BaseDataProvider` gains a non-abstract `get_dividends()` that raises
`NotImplementedError` by default. `MassiveDataProvider` overrides it with a `POLYGON_BREAKER`-wrapped
`/v3/reference/dividends` call. `sync_stock_aggregates` gains a `provider` kwarg (default
`"massive"`), and all three call sites pass the ticker's `MonitoredStock.data_source`. Two new tables
(`lt_dividend`, `fx_rate_daily`) are filled by two explicit-input Celery tasks in a new
`app/tasks/long_term.py`: `fetch_dividends(tickers, from_date, to_date, source)` and
`fetch_fx_rate(pair, from_date, to_date)`, where FX tries yfinance `CAD=X` first and falls back to
Polygon `C:USDCAD`. Both tasks upsert on their natural key.

**Tech Stack:** FastAPI, SQLAlchemy 2.0 (sync), PostgreSQL (`ON CONFLICT DO UPDATE` upserts),
Celery, pybreaker, `yfinance==1.8.0`, `polygon-api-client==1.16.3`, pytest (testcontainers / `db`
fixture), Alembic.

---

## Scope notes (read before starting)

- **Settled by the spec (follow it, do not re-open):** the two fetch tasks take explicit inputs and
  **never** query `lt_etf` / `MonitoredStock`. Nightly beat entries, the 1830-day self-backfill, and
  roster iteration (the "carried-over decisions" in the issue body that name
  `sync_lt_dividends_nightly` / `sync_fx_rates_nightly`) are **LT-1c**, per spec §1 and the refine
  Q&A. Do not add beat entries or roster queries in this slice.
- **Spec open questions, resolved during plan recon (with evidence):**
  - *Polygon SDK dividends helper*: `polygon.RESTClient.list_dividends(ticker=..., ex_dividend_date_gte=..., ex_dividend_date_lte=..., limit=...)`
    exists in the installed `polygon-api-client==1.16.3`. It returns a lazily paginating iterator of
    `Dividend` dataclasses with `ex_dividend_date` (str), `cash_amount` (float) and `currency` (str).
    Use the SDK, not raw `httpx`.
  - *yfinance dividend currency*: in yfinance 1.8.0, `Ticker.dividends` is normally a `pd.Series`
    with no currency. When Yahoo reports a dividend currency that differs from the price currency
    (`scrapers/history.py`: "Rare … companies that distribute dividends in a different currency"),
    it is instead a `pd.DataFrame` with `Dividends` and `currency` columns. The provider handles both
    shapes. It uses the per-row currency when present and falls back to the ticker suffix (`.TO` → CAD,
    else USD).
  - *Task module*: the tasks go in a new `backend/app/tasks/long_term.py`, which keeps all LT-1b
    tasks together. Celery's `include=["app.tasks"]` imports the package, so the tasks must be
    re-exported from `app/tasks/__init__.py` (Task 14).
  - *`POST /{ticker}/sync-missing` routing*: included, per the refine summary's Requirements list.
- **Dependency check done at plan time:** `pip install --dry-run yfinance==1.8.0 pandas==2.3.3 numpy==2.3.3 websockets==16.0`
  resolves cleanly on Python 3.14. It would add `beautifulsoup4, curl_cffi 0.17.0, lxml, peewee, soupsieve`.
- **Small, deliberate refinements beyond the spec text (each justified inline in its task):**
  1. `sync_stock_aggregates` stores `StockAggregate.provider="yfinance"` for yfinance rows. It used to
     hardcode `"polygon"`, which would mislabel Canadian bars. Massive rows stay `"polygon"`.
  2. `YFinanceDataProvider.get_bars` returns `[]` (with a warning) for any timespan other than
     `day×1`. Universe sync-missing may queue minute combos for a `.TO` ticker, and those should be
     a no-op, not a retry loop.
  3. `fetch_fx_rate` also falls back to Polygon when yfinance returns **no rows**, as well as on a
     `ProviderError`. A silent empty response from an unofficial client is the same failure in practice.
  4. The provider calls are timed with `track_provider_call(...)`, the same as every Massive call, so
     LT-1c's data-health work has yfinance latency/error data without extra wiring.
  5. `ENV_VARIABLES.md` has no circuit-breaker section today, so the spec's "next to the existing
     `POLYGON_CB_*` entries" anchor does not exist. Task 2 adds a "Circuit Breakers" table listing the
     four existing breaker vars and the two new ones.
- **Known follow-up, out of scope here:** two other bar fetchers still hard-route to Massive.
  `app/services/normalization.py` `_sync_stock_range` calls `StockDataService.get_aggregates`
  without `provider=`, and the synchronous refresh path in `app/services/stock_data.py` (around
  line 390) hardcodes massive / `provider="polygon"`. Neither is one of the spec's §3.4 call sites,
  so they stay unchanged. Quality normalization for `.TO` tickers will fetch nothing until a later
  slice routes them. Call this out in the PR body as a follow-up for LT-1c (data-health).
- **Known limitation (PR-body note):** the `/sync-missing` lookup in Task 11 takes the first
  non-futures `MonitoredStock` row for the ticker, with no `is_active` filter, which matches the
  spec's query. If a ticker sits in several universes with *different* `data_source` values, the
  provider choice is arbitrary. Roster rows from LT-1a always pair `.TO` with `yfinance`, so this
  does not happen in practice.
- **Known accepted side effect:** `/api/v1/futures/providers` (used by `UniverseFormModal`) will now
  list `yfinance` with classes `["stocks", "forex"]`, so it shows up as a stocks data-source option.
  This is intended: LT-1a's static universe needs that value. No frontend change.

## Memory lessons applied (baked into tasks)

- New breakers live in `app/core/circuit_breakers.py` as module-level singletons built from `settings`
  (Task 2). They are not defined in provider files.
- Sync provider methods use `BREAKER.call(self._impl, ...)` and catch `pybreaker.CircuitBreakerError`
  → `ProviderError(is_retryable=False)`. This is consistent for every method on the provider: both
  `get_bars` and `get_dividends` on yfinance, and the new `get_dividends` on Massive (Tasks 4, 5, 7).
- Never `except (pybreaker.CircuitBreakerError, Exception)`. Use separate handlers (Tasks 4, 5, 7).
- New models are imported into `backend/app/models/__init__.py` and added to `__all__` (Task 8).
- Tests use the `db` fixture (real PostgreSQL) for upsert assertions, never SQLite in-memory
  (`ON CONFLICT` plus JSONB models break SQLite). Orchestrator and router routing tests use `MagicMock` DBs.
- Running a single test file must pass `--no-cov`. `backend/pyproject.toml` sets
  `--cov-fail-under=60` in `addopts`, so a partial run would fail on coverage alone.

## File Structure

| File | Action | Responsibility |
|---|---|---|
| `backend/requirements.txt` | Modify | Pin `yfinance==1.8.0` in "Financial Data" |
| `backend/app/core/config.py` | Modify | `YFINANCE_CB_FAIL_MAX=3`, `YFINANCE_CB_RESET_TIMEOUT=300` |
| `backend/app/core/circuit_breakers.py` | Modify | `YFINANCE_BREAKER` singleton |
| `ENV_VARIABLES.md` | Modify | New "Circuit Breakers" table (existing + new vars) |
| `backend/app/providers/base.py` | Modify | Non-abstract `get_dividends()` default → `NotImplementedError` |
| `backend/app/providers/yfinance_provider.py` | Create | `YFinanceDataProvider` (`get_bars`, `get_dividends`), `currency_for_ticker` |
| `backend/app/providers/__init__.py` | Modify | Register `YFinanceDataProvider` |
| `backend/app/providers/massive.py` | Modify | `get_dividends()` via `list_dividends`, `POLYGON_BREAKER`-wrapped |
| `backend/app/models/lt_dividend.py` | Create | `LtDividend` model |
| `backend/app/models/fx_rate_daily.py` | Create | `FxRateDaily` model |
| `backend/app/models/__init__.py` | Modify | Import and export both models |
| `backend/app/alembic/versions/a7b8c9d0e1f2_add_lt_dividend_and_fx_rate_daily.py` | Create | Migration for both tables |
| `backend/app/tasks/sync.py` | Modify | `sync_stock_aggregates(provider=...)`, provider-labelled rows |
| `backend/app/services/universe_orchestrator.py` | Modify | Pass `provider=data_source` at both call sites |
| `backend/app/routers/stocks.py` | Modify | `/sync-missing` stock branch looks up `data_source` |
| `backend/app/tasks/long_term.py` | Create | `fetch_dividends`, `fetch_fx_rate`, upsert helpers, `_bar_date` |
| `backend/app/tasks/__init__.py` | Modify | Re-export both new tasks |
| `backend/tests/providers/test_circuit_breakers.py` | Modify | yfinance breaker settings and singleton tests |
| `backend/tests/providers/test_base_provider_dividends.py` | Create | Base default and IBKR `NotImplementedError` |
| `backend/tests/providers/test_yfinance_provider.py` | Create | Bars, dividends, breaker, registration |
| `backend/tests/providers/test_massive_dividends.py` | Create | Massive `get_dividends` |
| `backend/tests/models/test_lt_models.py` | Create | Model shape and registration |
| `backend/tests/tasks/test_sync_tasks.py` | Modify | `sync_stock_aggregates` provider kwarg |
| `backend/tests/tasks/test_sync_stock_aggregates_routing.py` | Create | All three call sites route by `data_source` |
| `backend/tests/tasks/test_fetch_dividends.py` | Create | Done-when: TLT and XBB.TO rows, idempotency, retry |
| `backend/tests/tasks/test_fetch_fx_rate.py` | Create | Done-when: one-month USDCAD, fallback, retry |
| `backend/tests/tasks/test_package_exports.py` | Modify | Register new public tasks |

All commands below run from `backend/` unless stated otherwise.

**Pre-commit hook:** `.git/hooks/pre-commit` runs `ruff --fix` and `ruff-format` on `backend/`.
Several code blocks below will be reformatted the first time you commit them (long query lines,
compact dict literals, magic trailing commas). If a commit aborts because the hook modified
files, re-`git add` the same paths and repeat the same `git commit` command. That is expected and
not a failure. Never pass `--no-verify`.

---

## Task 1: Pin and install yfinance

**Files:** `backend/requirements.txt`

- [ ] **Step 1.1:** In `backend/requirements.txt`, in the `# Financial Data` block, add one line directly after `polygon-api-client==1.16.3`:

```text
polygon-api-client==1.16.3
yfinance==1.8.0    # Canadian (.TO) bars, dividends, CAD=X FX — unofficial Yahoo client (LT-1b, #912)
websockets==16.0
```

- [ ] **Step 1.2:** Install it into the environment the tests run in:

```bash
pip install yfinance==1.8.0
python -c "import yfinance, pandas; print(yfinance.__version__, pandas.__version__)"
```

Expected: `1.8.0 2.3.3`. If the install changes the `pandas`/`numpy` versions, stop. Pick the newest
yfinance 1.x that leaves `pandas==2.3.3` and `numpy==2.3.3` alone, and note the reason in the
commit message (spec §6 assumption).

- [ ] **Step 1.3:** Run the dependency audit CI uses, so a new transitive advisory shows up now and
not in CI:

```bash
pip install pip-audit && pip-audit -r requirements.txt --ignore-vuln PYSEC-2022-42969 --ignore-vuln PYSEC-2026-1325
```

Expected: `No known vulnerabilities found`. If a yfinance transitive dependency (`curl_cffi`,
`lxml`, `peewee`, `beautifulsoup4`) is flagged, pin a fixed version of that package on its own line
under `yfinance` and re-run.

- [ ] **Step 1.4:** Commit:

```bash
git add backend/requirements.txt
git commit -m "deps: pin yfinance==1.8.0 for Canadian bars/dividends/FX (#912)"
```

---

## Task 2: `YFINANCE_BREAKER` + settings + env docs

**Files:** `backend/app/core/config.py`, `backend/app/core/circuit_breakers.py`, `ENV_VARIABLES.md`, `backend/tests/providers/test_circuit_breakers.py`

- [ ] **Step 2.1 (failing test):** In `backend/tests/providers/test_circuit_breakers.py`, add these two methods inside `class TestCircuitBreakerSettings`, after `test_ibkr_cb_params_overrideable`:

```python
    def test_yfinance_cb_defaults(self):
        from app.core.config import Settings

        s = Settings(
            DATABASE_URL="postgresql://t:t@localhost/t",
            POLYGON_API_KEY="key",
        )
        assert s.YFINANCE_CB_FAIL_MAX == 3
        assert s.YFINANCE_CB_RESET_TIMEOUT == 300

    def test_yfinance_cb_params_overrideable(self):
        from app.core.config import Settings

        s = Settings(
            DATABASE_URL="postgresql://t:t@localhost/t",
            POLYGON_API_KEY="key",
            YFINANCE_CB_FAIL_MAX=6,
            YFINANCE_CB_RESET_TIMEOUT=45,
        )
        assert s.YFINANCE_CB_FAIL_MAX == 6
        assert s.YFINANCE_CB_RESET_TIMEOUT == 45
```

Then append this module-level test at the end of the file:

```python
def test_yfinance_breaker_singleton_built_from_settings():
    from app.core.circuit_breakers import (
        YFINANCE_BREAKER,
        HealthRecordingListener,
        _non_retryable_provider_error,
    )
    from app.core.config import settings

    assert YFINANCE_BREAKER.fail_max == settings.YFINANCE_CB_FAIL_MAX
    assert YFINANCE_BREAKER.reset_timeout == settings.YFINANCE_CB_RESET_TIMEOUT
    listeners = [
        lst for lst in YFINANCE_BREAKER.listeners
        if isinstance(lst, HealthRecordingListener)
    ]
    assert [lst.provider for lst in listeners] == ["yfinance"]
    # Non-retryable ProviderErrors are excluded from fail counting, like Polygon.
    assert _non_retryable_provider_error in YFINANCE_BREAKER.excluded_exceptions
```

- [ ] **Step 2.2 (verify fail):**

```bash
python -m pytest tests/providers/test_circuit_breakers.py -k yfinance -v --no-cov
```

Expected: 3 failures. The settings tests fail with `AttributeError: 'Settings' object has no attribute 'YFINANCE_CB_FAIL_MAX'` (or a pydantic `ValidationError` for the override test, if `Settings` forbids extra fields); the singleton test fails with `ImportError: cannot import name 'YFINANCE_BREAKER'`.

- [ ] **Step 2.3 (implement settings):** In `backend/app/core/config.py`, directly after `IBKR_CB_RESET_TIMEOUT: int = 120`, add:

```python
    # yfinance breaker: open after 3 consecutive failures; retry after 300 s.
    # More conservative than Polygon: unofficial client, nightly batch only, and
    # hammering an undocumented Yahoo endpoint risks a Yahoo-side rate-limit ban.
    YFINANCE_CB_FAIL_MAX: int = 3
    YFINANCE_CB_RESET_TIMEOUT: int = 300
```

- [ ] **Step 2.4 (implement breaker):** In `backend/app/core/circuit_breakers.py`:

Replace the docstring's first paragraph lines

```text
Two module-level breakers are provided:
  POLYGON_BREAKER — wraps synchronous Polygon API calls in MassiveDataProvider.
  IBKR_BREAKER    — wraps async IBKR calls in IBKRDataProvider.

Both are built from Settings at import time so parameters are tunable via env vars
(POLYGON_CB_FAIL_MAX, POLYGON_CB_RESET_TIMEOUT, IBKR_CB_FAIL_MAX, IBKR_CB_RESET_TIMEOUT).
```

with

```text
Three module-level breakers are provided:
  POLYGON_BREAKER  — wraps synchronous Polygon API calls in MassiveDataProvider.
  IBKR_BREAKER     — wraps async IBKR calls in IBKRDataProvider.
  YFINANCE_BREAKER — wraps synchronous yfinance calls in YFinanceDataProvider
                     (bars, dividends and CAD=X FX share one breaker).

All are built from Settings at import time so parameters are tunable via env vars
(POLYGON_CB_*, IBKR_CB_*, YFINANCE_CB_FAIL_MAX, YFINANCE_CB_RESET_TIMEOUT).
```

Append at the end of the file:

```python

YFINANCE_BREAKER: pybreaker.CircuitBreaker = pybreaker.CircuitBreaker(
    fail_max=settings.YFINANCE_CB_FAIL_MAX,
    reset_timeout=settings.YFINANCE_CB_RESET_TIMEOUT,
    exclude=[_non_retryable_provider_error],
    listeners=[HealthRecordingListener("yfinance")],
)
```

- [ ] **Step 2.5 (verify pass):**

```bash
python -m pytest tests/providers/test_circuit_breakers.py -v --no-cov
```

Expected: all tests pass, including the 3 new `yfinance` ones. (`excluded_exceptions` and
`listeners` are public attributes on the installed pybreaker; this was checked at plan time.)

- [ ] **Step 2.6 (docs):** In `ENV_VARIABLES.md`, insert this section directly **before** the `## Provider Health / Degraded-Feed Failover` heading:

```markdown
## Circuit Breakers

Per-process breakers around external provider calls (`backend/app/core/circuit_breakers.py`). All
are optional. To override one, add it to the `backend` and `celery-worker` `environment:` blocks.

| Variable | Default | Description |
|---|---|---|
| `POLYGON_CB_FAIL_MAX` | `5` | Consecutive Polygon failures before the breaker opens. |
| `POLYGON_CB_RESET_TIMEOUT` | `60` | Seconds the Polygon breaker stays open before a half-open probe. |
| `IBKR_CB_FAIL_MAX` | `3` | Consecutive IBKR failures before the breaker opens. |
| `IBKR_CB_RESET_TIMEOUT` | `120` | Seconds the IBKR breaker stays open before a half-open probe. |
| `YFINANCE_CB_FAIL_MAX` | `3` | Consecutive yfinance failures (bars, dividends, `CAD=X` FX) before the breaker opens. Conservative: yfinance is an unofficial client used only in batch jobs. |
| `YFINANCE_CB_RESET_TIMEOUT` | `300` | Seconds the yfinance breaker stays open. While open, `fetch_fx_rate` falls back to Polygon `C:USDCAD` immediately. |

---
```

- [ ] **Step 2.7:** Commit:

```bash
git add backend/app/core/config.py backend/app/core/circuit_breakers.py ENV_VARIABLES.md backend/tests/providers/test_circuit_breakers.py
git commit -m "feat(providers): add YFINANCE_BREAKER and its settings (#912)"
```

---

## Task 3: `BaseDataProvider.get_dividends()` default

**Files:** `backend/app/providers/base.py`, `backend/tests/providers/test_base_provider_dividends.py`

- [ ] **Step 3.1 (failing test):** Create `backend/tests/providers/test_base_provider_dividends.py`:

```python
"""BaseDataProvider.get_dividends() is a concrete default, not part of the abstract contract."""

import pytest

from app.providers.base import BaseDataProvider


class _BarsOnlyProvider(BaseDataProvider):
    name = "bars-only"
    supported_asset_classes = ["stocks"]

    def is_available(self):
        return True, "Ready"

    def get_bars(self, symbol, timespan, multiplier, from_date, to_date, **kwargs):
        return []

    def get_snapshots(self, symbols=None):
        return []

    def get_ticker_details(self, symbol):
        return {}


def test_subclass_without_get_dividends_is_instantiable_and_raises():
    p = _BarsOnlyProvider()  # would TypeError if get_dividends were abstract
    with pytest.raises(NotImplementedError, match="bars-only does not support get_dividends"):
        p.get_dividends("AAPL", "2026-01-01", "2026-01-31")


def test_ibkr_inherits_not_implemented_default():
    from app.providers.ibkr import IBKRDataProvider

    p = IBKRDataProvider.__new__(IBKRDataProvider)
    with pytest.raises(NotImplementedError):
        p.get_dividends("ES", "2026-01-01", "2026-01-31")
```

- [ ] **Step 3.2 (verify fail):**

```bash
python -m pytest tests/providers/test_base_provider_dividends.py -v --no-cov
```

Expected: 2 failures, `AttributeError: '_BarsOnlyProvider' object has no attribute 'get_dividends'` (and the same for `IBKRDataProvider`).

- [ ] **Step 3.3 (implement):** In `backend/app/providers/base.py`, append this method at the end of the class, after `get_ticker_details`:

```python

    # ------------------------------------------------------------------ #
    #  Corporate actions (optional — not part of the abstract contract)    #
    # ------------------------------------------------------------------ #

    def get_dividends(
        self, ticker: str, from_date: str, to_date: str
    ) -> List[Dict[str, Any]]:
        """
        Fetch cash-dividend history for a ticker, ex-date range inclusive.

        Returns a list of dicts:
            { "ex_date": date, "cash_amount": float, "currency": str }

        Providers that don't support this raise NotImplementedError.
        """
        raise NotImplementedError(f"{self.name} does not support get_dividends()")
```

- [ ] **Step 3.4 (verify pass):** Re-run the Step 3.2 command. Expected: `2 passed`.

- [ ] **Step 3.5:** Commit:

```bash
git add backend/app/providers/base.py backend/tests/providers/test_base_provider_dividends.py
git commit -m "feat(providers): add optional BaseDataProvider.get_dividends (#912)"
```

---

## Task 4: `YFinanceDataProvider.get_bars`

**Files:** `backend/app/providers/yfinance_provider.py`, `backend/tests/providers/test_yfinance_provider.py`

- [ ] **Step 4.1 (failing test):** Create `backend/tests/providers/test_yfinance_provider.py`:

```python
"""
YFinanceDataProvider — mocked at the yfinance library boundary (yf.Ticker),
like test_ibkr_provider.py mocks ib_insync. No live network.
"""

from datetime import datetime, timezone
from unittest.mock import patch

import pandas as pd
import pybreaker
import pytest

from app.core.circuit_breakers import _non_retryable_provider_error
from app.exceptions import ProviderError

_YF = "app.providers.yfinance_provider.yf.Ticker"
_BREAKER = "app.providers.yfinance_provider.YFINANCE_BREAKER"


def _make_provider():
    from app.providers.yfinance_provider import YFinanceDataProvider

    return YFinanceDataProvider.__new__(YFinanceDataProvider)


def _fresh_breaker(fail_max: int = 3) -> pybreaker.CircuitBreaker:
    return pybreaker.CircuitBreaker(
        fail_max=fail_max, reset_timeout=60, exclude=[_non_retryable_provider_error]
    )


def _frame(rows, tz="America/Toronto") -> pd.DataFrame:
    """rows: [(YYYY-MM-DD, (open, high, low, close, volume)), ...] — yfinance daily shape."""
    index = pd.DatetimeIndex([pd.Timestamp(d, tz=tz) for d, _ in rows], name="Date")
    return pd.DataFrame(
        [
            {"Open": o, "High": h, "Low": lo, "Close": c, "Adj Close": c, "Volume": v}
            for _, (o, h, lo, c, v) in rows
        ],
        index=index,
    )


# ---------------------------------------------------------------------------
# get_bars
# ---------------------------------------------------------------------------


class TestGetBars:
    def test_maps_daily_frame_to_standard_bar_shape(self):
        p = _make_provider()
        frame = _frame(
            [
                ("2026-10-01", (35.0, 35.5, 34.8, 35.2, 120_000)),
                ("2026-10-02", (35.2, 35.9, 35.1, 35.8, 98_000)),
            ]
        )
        with patch(_YF) as ticker_cls, patch(_BREAKER, _fresh_breaker()):
            ticker_cls.return_value.history.return_value = frame
            bars = p.get_bars("XIU.TO", "day", 1, "2026-10-01", "2026-10-02")

        ticker_cls.assert_called_once_with("XIU.TO")  # .TO passes straight through
        kwargs = ticker_cls.return_value.history.call_args.kwargs
        assert kwargs["auto_adjust"] is False  # raw closes, consistent with Massive
        assert kwargs["interval"] == "1d"
        assert kwargs["start"] == "2026-10-01"
        assert kwargs["end"] == "2026-10-03"  # yfinance end is exclusive; contract is inclusive

        assert len(bars) == 2
        first = bars[0]
        # Toronto midnight (EDT, UTC-4) expressed as UTC-aware datetime
        assert first["timestamp"] == datetime(2026, 10, 1, 4, 0, tzinfo=timezone.utc)
        assert first["timestamp"].utcoffset().total_seconds() == 0
        assert (first["open"], first["high"], first["low"], first["close"]) == (
            35.0, 35.5, 34.8, 35.2,
        )
        assert first["volume"] == 120_000 and isinstance(first["volume"], int)
        assert first["vwap"] is None
        assert first["transactions"] is None

    def test_empty_frame_returns_empty_list(self):
        p = _make_provider()
        with patch(_YF) as ticker_cls, patch(_BREAKER, _fresh_breaker()):
            ticker_cls.return_value.history.return_value = pd.DataFrame()
            assert p.get_bars("NOPE.TO", "day", 1, "2026-10-01", "2026-10-31") == []

    def test_rows_with_nan_close_are_dropped(self):
        p = _make_provider()
        frame = _frame(
            [
                ("2026-10-01", (35.0, 35.5, 34.8, float("nan"), 0)),
                ("2026-10-02", (35.2, 35.9, 35.1, 35.8, 98_000)),
            ]
        )
        with patch(_YF) as ticker_cls, patch(_BREAKER, _fresh_breaker()):
            ticker_cls.return_value.history.return_value = frame
            bars = p.get_bars("XIU.TO", "day", 1, "2026-10-01", "2026-10-02")
        assert [b["close"] for b in bars] == [35.8]

    def test_non_daily_timespan_returns_empty_without_calling_yahoo(self):
        p = _make_provider()
        with patch(_YF) as ticker_cls, patch(_BREAKER, _fresh_breaker()):
            assert p.get_bars("XIU.TO", "minute", 1, "2026-10-01", "2026-10-02") == []
        ticker_cls.assert_not_called()

    def test_vendor_exception_raises_provider_error_and_trips_breaker(self):
        p = _make_provider()
        breaker = _fresh_breaker(fail_max=2)
        with patch(_YF, side_effect=RuntimeError("yahoo down")), patch(_BREAKER, breaker):
            with pytest.raises(ProviderError) as first:
                p.get_bars("XIU.TO", "day", 1, "2026-10-01", "2026-10-02")
            assert first.value.is_retryable is True
            assert first.value.provider == "yfinance"

            with pytest.raises(ProviderError):
                p.get_bars("XIU.TO", "day", 1, "2026-10-01", "2026-10-02")
            assert breaker.current_state == "open"

            with pytest.raises(ProviderError) as opened:
                p.get_bars("XIU.TO", "day", 1, "2026-10-01", "2026-10-02")
        assert opened.value.is_retryable is False
        assert opened.value.provider == "yfinance"

    def test_get_bars_through_provider_abstraction(self):
        """Done-when: get_bars("XIU.TO", ...) returns daily bars via the factory + StockDataService."""
        from app.services.stock_data import StockDataService

        frame = _frame([("2026-10-01", (35.0, 35.5, 34.8, 35.2, 120_000))])
        with patch(_YF) as ticker_cls, patch(_BREAKER, _fresh_breaker()):
            ticker_cls.return_value.history.return_value = frame
            bars = StockDataService.get_aggregates(
                ticker="XIU.TO",
                multiplier=1,
                timespan="day",
                from_date="2026-10-01",
                to_date="2026-10-01",
                provider="yfinance",
                paginate=True,  # Massive-only kwargs must be accepted and ignored
            )
        assert len(bars) == 1
        assert bars[0]["close"] == 35.2
        ticker_cls.assert_called_once_with("XIU.TO")
```

- [ ] **Step 4.2 (verify fail):**

```bash
python -m pytest tests/providers/test_yfinance_provider.py -v --no-cov
```

Expected: every test errors with `ModuleNotFoundError: No module named 'app.providers.yfinance_provider'`. The abstraction test may instead fail with `ValueError: DataProviderFactory: Unknown provider 'yfinance'`; that one goes green after Task 6.

- [ ] **Step 4.3 (implement):** Create `backend/app/providers/yfinance_provider.py`:

```python
"""
yfinance Data Provider - Yahoo Finance (unofficial client) implementation.

Serves daily bars and dividend history for tickers Polygon does not cover —
primarily Canadian (TSX, ``.TO``) ETFs — plus the ``CAD=X`` USDCAD rate used by
the FX fetch task.  App tickers pass straight through to Yahoo
(``XIU.TO`` → ``XIU.TO``).

yfinance scrapes undocumented Yahoo endpoints and can break on Yahoo-side
changes, so every call goes through YFINANCE_BREAKER.  Only daily resolution
is supported (epic #902: the long-term strategies are daily-only).
"""

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

import pandas as pd
import pybreaker
import yfinance as yf

from app.core.circuit_breakers import YFINANCE_BREAKER
from app.core.provider_health import track_provider_call
from app.exceptions import ProviderError
from app.providers.base import BaseDataProvider

logger = logging.getLogger(__name__)


def currency_for_ticker(ticker: str) -> str:
    """Listing currency by exchange suffix: ``.TO`` (TSX) → CAD, otherwise USD."""
    return "CAD" if ticker.upper().endswith(".TO") else "USD"


def _to_utc(ts: pd.Timestamp) -> datetime:
    """yfinance indexes daily bars at exchange-local midnight; the contract is UTC-aware."""
    if ts.tzinfo is None:
        ts = ts.tz_localize("UTC")
    return ts.tz_convert(timezone.utc).to_pydatetime()


class YFinanceDataProvider(BaseDataProvider):
    """Yahoo Finance via yfinance — Canadian bars, dividends and CAD=X FX."""

    # ------------------------------------------------------------------ #
    #  BaseDataProvider interface                                          #
    # ------------------------------------------------------------------ #

    @property
    def name(self) -> str:
        return "yfinance"

    @property
    def supported_asset_classes(self) -> List[str]:
        return ["stocks", "forex"]

    def is_available(self) -> tuple[bool, str]:
        # No API key to check; Yahoo reachability is tracked by YFINANCE_BREAKER.
        return True, "Ready"

    def get_bars(
        self,
        symbol: str,
        timespan: str,
        multiplier: int,
        from_date: str,
        to_date: str,
        **kwargs,
    ) -> List[Dict[str, Any]]:
        """
        Fetch raw (unadjusted) daily OHLCV bars, ``to_date`` inclusive.

        Massive-specific kwargs passed by StockDataService.get_aggregates
        (adjusted, sort, limit, paginate) are accepted and ignored: yfinance
        returns the whole range in one response and we always request raw closes.
        """
        if timespan != "day" or multiplier != 1:
            logger.warning(
                f"YFinanceDataProvider: {timespan}×{multiplier} bars not supported "
                f"for {symbol} — daily only; returning no bars."
            )
            return []

        try:
            return YFINANCE_BREAKER.call(
                self._get_bars_impl, symbol, from_date, to_date
            )
        except pybreaker.CircuitBreakerError as e:
            raise ProviderError(
                "yfinance circuit breaker open — provider temporarily unavailable",
                provider="yfinance",
                endpoint="history",
                is_retryable=False,
            ) from e

    def _get_bars_impl(
        self, symbol: str, from_date: str, to_date: str
    ) -> List[Dict[str, Any]]:
        # yfinance's `end` is exclusive; the provider contract's to_date is inclusive.
        end = (datetime.strptime(to_date, "%Y-%m-%d") + timedelta(days=1)).strftime(
            "%Y-%m-%d"
        )
        try:
            with track_provider_call("yfinance", "history"):
                df = yf.Ticker(symbol).history(
                    start=from_date,
                    end=end,
                    interval="1d",
                    auto_adjust=False,
                    actions=False,
                )
        except Exception as e:
            logger.exception(
                f"❌ yfinance fetch FAILED for {symbol} ({from_date} → {to_date}): {e}"
            )
            raise ProviderError(
                f"yfinance fetch failed for {symbol}: {e}",
                provider="yfinance",
                endpoint="history",
                is_retryable=True,
            ) from e

        if df is None or df.empty:
            return []

        bars: List[Dict[str, Any]] = []
        for ts, row in df.dropna(subset=["Close"]).iterrows():
            volume = row.get("Volume")
            bars.append(
                {
                    "timestamp": _to_utc(ts),
                    "open": float(row["Open"]),
                    "high": float(row["High"]),
                    "low": float(row["Low"]),
                    "close": float(row["Close"]),
                    "volume": int(volume) if pd.notna(volume) else 0,
                    "vwap": None,  # yfinance provides neither vwap nor trade count
                    "transactions": None,
                }
            )

        if bars:
            logger.debug(f"YFinanceDataProvider: {symbol} fetched {len(bars)} day bars")
        return bars

    def get_snapshots(
        self, symbols: Optional[List[str]] = None
    ) -> List[Dict[str, Any]]:
        return []

    def get_ticker_details(self, symbol: str) -> Dict[str, Any]:
        return {}
```

- [ ] **Step 4.4 (verify pass):**

```bash
python -m pytest tests/providers/test_yfinance_provider.py -v --no-cov -k "not through_provider_abstraction"
```

Expected: 5 passed. (`test_get_bars_through_provider_abstraction` goes green in Task 6.)

- [ ] **Step 4.5:** Commit:

```bash
git add backend/app/providers/yfinance_provider.py backend/tests/providers/test_yfinance_provider.py
git commit -m "feat(providers): add YFinanceDataProvider.get_bars (raw daily bars) (#912)"
```

---

## Task 5: `YFinanceDataProvider.get_dividends`

**Files:** `backend/app/providers/yfinance_provider.py`, `backend/tests/providers/test_yfinance_provider.py`

- [ ] **Step 5.1 (failing test):** In `backend/tests/providers/test_yfinance_provider.py`, change the import line `from datetime import datetime, timezone` to `from datetime import date, datetime, timezone`. (Task 4 left `date` out on purpose: the pre-commit hook runs `ruff --fix`, which would strip an unused import.) Then append:

```python
# ---------------------------------------------------------------------------
# get_dividends
# ---------------------------------------------------------------------------


def _div_series(points, tz="America/Toronto") -> pd.Series:
    index = pd.DatetimeIndex([pd.Timestamp(d, tz=tz) for d, _ in points], name="Date")
    return pd.Series([v for _, v in points], index=index, name="Dividends")


class TestGetDividends:
    def test_series_filtered_to_range_with_cad_for_tsx(self):
        p = _make_provider()
        divs = _div_series(
            [("2026-08-25", 0.05), ("2026-09-24", 0.06), ("2026-10-28", 0.07)]
        )
        with patch(_YF) as ticker_cls, patch(_BREAKER, _fresh_breaker()):
            ticker_cls.return_value.dividends = divs
            rows = p.get_dividends("XBB.TO", "2026-09-01", "2026-10-31")

        ticker_cls.assert_called_once_with("XBB.TO")
        assert rows == [
            {"ex_date": date(2026, 9, 24), "cash_amount": 0.06, "currency": "CAD"},
            {"ex_date": date(2026, 10, 28), "cash_amount": 0.07, "currency": "CAD"},
        ]

    def test_us_ticker_defaults_to_usd(self):
        p = _make_provider()
        divs = _div_series([("2026-10-01", 0.32)], tz="America/New_York")
        with patch(_YF) as ticker_cls, patch(_BREAKER, _fresh_breaker()):
            ticker_cls.return_value.dividends = divs
            rows = p.get_dividends("TLT", "2026-10-01", "2026-10-31")
        assert rows == [{"ex_date": date(2026, 10, 1), "cash_amount": 0.32, "currency": "USD"}]

    def test_dataframe_with_currency_column_uses_row_currency(self):
        """yfinance 1.8 returns a DataFrame when Yahoo reports a dividend currency."""
        p = _make_provider()
        index = pd.DatetimeIndex(
            [pd.Timestamp("2026-09-24", tz="America/Toronto"),
             pd.Timestamp("2026-10-28", tz="America/Toronto")],
            name="Date",
        )
        divs = pd.DataFrame(
            {"Dividends": [0.06, 0.07], "currency": ["usd", ""]}, index=index
        )
        with patch(_YF) as ticker_cls, patch(_BREAKER, _fresh_breaker()):
            ticker_cls.return_value.dividends = divs
            rows = p.get_dividends("XBB.TO", "2026-09-01", "2026-10-31")
        assert [r["currency"] for r in rows] == ["USD", "CAD"]  # blank → suffix fallback

    def test_empty_series_returns_empty_list(self):
        p = _make_provider()
        with patch(_YF) as ticker_cls, patch(_BREAKER, _fresh_breaker()):
            ticker_cls.return_value.dividends = pd.Series(dtype=float)
            assert p.get_dividends("XBB.TO", "2026-09-01", "2026-10-31") == []

    def test_open_breaker_raises_non_retryable(self):
        p = _make_provider()
        breaker = _fresh_breaker(fail_max=1)
        with patch(_YF, side_effect=RuntimeError("yahoo down")), patch(_BREAKER, breaker):
            with pytest.raises(ProviderError):
                p.get_dividends("XBB.TO", "2026-09-01", "2026-10-31")
            with pytest.raises(ProviderError) as opened:
                p.get_dividends("XBB.TO", "2026-09-01", "2026-10-31")
        assert opened.value.is_retryable is False
        assert opened.value.endpoint == "dividends"


def test_currency_for_ticker():
    from app.providers.yfinance_provider import currency_for_ticker

    assert currency_for_ticker("XIU.TO") == "CAD"
    assert currency_for_ticker("xbb.to") == "CAD"
    assert currency_for_ticker("TLT") == "USD"
```

(`ProviderError.endpoint` is a real attribute, set in `app/exceptions.py:122`.)

- [ ] **Step 5.2 (verify fail):**

```bash
python -m pytest tests/providers/test_yfinance_provider.py -v --no-cov -k "Dividends or currency_for_ticker"
```

Expected: the 5 `TestGetDividends` tests fail with `NotImplementedError: yfinance does not support get_dividends()`, which comes from the Task 3 base default. `test_currency_for_ticker` already passes.

- [ ] **Step 5.3 (implement):** In `backend/app/providers/yfinance_provider.py`, change `from datetime import datetime, timedelta, timezone` to `from datetime import date, datetime, timedelta, timezone`. Then insert these two methods right after `_get_bars_impl` (before `get_snapshots`):

```python
    def get_dividends(
        self, ticker: str, from_date: str, to_date: str
    ) -> List[Dict[str, Any]]:
        """Fetch cash dividends from Yahoo, ex-date range inclusive."""
        try:
            return YFINANCE_BREAKER.call(
                self._get_dividends_impl, ticker, from_date, to_date
            )
        except pybreaker.CircuitBreakerError as e:
            raise ProviderError(
                "yfinance circuit breaker open — provider temporarily unavailable",
                provider="yfinance",
                endpoint="dividends",
                is_retryable=False,
            ) from e

    def _get_dividends_impl(
        self, ticker: str, from_date: str, to_date: str
    ) -> List[Dict[str, Any]]:
        start, end = date.fromisoformat(from_date), date.fromisoformat(to_date)
        try:
            with track_provider_call("yfinance", "dividends"):
                divs = yf.Ticker(ticker).dividends
        except Exception as e:
            logger.exception(f"❌ yfinance dividends FAILED for {ticker}: {e}")
            raise ProviderError(
                f"yfinance dividends fetch failed for {ticker}: {e}",
                provider="yfinance",
                endpoint="dividends",
                is_retryable=True,
            ) from e

        if divs is None or divs.empty:
            return []

        # Normally a Series of amounts.  yfinance returns a DataFrame with a
        # "currency" column instead when Yahoo reports a dividend currency that
        # differs from the price currency — honour it, else derive from suffix.
        if isinstance(divs, pd.DataFrame):
            amounts = divs["Dividends"]
            currencies = (
                list(divs["currency"]) if "currency" in divs.columns else [None] * len(divs)
            )
        else:
            amounts, currencies = divs, [None] * len(divs)

        default_currency = currency_for_ticker(ticker)
        rows: List[Dict[str, Any]] = []
        for (ts, amount), currency in zip(amounts.items(), currencies):
            ex_date = ts.date()  # exchange-local date is the ex-date
            if not (start <= ex_date <= end) or pd.isna(amount) or amount <= 0:
                continue
            rows.append(
                {
                    "ex_date": ex_date,
                    "cash_amount": float(amount),
                    "currency": (
                        currency.upper()
                        if isinstance(currency, str) and currency
                        else default_currency
                    ),
                }
            )
        return rows
```

- [ ] **Step 5.4 (verify pass):**

```bash
python -m pytest tests/providers/test_yfinance_provider.py -v --no-cov -k "not through_provider_abstraction"
```

Expected: 11 passed.

- [ ] **Step 5.5:** Commit:

```bash
git add backend/app/providers/yfinance_provider.py backend/tests/providers/test_yfinance_provider.py
git commit -m "feat(providers): add YFinanceDataProvider.get_dividends (#912)"
```

---

## Task 6: Register the yfinance provider

**Files:** `backend/app/providers/__init__.py`, `backend/tests/providers/test_yfinance_provider.py`

- [ ] **Step 6.1 (failing test):** Append to `backend/tests/providers/test_yfinance_provider.py`:

```python
def test_registered_in_factory():
    from app.providers import DataProviderFactory
    from app.providers.yfinance_provider import YFinanceDataProvider

    p = DataProviderFactory.get("yfinance")
    assert isinstance(p, YFinanceDataProvider)
    assert p.is_available() == (True, "Ready")
    assert "yfinance" in DataProviderFactory.get_available()
```

- [ ] **Step 6.2 (verify fail):**

```bash
python -m pytest tests/providers/test_yfinance_provider.py -v --no-cov -k "registered_in_factory or through_provider_abstraction"
```

Expected: 2 failures with `ValueError: DataProviderFactory: Unknown provider 'yfinance'` (the abstraction test may instead log the error and assert on an empty list).

- [ ] **Step 6.3 (implement):** In `backend/app/providers/__init__.py`:

  - In the module docstring's "Usage" block, after the IBKR lines, add:

    ```text
        # Get yfinance provider (Canadian .TO bars, dividends, CAD=X FX)
        yfinance = DataProviderFactory.get("yfinance")
    ```

  - Replace the registration block

    ```python
    from app.providers.ibkr import IBKRDataProvider  # noqa: E402
    from app.providers.massive import MassiveDataProvider  # noqa: E402

    DataProviderFactory.register(MassiveDataProvider())
    DataProviderFactory.register(IBKRDataProvider())
    ```

    with

    ```python
    from app.providers.ibkr import IBKRDataProvider  # noqa: E402
    from app.providers.massive import MassiveDataProvider  # noqa: E402
    from app.providers.yfinance_provider import YFinanceDataProvider  # noqa: E402

    DataProviderFactory.register(MassiveDataProvider())
    DataProviderFactory.register(IBKRDataProvider())
    DataProviderFactory.register(YFinanceDataProvider())
    ```

  - Add `"YFinanceDataProvider",` to `__all__` after `"IBKRDataProvider",`.

- [ ] **Step 6.4 (verify pass):**

```bash
python -m pytest tests/providers -v --no-cov
```

Expected: every test in `tests/providers` passes, including all 13 in `test_yfinance_provider.py`.

- [ ] **Step 6.5:** Commit:

```bash
git add backend/app/providers/__init__.py backend/tests/providers/test_yfinance_provider.py
git commit -m "feat(providers): register yfinance in DataProviderFactory (#912)"
```

---

## Task 7: `MassiveDataProvider.get_dividends`

**Files:** `backend/app/providers/massive.py`, `backend/tests/providers/test_massive_dividends.py`

- [ ] **Step 7.1 (failing test):** Create `backend/tests/providers/test_massive_dividends.py`:

```python
"""MassiveDataProvider.get_dividends — polygon.RESTClient mocked (no HTTP)."""

from datetime import date
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pybreaker
import pytest

from app.core.circuit_breakers import _non_retryable_provider_error
from app.exceptions import ProviderError

_BREAKER = "app.providers.massive.POLYGON_BREAKER"


def _make_massive():
    from app.providers.massive import MassiveDataProvider

    p = MassiveDataProvider.__new__(MassiveDataProvider)
    p._client = MagicMock()
    return p


def _fresh_breaker(fail_max: int = 3) -> pybreaker.CircuitBreaker:
    return pybreaker.CircuitBreaker(
        fail_max=fail_max, reset_timeout=60, exclude=[_non_retryable_provider_error]
    )


def _div(ex_date, amount, currency="USD"):
    return SimpleNamespace(ex_dividend_date=ex_date, cash_amount=amount, currency=currency)


def test_maps_polygon_results_and_passes_range_filters():
    p = _make_massive()
    p._client.list_dividends.return_value = iter(
        [_div("2026-10-01", 0.3241), _div(None, 0.1), _div("2026-09-02", None)]
    )
    with patch(_BREAKER, _fresh_breaker()):
        rows = p.get_dividends("tlt", "2026-09-01", "2026-10-31")

    p._client.list_dividends.assert_called_once_with(
        ticker="TLT",
        ex_dividend_date_gte="2026-09-01",
        ex_dividend_date_lte="2026-10-31",
        limit=1000,
    )
    assert rows == [{"ex_date": date(2026, 10, 1), "cash_amount": 0.3241, "currency": "USD"}]


def test_missing_currency_defaults_to_usd():
    p = _make_massive()
    p._client.list_dividends.return_value = iter([_div("2026-10-01", 0.3, currency=None)])
    with patch(_BREAKER, _fresh_breaker()):
        rows = p.get_dividends("TLT", "2026-10-01", "2026-10-31")
    assert rows[0]["currency"] == "USD"


def test_empty_result_returns_empty_list():
    p = _make_massive()
    p._client.list_dividends.return_value = iter([])
    with patch(_BREAKER, _fresh_breaker()):
        assert p.get_dividends("TLT", "2026-10-01", "2026-10-31") == []


def test_no_client_returns_empty_list():
    p = _make_massive()
    p._client = None
    assert p.get_dividends("TLT", "2026-10-01", "2026-10-31") == []


def test_sdk_exception_raises_retryable_provider_error():
    p = _make_massive()
    p._client.list_dividends.side_effect = RuntimeError("connection reset")
    with patch(_BREAKER, _fresh_breaker()):
        with pytest.raises(ProviderError) as exc_info:
            p.get_dividends("TLT", "2026-10-01", "2026-10-31")
    assert exc_info.value.is_retryable is True
    assert exc_info.value.provider == "massive"


def test_open_breaker_raises_non_retryable_provider_error():
    p = _make_massive()
    breaker = _fresh_breaker(fail_max=1)
    p._client.list_dividends.side_effect = RuntimeError("polygon down")
    with patch(_BREAKER, breaker):
        with pytest.raises(ProviderError):
            p.get_dividends("TLT", "2026-10-01", "2026-10-31")
        with pytest.raises(ProviderError) as exc_info:
            p.get_dividends("TLT", "2026-10-01", "2026-10-31")
    assert exc_info.value.is_retryable is False
    assert exc_info.value.provider == "massive"
```

- [ ] **Step 7.2 (verify fail):**

```bash
python -m pytest tests/providers/test_massive_dividends.py -v --no-cov
```

Expected: 6 failures, all with `NotImplementedError: massive does not support get_dividends()` (including `test_no_client_returns_empty_list`, since the base default raises before any client check).

- [ ] **Step 7.3 (implement):** In `backend/app/providers/massive.py`:

  - Change `from datetime import datetime, timezone` to `from datetime import date, datetime, timezone`.
  - Insert these methods right after `_get_ticker_details_impl` (before `get_snapshots`):

```python
    def get_dividends(
        self, ticker: str, from_date: str, to_date: str
    ) -> List[Dict[str, Any]]:
        """
        Fetch cash dividends from Polygon /v3/reference/dividends, ex-date range
        inclusive.  Errors propagate (unlike get_ticker_details) so the dividend
        fetch task can retry instead of recording "no dividends".
        """
        if not self._client:
            return []

        try:
            return POLYGON_BREAKER.call(
                self._get_dividends_impl, ticker, from_date, to_date
            )
        except pybreaker.CircuitBreakerError as e:
            raise ProviderError(
                "Polygon circuit breaker open — provider temporarily unavailable",
                provider="massive",
                endpoint="dividends",
                is_retryable=False,
            ) from e

    def _get_dividends_impl(
        self, ticker: str, from_date: str, to_date: str
    ) -> List[Dict[str, Any]]:
        try:
            polygon_api_calls_total.labels(endpoint="dividends").inc()
            with track_provider_call(
                "polygon", "dividends", is_failure=_is_health_failure
            ):
                # list_dividends paginates lazily — materialise inside the try.
                results = list(
                    self._client.list_dividends(
                        ticker=ticker.upper(),
                        ex_dividend_date_gte=from_date,
                        ex_dividend_date_lte=to_date,
                        limit=1000,
                    )
                )
        except Exception as e:
            logger.exception(f"❌ Polygon dividends fetch FAILED for {ticker}: {e}")
            raise ProviderError(
                f"Polygon dividends fetch failed for {ticker}: {e}",
                provider="massive",
                endpoint="dividends",
                is_retryable=not _is_plan_limit_error(e),
            ) from e

        rows: List[Dict[str, Any]] = []
        for d in results:
            ex_date = getattr(d, "ex_dividend_date", None)
            amount = getattr(d, "cash_amount", None)
            if not ex_date or amount is None:
                continue
            rows.append(
                {
                    "ex_date": date.fromisoformat(ex_date),
                    "cash_amount": float(amount),
                    # Polygon dividends cover US listings — USD unless stated.
                    "currency": (getattr(d, "currency", None) or "USD").upper(),
                }
            )
        return rows
```

- [ ] **Step 7.4 (verify pass):**

```bash
python -m pytest tests/providers/test_massive_dividends.py tests/providers/test_circuit_breakers.py tests/providers/test_massive_health_instrumentation.py -v --no-cov
```

Expected: all pass, with 6 new tests in `test_massive_dividends.py`.

- [ ] **Step 7.5:** Commit:

```bash
git add backend/app/providers/massive.py backend/tests/providers/test_massive_dividends.py
git commit -m "feat(providers): add breaker-wrapped MassiveDataProvider.get_dividends (#912)"
```

---

## Task 8: `LtDividend` + `FxRateDaily` models and migration

**Files:** `backend/app/models/lt_dividend.py`, `backend/app/models/fx_rate_daily.py`, `backend/app/models/__init__.py`, `backend/app/alembic/versions/a7b8c9d0e1f2_add_lt_dividend_and_fx_rate_daily.py`, `backend/tests/models/test_lt_models.py`

- [ ] **Step 8.1 (failing test):** Create `backend/tests/models/test_lt_models.py`:

```python
"""Shape of the LT-1b reference-data tables (no DB needed)."""

from sqlalchemy import UniqueConstraint


def _unique_constraints(model):
    return {
        c.name: tuple(col.name for col in c.columns)
        for c in model.__table__.constraints
        if isinstance(c, UniqueConstraint)
    }


def test_lt_dividend_shape():
    from app.models import LtDividend

    t = LtDividend.__table__
    assert t.name == "lt_dividend"
    assert {"id", "ticker", "ex_date", "cash_amount", "currency", "source"} <= set(t.c.keys())
    for col in ("ticker", "ex_date", "cash_amount", "currency", "source"):
        assert t.c[col].nullable is False
    assert t.c.ticker.index and t.c.ex_date.index
    assert _unique_constraints(LtDividend) == {
        "uq_lt_dividend_ticker_ex_date": ("ticker", "ex_date")
    }


def test_fx_rate_daily_shape():
    from app.models import FxRateDaily

    t = FxRateDaily.__table__
    assert t.name == "fx_rate_daily"
    assert {"id", "pair", "date", "rate"} <= set(t.c.keys())
    for col in ("pair", "date", "rate"):
        assert t.c[col].nullable is False
    assert t.c.pair.index and t.c.date.index
    assert _unique_constraints(FxRateDaily) == {
        "uq_fx_rate_daily_pair_date": ("pair", "date")
    }


def test_models_exported():
    import app.models as models

    assert "LtDividend" in models.__all__
    assert "FxRateDaily" in models.__all__
```

- [ ] **Step 8.2 (verify fail):**

```bash
python -m pytest tests/models/test_lt_models.py -v --no-cov
```

Expected: 3 failures. The two shape tests fail with `ImportError: cannot import name 'LtDividend' / 'FxRateDaily' from 'app.models'`, and `test_models_exported` fails with `AssertionError`.

- [ ] **Step 8.3 (implement models):** Create `backend/app/models/lt_dividend.py`:

```python
"""
LtDividend SQLAlchemy model — cash dividends for long-term ETF tickers (LT-1b, #912).
"""

from sqlalchemy import Column, Date, Integer, Numeric, String, UniqueConstraint

from app.core.database import Base


class LtDividend(Base):
    """One cash dividend (ex-date + amount) for a ticker, from Polygon or yfinance."""

    __tablename__ = "lt_dividend"

    id = Column(Integer, primary_key=True, index=True)
    ticker = Column(String(20), nullable=False, index=True)
    ex_date = Column(Date, nullable=False, index=True)
    cash_amount = Column(Numeric, nullable=False)
    currency = Column(String(3), nullable=False)
    source = Column(String(20), nullable=False)  # "massive" | "yfinance"

    __table_args__ = (
        UniqueConstraint("ticker", "ex_date", name="uq_lt_dividend_ticker_ex_date"),
    )
```

Create `backend/app/models/fx_rate_daily.py`:

```python
"""
FxRateDaily SQLAlchemy model — daily FX rates, e.g. USDCAD (LT-1b, #912).
"""

from sqlalchemy import Column, Date, Integer, Numeric, String, UniqueConstraint

from app.core.database import Base


class FxRateDaily(Base):
    """Daily close rate for a currency pair (``rate`` = quote units per 1 base unit)."""

    __tablename__ = "fx_rate_daily"

    id = Column(Integer, primary_key=True, index=True)
    pair = Column(String(10), nullable=False, index=True)  # "USDCAD"
    date = Column(Date, nullable=False, index=True)
    rate = Column(Numeric, nullable=False)

    __table_args__ = (
        UniqueConstraint("pair", "date", name="uq_fx_rate_daily_pair_date"),
    )
```

- [ ] **Step 8.4 (register models):** In `backend/app/models/__init__.py`:
  - Add `from app.models.fx_rate_daily import FxRateDaily` directly after `from app.models.futures_rollover import FuturesRollover` (alphabetical).
  - Add `from app.models.lt_dividend import LtDividend` directly **before** `from app.models.market_holiday import MarketHoliday`, i.e. right after the new `fx_rate_daily` line and the existing `futures_*` lines (alphabetical: `fx_` < `lt_` < `market_`). Confirm with `ruff check app/models/__init__.py`, which should pass with no I001.
  - Append `"LtDividend",` and `"FxRateDaily",` to the end of `__all__` (after `"ReplayTrade",`).

- [ ] **Step 8.5 (verify pass):** Re-run the Step 8.2 command. Expected: `3 passed`.

- [ ] **Step 8.6 (migration):** Check the current head first. LT-1a (#904) may have added a migration since this plan was written:

```bash
python -m alembic heads
```

Expected on this branch's base: `e2f3a4b5c6d7 (head)`. If there is a different single head, use it as `down_revision` below and in the docstring's `Revises:` line. Also check the new revision id is unused: `grep -rl a7b8c9d0e1f2 app/alembic/versions` should print nothing.

Create `backend/app/alembic/versions/a7b8c9d0e1f2_add_lt_dividend_and_fx_rate_daily.py`. It is hand-written so it matches the models exactly and CI's `alembic check` passes:

```python
"""add_lt_dividend_and_fx_rate_daily

Revision ID: a7b8c9d0e1f2
Revises: e2f3a4b5c6d7
Create Date: 2026-11-07 12:00:00.000000
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "a7b8c9d0e1f2"
down_revision: Union[str, None] = "e2f3a4b5c6d7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "lt_dividend",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("ticker", sa.String(length=20), nullable=False),
        sa.Column("ex_date", sa.Date(), nullable=False),
        sa.Column("cash_amount", sa.Numeric(), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("source", sa.String(length=20), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("ticker", "ex_date", name="uq_lt_dividend_ticker_ex_date"),
    )
    op.create_index(op.f("ix_lt_dividend_id"), "lt_dividend", ["id"])
    op.create_index(op.f("ix_lt_dividend_ticker"), "lt_dividend", ["ticker"])
    op.create_index(op.f("ix_lt_dividend_ex_date"), "lt_dividend", ["ex_date"])

    op.create_table(
        "fx_rate_daily",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("pair", sa.String(length=10), nullable=False),
        sa.Column("date", sa.Date(), nullable=False),
        sa.Column("rate", sa.Numeric(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("pair", "date", name="uq_fx_rate_daily_pair_date"),
    )
    op.create_index(op.f("ix_fx_rate_daily_id"), "fx_rate_daily", ["id"])
    op.create_index(op.f("ix_fx_rate_daily_pair"), "fx_rate_daily", ["pair"])
    op.create_index(op.f("ix_fx_rate_daily_date"), "fx_rate_daily", ["date"])


def downgrade() -> None:
    op.drop_index(op.f("ix_fx_rate_daily_date"), table_name="fx_rate_daily")
    op.drop_index(op.f("ix_fx_rate_daily_pair"), table_name="fx_rate_daily")
    op.drop_index(op.f("ix_fx_rate_daily_id"), table_name="fx_rate_daily")
    op.drop_table("fx_rate_daily")
    op.drop_index(op.f("ix_lt_dividend_ex_date"), table_name="lt_dividend")
    op.drop_index(op.f("ix_lt_dividend_ticker"), table_name="lt_dividend")
    op.drop_index(op.f("ix_lt_dividend_id"), table_name="lt_dividend")
    op.drop_table("lt_dividend")
```

- [ ] **Step 8.7 (apply + check):** Run these against the dev database (`docker-compose exec backend …`, or locally with `DATABASE_URL` pointing at a reachable Postgres):

```bash
python -m alembic upgrade head
python -m alembic check
python -m alembic downgrade -1 && python -m alembic upgrade head
```

Expected: `upgrade` logs `Running upgrade e2f3a4b5c6d7 -> a7b8c9d0e1f2, add_lt_dividend_and_fx_rate_daily`, and `check` prints `No new upgrade operations detected.` Since CLAUDE.md prefers autogenerate, also cross-check against an autogenerated revision. The hand-written file must be moved out of `versions/` first, because otherwise Alembic refuses with `Target database is not up to date`:

```bash
python -m alembic downgrade -1                       # DB back to e2f3a4b5c6d7
mv app/alembic/versions/a7b8c9d0e1f2_add_lt_dividend_and_fx_rate_daily.py /tmp/
python -m alembic revision --autogenerate -m tmp_diff
diff <(sed -n '/^def upgrade/,/^def downgrade/p' app/alembic/versions/*_tmp_diff.py) \
     <(sed -n '/^def upgrade/,/^def downgrade/p' /tmp/a7b8c9d0e1f2_add_lt_dividend_and_fx_rate_daily.py)
rm app/alembic/versions/*_tmp_diff.py
mv /tmp/a7b8c9d0e1f2_add_lt_dividend_and_fx_rate_daily.py app/alembic/versions/
python -m alembic upgrade head && python -m alembic check
```

Two notes for this step. First, if the first `alembic check` above reports changes to tables
other than `lt_dividend`/`fx_rate_daily`, that is pre-existing dev-DB drift, not this migration;
CI's fresh-DB `alembic check` is the authoritative gate. Second, every upgrade/downgrade runs
`env.py`'s schema-doc generator, which can write an untracked repo-root `Docs/` directory
(capital D, separate from the committed `docs/`). Ignore or delete that directory and never
stage it.

Only cosmetic differences are acceptable: comments, index argument order, `unique=False`. A
missing or extra column, index or constraint means the hand-written file must be fixed to match
the models. If the autogenerate step reports changes to tables *other* than these two, that is
pre-existing dev-DB drift: ignore it for this diff, and do not commit the tmp file. The downgrade/upgrade round trip runs without errors. If no Postgres is reachable from the implement environment, record that in the commit message. CI runs `alembic upgrade head` and `alembic check` (`.github/workflows/ci.yml`).

- [ ] **Step 8.8:** Commit:

```bash
git add backend/app/models/lt_dividend.py backend/app/models/fx_rate_daily.py backend/app/models/__init__.py backend/app/alembic/versions/a7b8c9d0e1f2_add_lt_dividend_and_fx_rate_daily.py backend/tests/models/test_lt_models.py
git commit -m "feat(models): add lt_dividend and fx_rate_daily tables + migration (#912)"
```

---

## Task 9: `sync_stock_aggregates` gains a `provider` kwarg

**Files:** `backend/app/tasks/sync.py`, `backend/tests/tasks/test_sync_tasks.py`

- [ ] **Step 9.1 (failing test):** In `backend/tests/tasks/test_sync_tasks.py`, add this class directly after `class TestSyncStockAggregates` (before the `trigger_tweet_monitor` section comment):

```python
class TestSyncStockAggregatesProvider:
    """provider kwarg is threaded to StockDataService and recorded on stored rows."""

    _AGG = {
        "timestamp": datetime(2026, 10, 1, 4, 0, tzinfo=timezone.utc),
        "open": 35.0,
        "high": 35.5,
        "low": 34.8,
        "close": 35.2,
        "volume": 120000,
        "vwap": None,
        "transactions": None,
    }

    def _run(self, **task_kwargs):
        import app.tasks.sync as sync_module

        db = MagicMock()
        db.query.return_value.filter.return_value.delete = MagicMock(return_value=0)
        calls = []

        def _fake_get_aggregates(**kw):
            calls.append(kw)
            return [dict(self._AGG)]

        with (
            patch("app.tasks.sync.SessionLocal", return_value=db),
            patch(
                "app.services.stock_data.StockDataService.get_aggregates",
                side_effect=_fake_get_aggregates,
            ),
            patch("app.utils.session.classify_session", return_value=(False, False)),
        ):
            sync_module.sync_stock_aggregates.run(
                ticker="XIU.TO",
                from_date="2026-10-01",
                to_date="2026-10-01",
                timespan="day",
                **task_kwargs,
            )
        return db, calls

    def test_defaults_to_massive_and_labels_rows_polygon(self):
        db, calls = self._run()
        assert calls[0]["provider"] == "massive"
        assert db.bulk_save_objects.call_args[0][0][0].provider == "polygon"

    def test_yfinance_provider_threaded_and_labelled(self):
        db, calls = self._run(provider="yfinance")
        assert calls[0]["provider"] == "yfinance"
        assert db.bulk_save_objects.call_args[0][0][0].provider == "yfinance"
```

- [ ] **Step 9.2 (verify fail):**

```bash
python -m pytest tests/tasks/test_sync_tasks.py -k Provider -v --no-cov
```

Expected: `test_defaults_to_massive…` fails with `KeyError: 'provider'`, and `test_yfinance_provider…` fails with `TypeError: … unexpected keyword argument 'provider'`.

- [ ] **Step 9.3 (implement):** In `backend/app/tasks/sync.py`:

  - Directly above `@celery_app.task(bind=True, max_retries=3, name="app.tasks.sync_stock_aggregates")`, add:

```python
# DataProviderFactory name → StockAggregate.provider label. Massive rows have
# always been stored as "polygon"; every other provider stores its own name.
_AGGREGATE_PROVIDER_LABELS = {"massive": "polygon"}

```

  - Change the signature to add `provider` as the last parameter:

```python
def sync_stock_aggregates(
    self,
    ticker: str,
    from_date: str,
    to_date: str,
    multiplier: int = 1,
    timespan: str = "minute",
    adjusted: bool = True,
    sort: str = "asc",
    limit: int = 50000,
    provider: str = "massive",
):
    """
    Fetch and store aggregates for a specific ticker and date range.

    ``provider`` is the DataProviderFactory name to fetch from — callers pass the
    ticker's ``MonitoredStock.data_source`` ("yfinance" for .TO tickers).
    """
```

  - Change the first log line to include the provider:

```python
        logger.info(
            f"📊 Syncing aggregates for {ticker} {timespan}×{multiplier} "
            f"({from_date} to {to_date}) via {provider}"
        )
```

  - In the `StockDataService.get_aggregates(...)` call, add `provider=provider,` after `paginate=True,`.
  - Change the empty-result log from `f"📭 Polygon returned no bars for {ticker} "` to `f"📭 {provider} returned no bars for {ticker} "`.
  - Directly before `new_records = []`, add `provider_label = _AGGREGATE_PROVIDER_LABELS.get(provider, provider)`, and in the `StockAggregate(...)` constructor change `provider="polygon",` to `provider=provider_label,`.

- [ ] **Step 9.4 (verify pass):**

```bash
python -m pytest tests/tasks/test_sync_tasks.py -v --no-cov
```

Expected: all pass. The existing `TestSyncStockAggregates` is unchanged and still green, and the 2 new tests pass.

- [ ] **Step 9.5:** Commit:

```bash
git add backend/app/tasks/sync.py backend/tests/tasks/test_sync_tasks.py
git commit -m "feat(sync): route sync_stock_aggregates via a provider kwarg (#912)"
```

---

## Task 10: Route both orchestrator call sites by `data_source`

**Files:** `backend/app/services/universe_orchestrator.py`, `backend/tests/tasks/test_sync_stock_aggregates_routing.py`

- [ ] **Step 10.1 (failing test):** Create `backend/tests/tasks/test_sync_stock_aggregates_routing.py`:

```python
"""
Every sync_stock_aggregates call site routes by the ticker's data_source
(spec §3.4): universe sync-missing, universe sync, and POST /{ticker}/sync-missing.
Task dispatch is mocked — no broker, no provider calls.
"""

from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from app.utils.time import utc_now


def _stock(ticker, data_source, asset_class="stocks"):
    return SimpleNamespace(
        ticker=ticker,
        asset_class=asset_class,
        data_source=data_source,
        stock_metadata={},
    )


def _combo(timespan="day", multiplier=1):
    return SimpleNamespace(
        timespan=timespan,
        multiplier=multiplier,
        max_ts=utc_now() - timedelta(days=2),
    )


def _providers_by_ticker(task_mock):
    return {
        c.kwargs["ticker"]: c.kwargs["provider"] for c in task_mock.delay.call_args_list
    }


_STOCKS = [
    _stock("XIU.TO", "yfinance"),
    _stock("TLT", "massive"),
    _stock("OLD", None),  # pre-default NULL rows fall back to massive
]


class TestUniverseSyncMissing:
    def test_routes_each_ticker_by_data_source(self):
        from app.services.universe_orchestrator import sync_missing_aggregates

        db = MagicMock()
        db.query.return_value.filter.return_value.all.return_value = _STOCKS
        db.query.return_value.filter.return_value.group_by.return_value.all.return_value = [
            _combo()
        ]

        with (
            patch("app.tasks.sync_stock_aggregates") as task,
            patch("app.services.universe_orchestrator.redis_lib"),
        ):
            task.delay.return_value = MagicMock(id="t")
            result = sync_missing_aggregates(1, db)

        assert result["status"] == "accepted"
        assert _providers_by_ticker(task) == {
            "XIU.TO": "yfinance",
            "TLT": "massive",
            "OLD": "massive",
        }


class TestUniverseSyncAggregates:
    def test_routes_each_ticker_by_data_source(self):
        from app.services.universe_orchestrator import sync_aggregates

        db = MagicMock()
        db.query.return_value.filter.return_value.all.return_value = _STOCKS

        with (
            patch("app.tasks.sync_stock_aggregates") as task,
            patch("app.services.universe_orchestrator.redis_lib") as redis_mod,
        ):
            redis_mod.from_url.return_value.get.return_value = None
            task.delay.return_value = MagicMock(id="t")
            result = sync_aggregates(
                universe_id=1,
                from_date="2026-10-01",
                to_date="2026-10-31",
                multiplier=1,
                timespan="day",
                adjusted=True,
                sort="asc",
                limit=50000,
                db=db,
            )

        assert result["status"] == "accepted"
        assert _providers_by_ticker(task) == {
            "XIU.TO": "yfinance",
            "TLT": "massive",
            "OLD": "massive",
        }
```

(The router class is added in Task 11.)

- [ ] **Step 10.2 (verify fail):**

```bash
python -m pytest tests/tasks/test_sync_stock_aggregates_routing.py -v --no-cov
```

Expected: 2 failures with `KeyError: 'provider'`, because no call passes `provider=` yet.

- [ ] **Step 10.3 (implement — `sync_missing_aggregates`):** In `backend/app/services/universe_orchestrator.py`, directly after the line `stock_tickers = [s.ticker for s in stocks if s.asset_class != "futures"]`, add:

```python
    # Route each ticker to its provider (data_source: "massive" | "yfinance").
    stock_sources = {
        s.ticker: s.data_source or "massive"
        for s in stocks
        if s.asset_class != "futures"
    }
```

and in the `for ticker in stock_tickers:` loop, add `provider=stock_sources[ticker],` as the last kwarg of `sync_stock_aggregates.delay(...)` (after `timespan=combo.timespan,`).

- [ ] **Step 10.4 (implement — `sync_aggregates`):** In the same file, in the `else:` branch of `for stock in stocks:` inside `sync_aggregates`, add `provider=stock.data_source or "massive",` as the last kwarg of `sync_stock_aggregates.delay(...)` (after `limit=limit,`).

- [ ] **Step 10.5 (verify pass):** Re-run the Step 10.2 command. Expected: `2 passed`.

- [ ] **Step 10.6:** Commit:

```bash
git add backend/app/services/universe_orchestrator.py backend/tests/tasks/test_sync_stock_aggregates_routing.py
git commit -m "feat(universe): route aggregate sync by MonitoredStock.data_source (#912)"
```

---

## Task 11: Route `POST /{ticker}/sync-missing` by `data_source`

**Files:** `backend/app/routers/stocks.py`, `backend/tests/tasks/test_sync_stock_aggregates_routing.py`

- [ ] **Step 11.1 (failing test):** Append to `backend/tests/tasks/test_sync_stock_aggregates_routing.py`:

```python
class TestTickerSyncMissingEndpoint:
    def _call(self, monitored_row):
        from app.routers.stocks import sync_missing_stock_aggregates

        db = MagicMock()
        db.query.return_value.filter.return_value.first.return_value = monitored_row
        db.query.return_value.filter.return_value.group_by.return_value.all.return_value = [
            _combo()
        ]
        with (
            patch(
                "app.routers.stocks.StockDataService.is_futures_ticker",
                return_value=False,
            ),
            patch("app.tasks.sync_stock_aggregates") as task,
            patch("redis.from_url"),
        ):
            task.delay.return_value = MagicMock(id="t")
            sync_missing_stock_aggregates(ticker="xiu.to", db=db)
        return task

    def test_routes_by_monitored_stock_data_source(self):
        task = self._call(SimpleNamespace(data_source="yfinance"))
        assert _providers_by_ticker(task) == {"XIU.TO": "yfinance"}

    def test_unmonitored_ticker_defaults_to_massive(self):
        task = self._call(None)
        assert _providers_by_ticker(task) == {"XIU.TO": "massive"}
```

- [ ] **Step 11.2 (verify fail):**

```bash
python -m pytest tests/tasks/test_sync_stock_aggregates_routing.py -k Endpoint -v --no-cov
```

Expected: 2 failures with `KeyError: 'provider'`.

- [ ] **Step 11.3 (implement):** In `backend/app/routers/stocks.py`, in `sync_missing_stock_aggregates`, replace

```python
    else:
        # 2. Handle Stocks
        combos = (
```

with

```python
    else:
        # 2. Handle Stocks — route by the ticker's data_source (e.g. yfinance
        #    for .TO tickers) so manual resync matches the universe sync paths.
        stock = (
            db.query(MonitoredStock)
            .filter(
                MonitoredStock.ticker == ticker,
                MonitoredStock.asset_class != "futures",
            )
            .first()
        )
        provider = (stock.data_source if stock else None) or "massive"

        combos = (
```

and in that branch's `sync_stock_aggregates.delay(...)` call, add `provider=provider,` after `timespan=combo.timespan,`.

- [ ] **Step 11.4 (verify pass):**

```bash
python -m pytest tests/tasks/test_sync_stock_aggregates_routing.py -v --no-cov
```

Expected: `4 passed`.

- [ ] **Step 11.5:** Commit:

```bash
git add backend/app/routers/stocks.py backend/tests/tasks/test_sync_stock_aggregates_routing.py
git commit -m "feat(stocks): route POST /{ticker}/sync-missing by data_source (#912)"
```

---

## Task 12: `fetch_dividends` task + `lt_dividend` upsert

**Files:** `backend/app/tasks/long_term.py`, `backend/tests/tasks/test_fetch_dividends.py`

- [ ] **Step 12.1 (failing test):** Create `backend/tests/tasks/test_fetch_dividends.py`:

```python
"""
fetch_dividends — provider factory mocked, upserts asserted against the real
test PostgreSQL (`db` fixture; ON CONFLICT needs Postgres, not SQLite).
"""

from datetime import date
from unittest.mock import MagicMock, patch

import pytest

from app.exceptions import ProviderError
from app.models.lt_dividend import LtDividend


def _provider(rows_by_ticker=None, side_effect=None):
    p = MagicMock()
    if side_effect is not None:
        p.get_dividends.side_effect = side_effect
    else:
        p.get_dividends.side_effect = lambda t, f, to: list(rows_by_ticker.get(t, []))
    return p


def _run(db, provider, tickers, source):
    import app.tasks.long_term as lt

    with (
        patch("app.tasks.long_term.SessionLocal", return_value=db),
        patch.object(db, "close"),
        patch("app.tasks.long_term.DataProviderFactory") as factory,
    ):
        factory.get.return_value = provider
        result = lt.fetch_dividends.run(
            tickers=tickers, from_date="2026-09-01", to_date="2026-10-31", source=source
        )
    factory.get.assert_called_once_with(source)
    return result


def _rows(db, ticker):
    return db.query(LtDividend).filter(LtDividend.ticker == ticker).order_by(LtDividend.ex_date).all()


TLT_ROWS = [
    {"ex_date": date(2026, 9, 2), "cash_amount": 0.3241, "currency": "USD"},
    {"ex_date": date(2026, 10, 1), "cash_amount": 0.3302, "currency": "USD"},
]
XBB_ROWS = [{"ex_date": date(2026, 9, 24), "cash_amount": 0.065, "currency": "CAD"}]


def test_tlt_via_massive_produces_rows(db):
    result = _run(db, _provider({"TLT": TLT_ROWS}), ["TLT"], "massive")

    rows = _rows(db, "TLT")
    assert [r.ex_date for r in rows] == [date(2026, 9, 2), date(2026, 10, 1)]
    assert float(rows[0].cash_amount) == pytest.approx(0.3241)
    assert {(r.currency, r.source) for r in rows} == {("USD", "massive")}
    assert result["rows"] == 2


def test_xbb_to_via_yfinance_produces_rows(db):
    _run(db, _provider({"XBB.TO": XBB_ROWS}), ["XBB.TO"], "yfinance")

    rows = _rows(db, "XBB.TO")
    assert len(rows) == 1
    assert (rows[0].currency, rows[0].source) == ("CAD", "yfinance")


def test_rerun_is_idempotent_and_updates_amount(db):
    _run(db, _provider({"TLT": TLT_ROWS}), ["TLT"], "massive")
    revised = [dict(TLT_ROWS[0], cash_amount=0.33), TLT_ROWS[1]]
    _run(db, _provider({"TLT": revised}), ["TLT"], "massive")

    rows = _rows(db, "TLT")
    assert len(rows) == 2
    assert float(rows[0].cash_amount) == pytest.approx(0.33)


def test_duplicate_ex_date_in_one_response_does_not_fail(db):
    dup = [TLT_ROWS[0], dict(TLT_ROWS[0], cash_amount=0.4)]
    _run(db, _provider({"TLT": dup}), ["TLT"], "massive")
    assert len(_rows(db, "TLT")) == 1


def test_non_retryable_error_skips_ticker_and_continues(db):
    def _side_effect(ticker, f, t):
        if ticker == "BAD":
            raise ProviderError("breaker open", is_retryable=False, provider="massive")
        return list(TLT_ROWS)

    result = _run(db, _provider(side_effect=_side_effect), ["BAD", "TLT"], "massive")
    assert result["skipped"] == ["BAD"]
    assert len(_rows(db, "TLT")) == 2


def test_retryable_error_triggers_task_retry():
    import app.tasks.long_term as lt

    db = MagicMock()
    provider = _provider(
        side_effect=ProviderError("timeout", is_retryable=True, provider="yfinance")
    )

    def _retry_reraises(exc=None, **kw):
        raise exc

    with (
        patch("app.tasks.long_term.SessionLocal", return_value=db),
        patch("app.tasks.long_term.DataProviderFactory") as factory,
        patch.object(lt.fetch_dividends, "retry", side_effect=_retry_reraises) as retry,
    ):
        factory.get.return_value = provider
        with pytest.raises(ProviderError):
            lt.fetch_dividends.run(
                tickers=["XBB.TO"], from_date="2026-09-01", to_date="2026-10-31", source="yfinance"
            )
    retry.assert_called_once()
    db.rollback.assert_called_once()
    db.close.assert_called_once()
```

- [ ] **Step 12.2 (verify fail):**

```bash
python -m pytest tests/tasks/test_fetch_dividends.py -v --no-cov
```

Expected: every test errors with `ModuleNotFoundError: No module named 'app.tasks.long_term'`. DB tests need the test Postgres; `conftest.py` resolves it through `TEST_DATABASE_URL`, a running postgres probe, or testcontainers.

- [ ] **Step 12.3 (implement):** Create `backend/app/tasks/long_term.py`:

```python
"""
Long-term ETF investing data tasks (epic #902, LT-1b / #912).

Explicit-input fetchers that populate lt_dividend and fx_rate_daily.  They
never read the roster: the caller (LT-1c's backfill and nightly beat entries)
supplies the ticker list, source and date range.  Both tables upsert on their
natural key, so overlapping or repeated ranges are safe.
"""

import logging
from typing import Any, Dict, List

from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.core.celery_app import celery_app
from app.core.database import SessionLocal
from app.exceptions import ProviderError
from app.models.lt_dividend import LtDividend
from app.providers import DataProviderFactory

logger = logging.getLogger(__name__)


def upsert_dividends(
    db: Session, ticker: str, rows: List[Dict[str, Any]], source: str
) -> int:
    """Upsert provider dividend rows for one ticker on (ticker, ex_date)."""
    by_ex_date = {r["ex_date"]: r for r in rows}  # one row per key per statement
    if not by_ex_date:
        return 0
    stmt = pg_insert(LtDividend).values(
        [
            {
                "ticker": ticker,
                "ex_date": r["ex_date"],
                "cash_amount": r["cash_amount"],
                "currency": r["currency"],
                "source": source,
            }
            for r in by_ex_date.values()
        ]
    )
    stmt = stmt.on_conflict_do_update(
        constraint="uq_lt_dividend_ticker_ex_date",
        set_={
            "cash_amount": stmt.excluded.cash_amount,
            "currency": stmt.excluded.currency,
            "source": stmt.excluded.source,
        },
    )
    db.execute(stmt)
    return len(by_ex_date)


@celery_app.task(bind=True, max_retries=3, name="app.tasks.fetch_dividends")
def fetch_dividends(
    self, tickers: List[str], from_date: str, to_date: str, source: str
) -> Dict[str, Any]:
    """
    Fetch and upsert dividend rows for `tickers` from `source`
    ("massive" → Polygon /v3/reference/dividends, "yfinance" → Yahoo).

    A non-retryable ProviderError (open breaker, plan limit) skips that ticker;
    any other failure retries the whole task — safe because upserts are idempotent.
    """
    provider = DataProviderFactory.get(source)
    db: Session = SessionLocal()
    try:
        total = 0
        skipped: List[str] = []
        for ticker in tickers:
            try:
                rows = provider.get_dividends(ticker, from_date, to_date)
            except ProviderError as e:
                if e.is_retryable:
                    raise
                logger.warning(f"⏭️ Dividends skipped for {ticker} via {source}: {e}")
                skipped.append(ticker)
                continue
            total += upsert_dividends(db, ticker, rows, source)
            db.commit()
        logger.info(
            f"✅ Dividends via {source}: {total} row(s) upserted for "
            f"{len(tickers) - len(skipped)}/{len(tickers)} ticker(s) "
            f"({from_date} to {to_date})"
        )
        return {"source": source, "tickers": len(tickers), "rows": total, "skipped": skipped}
    except Exception as e:
        logger.error(f"❌ Error fetching dividends via {source}: {e}")
        db.rollback()
        raise self.retry(exc=e, countdown=60)
    finally:
        db.close()
```

(No `datetime` import yet. Task 13 adds `from datetime import date, datetime, timedelta`
together with the code that uses it, so ruff's F401 check and the pre-commit `ruff --fix` hook
never see an unused import.)

- [ ] **Step 12.4 (verify pass):**

```bash
ruff check app/tasks/long_term.py && python -m pytest tests/tasks/test_fetch_dividends.py -v --no-cov
```

Expected: ruff `All checks passed!`, `6 passed`.

- [ ] **Step 12.5:** Commit:

```bash
git add backend/app/tasks/long_term.py backend/tests/tasks/test_fetch_dividends.py
git commit -m "feat(tasks): add fetch_dividends task upserting lt_dividend (#912)"
```

---

## Task 13: `fetch_fx_rate` task + `fx_rate_daily` upsert

**Files:** `backend/app/tasks/long_term.py`, `backend/tests/tasks/test_fetch_fx_rate.py`

- [ ] **Step 13.1 (failing test):** Create `backend/tests/tasks/test_fetch_fx_rate.py`:

```python
"""
fetch_fx_rate — yfinance CAD=X primary, Polygon C:USDCAD fallback.  Providers
mocked; upserts asserted against the real test PostgreSQL (`db` fixture).
"""

from datetime import date, datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest

from app.exceptions import ProviderError
from app.models.fx_rate_daily import FxRateDaily

OCT_2026_WEEKDAYS = [
    date(2026, 10, d) for d in range(1, 32) if date(2026, 10, d).weekday() < 5
]


def _bars(days, utc_offset_hours=0, base=1.38):
    """Daily bars stamped at local midnight expressed in UTC (Yahoo FX: London)."""
    return [
        {
            "timestamp": datetime(d.year, d.month, d.day, tzinfo=timezone.utc)
            - timedelta(hours=utc_offset_hours),
            "open": base, "high": base, "low": base,
            "close": round(base + i * 0.001, 4),
            "volume": 0, "vwap": None, "transactions": None,
        }
        for i, d in enumerate(days)
    ]


def _run(db, yf_provider, massive_provider, pair="USDCAD"):
    import app.tasks.long_term as lt

    providers = {"yfinance": yf_provider, "massive": massive_provider}
    with (
        patch("app.tasks.long_term.SessionLocal", return_value=db),
        patch.object(db, "close"),
        patch("app.tasks.long_term.DataProviderFactory") as factory,
    ):
        factory.get.side_effect = lambda name: providers[name]
        return lt.fetch_fx_rate.run(pair=pair, from_date="2026-10-01", to_date="2026-10-31")


def _stored(db):
    return db.query(FxRateDaily).filter(FxRateDaily.pair == "USDCAD").order_by(FxRateDaily.date).all()


def test_one_month_via_yfinance_produces_a_row_per_trading_day(db):
    """Done-when: FX for a one-month range produces rows."""
    yf_p, massive_p = MagicMock(), MagicMock()
    # BST: London midnight = 23:00 UTC the previous day — dates must not shift.
    yf_p.get_bars.return_value = _bars(OCT_2026_WEEKDAYS, utc_offset_hours=1)

    result = _run(db, yf_p, massive_p)

    yf_p.get_bars.assert_called_once_with(
        symbol="CAD=X", timespan="day", multiplier=1,
        from_date="2026-10-01", to_date="2026-10-31",
    )
    massive_p.get_bars.assert_not_called()
    rows = _stored(db)
    assert [r.date for r in rows] == OCT_2026_WEEKDAYS
    assert float(rows[0].rate) == pytest.approx(1.38)
    assert result == {"pair": "USDCAD", "source": "yfinance", "rows": len(OCT_2026_WEEKDAYS)}


def test_yfinance_provider_error_falls_back_to_polygon(db):
    yf_p, massive_p = MagicMock(), MagicMock()
    yf_p.get_bars.side_effect = ProviderError(
        "breaker open", is_retryable=False, provider="yfinance"
    )
    massive_p.get_bars.return_value = _bars(OCT_2026_WEEKDAYS[:5], utc_offset_hours=-5)

    result = _run(db, yf_p, massive_p)

    assert massive_p.get_bars.call_args.kwargs["symbol"] == "C:USDCAD"
    assert result["source"] == "massive"
    assert [r.date for r in _stored(db)] == OCT_2026_WEEKDAYS[:5]


def test_empty_yfinance_response_falls_back_to_polygon(db):
    yf_p, massive_p = MagicMock(), MagicMock()
    yf_p.get_bars.return_value = []
    massive_p.get_bars.return_value = _bars(OCT_2026_WEEKDAYS[:3])

    result = _run(db, yf_p, massive_p)
    assert result["source"] == "massive"
    assert len(_stored(db)) == 3


def test_rerun_is_idempotent(db):
    yf_p, massive_p = MagicMock(), MagicMock()
    yf_p.get_bars.return_value = _bars(OCT_2026_WEEKDAYS)
    _run(db, yf_p, massive_p)
    yf_p.get_bars.return_value = _bars(OCT_2026_WEEKDAYS, base=1.40)
    _run(db, yf_p, massive_p)

    rows = _stored(db)
    assert len(rows) == len(OCT_2026_WEEKDAYS)
    assert float(rows[0].rate) == pytest.approx(1.40)


def test_both_sources_failing_retryably_triggers_retry():
    import app.tasks.long_term as lt

    yf_p, massive_p = MagicMock(), MagicMock()
    yf_p.get_bars.side_effect = ProviderError("down", is_retryable=True, provider="yfinance")
    massive_p.get_bars.side_effect = ProviderError("down", is_retryable=True, provider="massive")

    def _retry_reraises(exc=None, **kw):
        raise exc

    with (
        patch("app.tasks.long_term.DataProviderFactory") as factory,
        patch.object(lt.fetch_fx_rate, "retry", side_effect=_retry_reraises) as retry,
    ):
        factory.get.side_effect = lambda name: {"yfinance": yf_p, "massive": massive_p}[name]
        with pytest.raises(ProviderError):
            lt.fetch_fx_rate.run(pair="USDCAD", from_date="2026-10-01", to_date="2026-10-31")
    retry.assert_called_once()


def test_both_sources_failing_non_retryably_returns_zero_rows():
    import app.tasks.long_term as lt

    yf_p, massive_p = MagicMock(), MagicMock()
    yf_p.get_bars.side_effect = ProviderError("open", is_retryable=False, provider="yfinance")
    massive_p.get_bars.side_effect = ProviderError("open", is_retryable=False, provider="massive")

    with patch("app.tasks.long_term.DataProviderFactory") as factory:
        factory.get.side_effect = lambda name: {"yfinance": yf_p, "massive": massive_p}[name]
        result = lt.fetch_fx_rate.run(pair="USDCAD", from_date="2026-10-01", to_date="2026-10-31")
    assert result == {"pair": "USDCAD", "source": None, "rows": 0}


def test_unsupported_pair_raises_value_error():
    import app.tasks.long_term as lt

    with pytest.raises(ValueError, match="unsupported pair"):
        lt.fetch_fx_rate.run(pair="EURJPY", from_date="2026-10-01", to_date="2026-10-31")


def test_bar_date_recovers_session_date_across_offsets():
    from app.tasks.long_term import _bar_date

    utc = timezone.utc
    assert _bar_date(datetime(2026, 9, 30, 23, 0, tzinfo=utc)) == date(2026, 10, 1)  # London BST
    assert _bar_date(datetime(2026, 10, 1, 0, 0, tzinfo=utc)) == date(2026, 10, 1)   # UTC midnight
    assert _bar_date(datetime(2026, 10, 1, 4, 0, tzinfo=utc)) == date(2026, 10, 1)   # NY/Toronto EDT
```

- [ ] **Step 13.2 (verify fail):**

```bash
python -m pytest tests/tasks/test_fetch_fx_rate.py -v --no-cov
```

Expected: every test fails with `AttributeError: module 'app.tasks.long_term' has no attribute 'fetch_fx_rate'` (or `_bar_date`).

- [ ] **Step 13.3 (implement):** In `backend/app/tasks/long_term.py`:

  - Add `from datetime import date, datetime, timedelta` directly after `import logging`, and add `from app.models.fx_rate_daily import FxRateDaily` directly above the `LtDividend` import (isort order).
  - Below `logger = logging.getLogger(__name__)`, add:

```python

# pair → (yfinance symbol [primary], Polygon forex symbol [fallback]).
# Both quote CAD per 1 USD, matching the "USDCAD" pair convention.
FX_SYMBOLS: Dict[str, tuple[str, str]] = {"USDCAD": ("CAD=X", "C:USDCAD")}


def _bar_date(ts: datetime) -> date:
    """
    Session date of a daily bar.  Providers stamp day bars at the session's
    local midnight expressed in UTC (Polygon: 04:00/05:00 UTC; Yahoo FX: London
    midnight, i.e. 23:00 UTC the previous day under BST).  Rounding to the
    nearest UTC midnight recovers the session date for any offset within ±12 h.
    """
    return (ts + timedelta(hours=12)).date()


def upsert_fx_rates(db: Session, pair: str, rates: Dict[date, float]) -> int:
    """Upsert daily rates for one pair on (pair, date)."""
    if not rates:
        return 0
    stmt = pg_insert(FxRateDaily).values(
        [{"pair": pair, "date": d, "rate": rate} for d, rate in rates.items()]
    )
    stmt = stmt.on_conflict_do_update(
        constraint="uq_fx_rate_daily_pair_date",
        set_={"rate": stmt.excluded.rate},
    )
    db.execute(stmt)
    return len(rates)
```

  - Append at the end of the file:

```python


@celery_app.task(bind=True, max_retries=3, name="app.tasks.fetch_fx_rate")
def fetch_fx_rate(self, pair: str, from_date: str, to_date: str) -> Dict[str, Any]:
    """
    Fetch and upsert daily FX rows for `pair` (e.g. "USDCAD"), using each day
    bar's close as that day's rate.

    yfinance (`CAD=X`) is primary.  Polygon forex (`C:USDCAD`) is the fallback
    when yfinance raises a ProviderError (including an open YFINANCE_BREAKER)
    or returns no rows.  The fallback is internal — not a caller parameter.
    """
    pair = pair.upper()
    if pair not in FX_SYMBOLS:
        raise ValueError(
            f"fetch_fx_rate: unsupported pair '{pair}' (supported: {sorted(FX_SYMBOLS)})"
        )
    yf_symbol, polygon_symbol = FX_SYMBOLS[pair]
    bar_kwargs = dict(timespan="day", multiplier=1, from_date=from_date, to_date=to_date)

    source = "yfinance"
    try:
        bars = DataProviderFactory.get("yfinance").get_bars(symbol=yf_symbol, **bar_kwargs)
    except ProviderError as e:
        logger.warning(f"⚠️ yfinance {yf_symbol} failed ({e}) — falling back to Polygon")
        bars = []

    if not bars:
        source = "massive"
        try:
            bars = DataProviderFactory.get("massive").get_bars(
                symbol=polygon_symbol, **bar_kwargs
            )
        except ProviderError as e:
            if e.is_retryable:
                raise self.retry(exc=e, countdown=60)
            logger.error(f"❌ {pair}: both yfinance and Polygon unavailable: {e}")
            return {"pair": pair, "source": None, "rows": 0}

    rates = {
        _bar_date(b["timestamp"]): float(b["close"]) for b in bars if b.get("close")
    }

    db: Session = SessionLocal()
    try:
        count = upsert_fx_rates(db, pair, rates)
        db.commit()
    except Exception as e:
        logger.error(f"❌ Error storing {pair} FX rates: {e}")
        db.rollback()
        raise self.retry(exc=e, countdown=60)
    finally:
        db.close()

    logger.info(f"✅ {pair} via {source}: {count} rate(s) upserted ({from_date} to {to_date})")
    return {"pair": pair, "source": source, "rows": count}
```

- [ ] **Step 13.4 (verify pass):**

```bash
ruff check app/tasks/long_term.py && python -m pytest tests/tasks/test_fetch_fx_rate.py tests/tasks/test_fetch_dividends.py -v --no-cov
```

Expected: ruff `All checks passed!`, `14 passed` (8 FX + 6 dividends).

- [ ] **Step 13.5:** Commit:

```bash
git add backend/app/tasks/long_term.py backend/tests/tasks/test_fetch_fx_rate.py
git commit -m "feat(tasks): add fetch_fx_rate (yfinance CAD=X, Polygon C:USDCAD fallback) (#912)"
```

---

## Task 14: Register the new tasks with Celery

**Files:** `backend/app/tasks/__init__.py`, `backend/tests/tasks/test_package_exports.py`

- [ ] **Step 14.1 (failing test):** In `backend/tests/tasks/test_package_exports.py`:
  - In `PUBLIC_TASKS`, after the `"embed_generated_narrative_source",` line, add:

```python
    # long_term
    "fetch_dividends",
    "fetch_fx_rate",
```

  - In `SUBMODULE_TASKS`, after the `"app.tasks.embeddings": [...]` entry, add:

```python
    "app.tasks.long_term": [
        "fetch_dividends",
        "fetch_fx_rate",
    ],
```

- [ ] **Step 14.2 (verify fail):**

```bash
python -m pytest tests/tasks/test_package_exports.py -v --no-cov
```

Expected: `test_public_tasks_importable_from_top_level` and `test_celery_task_names_preserved` fail with `AssertionError: app.tasks.fetch_dividends not found` (and an `AttributeError` for the name check).

- [ ] **Step 14.3 (implement):** In `backend/app/tasks/__init__.py`:
  - After the `from app.tasks.explanations import backfill_scanner_explanations` line, add:

```python
from app.tasks.long_term import fetch_dividends, fetch_fx_rate
```

  - In `__all__`, after the `"backfill_scanner_explanations",` entry, add:

```python
    # long_term
    "fetch_dividends",
    "fetch_fx_rate",
```

- [ ] **Step 14.4 (verify pass):** Re-run the Step 14.2 command. Expected: all pass.

- [ ] **Step 14.5:** Commit:

```bash
git add backend/app/tasks/__init__.py backend/tests/tasks/test_package_exports.py
git commit -m "feat(tasks): export fetch_dividends/fetch_fx_rate for Celery discovery (#912)"
```

---

## Task 15: Full verification + live validation

**Files:** none (verification only; commit only if a fix is needed)

- [ ] **Step 15.1 (lint + full suite):**

```bash
ruff check . && python -m pytest
```

Expected: ruff `All checks passed!`, and pytest is all green with coverage at or above 60% (the
`--cov-fail-under=60` gate in `addopts`). New tests: 3 breaker, 2 base, 13 yfinance, 6 massive,
3 model, 2 sync provider, 4 routing, 6 dividends, 8 FX.

- [ ] **Step 15.2 (rebuild + reload; requirements changed):** From the repo root. Every service
that installs `backend/requirements.txt` and imports `app.tasks` / `app.providers` needs the new
image: under the dev override's `./backend:/app:ro` bind-mount, a stale image would fail on
`import yfinance`.

```bash
docker-compose build backend celery-worker celery-beat flower live-scanner forecast-worker
docker-compose up -d backend celery-worker celery-beat flower live-scanner forecast-worker
docker-compose logs backend --tail=10
docker-compose exec backend python -m alembic upgrade head
```

**Inside the Dark Factory container**, `compose build` / `up --build` over the docker-socket
proxy returns 403 (memory: dark-factory-ops `[PATTERN]`). Build with
`docker buildx build --builder remote tcp://buildkit:1234 --load -t <image> backend/` instead, or,
if no stack is reachable, skip Steps 15.2–15.4 and say so explicitly in the PR body. CI's test,
`alembic upgrade head` and `alembic check` jobs still gate the change. The Docker images are
`python:3.12-slim`; cp312/abi3 wheels for `curl_cffi 0.17.0` and `lxml 6.1.3` were confirmed
at plan time.

Expected: the backend log shows a clean startup (`Application startup complete`) with no
`ModuleNotFoundError: yfinance`, and `alembic upgrade head` reports
`Running upgrade … -> a7b8c9d0e1f2` (or no-op if already applied).

- [ ] **Step 15.3 (curl the changed surfaces):** Use whatever auth cookie your local stack needs (see DEVELOPMENT.md):

```bash
curl -s http://localhost:8000/api/v1/futures/providers | python -m json.tool
curl -s -X POST http://localhost:8000/api/v1/stocks/AAPL/sync-missing | python -m json.tool
```

Expected: the providers list contains `{"name": "yfinance", "classes": ["stocks", "forex"], "available": true, "status_message": "Ready", ...}`. The sync-missing call returns `"status": "accepted"` (or `"skipped"`) as before, and `docker-compose logs celery-worker --tail=20` shows `Syncing aggregates for AAPL … via massive`.

- [ ] **Step 15.4 (live smoke + confirm spec §5 currency assumption):** This hits Yahoo/Polygon once each. Run it in the dev container, never in tests:

```bash
docker-compose exec backend python - <<'EOF'
from app.providers import DataProviderFactory as F
yf = F.get("yfinance")
bars = yf.get_bars("XIU.TO", "day", 1, "2026-10-01", "2026-10-31")
print("XIU.TO bars:", len(bars), bars[0] if bars else None)
divs = yf.get_dividends("XBB.TO", "2025-11-01", "2026-10-31")
print("XBB.TO dividends:", divs[:2])
import yfinance
print("raw dividends type:", type(yfinance.Ticker("XBB.TO").dividends))  # Series vs DataFrame-with-currency
fx = yf.get_bars("CAD=X", "day", 1, "2026-10-01", "2026-10-31")
print("CAD=X:", len(fx), fx[0]["timestamp"] if fx else None)
EOF
docker-compose exec backend python -c "from app.tasks.long_term import fetch_fx_rate as t; print(t.run(pair='USDCAD', from_date='2026-10-01', to_date='2026-10-31'))"
```

Expected: about 22 XIU.TO bars with UTC-aware timestamps at 04:00 UTC, XBB.TO dividend rows with
`currency` `CAD`, and about 22 CAD=X bars. The task prints
`{'pair': 'USDCAD', 'source': 'yfinance', 'rows': ~22}`. Also check that the output has no yfinance
tz/cookie-cache permission warnings: the image runs as `appuser`, and yfinance writes its cache
under the platformdirs user cache dir. If warnings appear, record them in the PR body; this slice
does not need a fix. Put the observed results in the PR body
(this answers spec §5 open question 1). If Yahoo returns dividends as a DataFrame with a `currency`
column, say so there too.

- [ ] **Step 15.5:** If any step above needed a fix, commit it:

```bash
git add -A backend/ ENV_VARIABLES.md
git commit -m "fix: address LT-1b verification findings (#912)"
```

---

## Self-review checklist (done at plan time)

- [x] `**Issue:** #912` line present under the title.
- [x] Every spec requirement maps to a task: R1 (Tasks 4–6), R2 / §3.4 (Tasks 9–11), R3 (Tasks 12–13), R4 (Tasks 8, 12, 13), R5 (Task 7), R6 (Task 1), R7 (all test steps mock `yf.Ticker` or `RESTClient`, or the provider factory), R8 done-when (`test_get_bars_through_provider_abstraction`, `test_tlt_via_massive_produces_rows`, `test_xbb_to_via_yfinance_produces_rows`, `test_one_month_via_yfinance_produces_a_row_per_trading_day`), §3.7 breaker + settings + docs (Task 2).
- [x] No placeholders. Each code step has the full code and each command has its expected output.
- [x] Out of scope, as the spec says: no beat schedule entries, no roster (`lt_etf`) queries, no backfill run, no data-health checks, no FX/total-return consumers.
