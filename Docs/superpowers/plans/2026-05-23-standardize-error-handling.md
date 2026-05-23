# Standardize Error Handling Conventions Across Modules

**Date:** 2026-05-23
**Issue:** #64
**Branch:** refine/issue-64-standardize-error-handling-conventions-a
**Spec:** `Docs/superpowers/specs/2026-05-23-standardize-error-handling-conventions-design.md`

---

## Goal

Replace three incompatible error-handling patterns — `{"status": "error"}` dict returns in `StockDataService`, raw `RuntimeError` raises in `FuturesDataService`, and silent `except Exception: pass` swallowing in `ScannerService` — with a typed exception hierarchy. Every service boundary raises `ScanError`, `DataFetchError`, or `ProviderError` with structured `**context` fields. Celery retries by checking `is_retryable`; FastAPI maps errors to consistent HTTP codes; Seq gains filterable structured properties.

## Architecture

Single-pass migration, bottom-up through the call stack:

1. Define exception types → 2. Migrate providers → 3. Migrate StockDataService + callers → 4. Migrate FuturesDataService + callers → 5. Add `failed_tickers` DB column → 6. Migrate ScannerService per-ticker loops → 7. Normalize DiscoveryService → 8. Register FastAPI handler

## Tech Stack

- Python 3.11+, SQLAlchemy 2.0 (sync ORM), FastAPI, Celery, pytest
- PostgreSQL JSONB for the `failed_tickers` column via `sqlalchemy.dialects.postgresql.JSONB`

---

## File Structure

| File | Change |
|------|--------|
| `backend/app/exceptions.py` | **NEW** — `MarketHawkError`, `ScanError`, `DataFetchError`, `ProviderError` |
| `backend/app/providers/ibkr.py` | Replace `ConnectionError`/`ValueError` raises with `ProviderError` |
| `backend/app/providers/massive.py` | Replace silent swallow + return-empty on API failure with `ProviderError` |
| `backend/app/services/stock_data.py` | Fix `is_available()` tuple guard; replace dict error returns with `DataFetchError`; wrap `ProviderError` in `DataFetchError` |
| `backend/app/routers/stocks.py` | Catch `DataFetchError` before generic `Exception` |
| `backend/app/tasks.py` | `sync_futures_aggregates` task: catch `ProviderError` by name; `run_universe_scan`: pass `scanner_run=run` to scan methods |
| `backend/app/services/futures_data.py` | Replace `RuntimeError` raises with `ProviderError` |
| `backend/app/models/scanner_run.py` | Add `failed_tickers = Column(JSONB, nullable=True)` |
| `backend/app/alembic/versions/<hash>_add_failed_tickers_to_scanner_runs.py` | Alembic migration |
| `backend/app/services/scanner.py` | Add `scanner_run=None` param to scan methods; per-ticker `except Exception` → collect `failed_tickers`; `except Exception: pass` → named catches with logging |
| `backend/app/services/discovery_service.py` | All `except Exception` blocks explicitly re-raise or swallow with comment |
| `backend/app/main.py` | Register `MarketHawkError` handler before `Exception` catch-all |
| `backend/tests/test_exceptions.py` | **NEW** — unit tests for exception hierarchy |
| `backend/tests/providers/test_provider_errors.py` | **NEW** — provider `ProviderError` raise tests |
| `backend/tests/services/test_error_conventions.py` | **NEW** — service-level error convention tests |

---

## Task 1: Define the Exception Hierarchy

**Files:** `backend/app/exceptions.py` (new), `backend/tests/test_exceptions.py` (new)

### TDD Steps

**Write the failing test first:**

```python
# backend/tests/test_exceptions.py
import pytest
from app.exceptions import MarketHawkError, ScanError, DataFetchError, ProviderError


def test_markethawk_error_defaults():
    e = MarketHawkError("something failed")
    assert str(e) == "something failed"
    assert e.is_retryable is False
    assert e.context == {}


def test_markethawk_error_retryable_with_context():
    e = DataFetchError("rate limited", is_retryable=True, provider="polygon", symbol="TSLA")
    assert e.is_retryable is True
    assert e.context == {"provider": "polygon", "symbol": "TSLA"}


def test_subclasses_are_markethawk_errors():
    assert issubclass(ScanError, MarketHawkError)
    assert issubclass(DataFetchError, MarketHawkError)
    assert issubclass(ProviderError, MarketHawkError)


def test_scan_error_context_fields():
    e = ScanError("enrichment failed", scanner_type="pre_market", ticker="AAPL", scan_id=42)
    assert e.context["scanner_type"] == "pre_market"
    assert e.context["ticker"] == "AAPL"
    assert e.context["scan_id"] == 42


def test_provider_error_retryable():
    e = ProviderError(
        "503 from Polygon", is_retryable=True,
        provider="polygon", endpoint="aggs", status_code=503,
    )
    assert e.is_retryable is True
    assert e.context["status_code"] == 503


def test_catch_subclass_as_base():
    with pytest.raises(MarketHawkError):
        raise DataFetchError("ticker not found", is_retryable=False, provider="polygon", symbol="ZZZ")
```

**Verify failure:**
```bash
cd /workspace/markethawk/backend
python -m pytest tests/test_exceptions.py -v 2>&1 | tail -5
# Expected: ImportError — app.exceptions does not exist yet
```

**Implement `backend/app/exceptions.py`:**

```python
class MarketHawkError(Exception):
    def __init__(self, message: str, is_retryable: bool = False, **context):
        super().__init__(message)
        self.is_retryable = is_retryable
        self.context = context


class ScanError(MarketHawkError):
    pass


class DataFetchError(MarketHawkError):
    pass


class ProviderError(MarketHawkError):
    pass
```

**Verify pass:**
```bash
cd /workspace/markethawk/backend
python -m pytest tests/test_exceptions.py -v
# Expected: 6 passed
```

**Commit:**
```bash
git add backend/app/exceptions.py backend/tests/test_exceptions.py
git commit -m "feat(#64): define typed exception hierarchy — MarketHawkError, ScanError, DataFetchError, ProviderError"
```

---

## Task 2: Migrate Provider Layer — ibkr.py and massive.py

**Files:** `backend/app/providers/ibkr.py`, `backend/app/providers/massive.py`
**Test:** `backend/tests/providers/test_provider_errors.py` (new)

### Background

`ibkr.py` raises `ConnectionError` (line 400 — clientId rejected after `connect()` attempt) and `ValueError` (line 460 — `_resolve_bar_size()` with unsupported timespan; line 669 — bad bar date) at public method boundaries. `massive.py`'s `get_historical_bars()` (the public method on `MassiveDataProvider`) catches API exceptions at line 134 and silently returns `[]`, making it impossible for callers to distinguish "no bars for this range" from "Polygon returned a 429".

### TDD Steps

**Write the failing test:**

```python
# backend/tests/providers/test_provider_errors.py
import pytest
import asyncio
from unittest.mock import MagicMock, patch, AsyncMock
from app.exceptions import ProviderError


class TestIBKRProviderErrors:
    def test_resolve_bar_size_raises_provider_error_for_unknown_timespan(self):
        from app.providers.ibkr import IBKRDataProvider
        with pytest.raises(ProviderError) as exc_info:
            IBKRDataProvider._resolve_bar_size("nanosecond", 1)
        assert exc_info.value.is_retryable is False
        assert exc_info.value.context["provider"] == "ibkr"

    @pytest.mark.asyncio
    async def test_connect_raises_provider_error_when_client_id_rejected(self):
        from app.providers.ibkr import IBKRDataProvider

        provider = IBKRDataProvider.__new__(IBKRDataProvider)
        provider._ib = None
        provider._connected = False

        mock_ib = MagicMock()
        mock_ib.connectAsync = AsyncMock()
        mock_ib.isConnected.return_value = False

        with patch("app.providers.ibkr.IB", return_value=mock_ib), \
             patch("app.providers.ibkr.IB_INSYNC_AVAILABLE", True), \
             patch("asyncio.sleep", AsyncMock()):
            with pytest.raises(ProviderError) as exc_info:
                await provider.connect(max_retries=1)

        assert exc_info.value.is_retryable is True
        assert exc_info.value.context["provider"] == "ibkr"


class TestMassiveProviderErrors:
    def test_get_historical_bars_raises_provider_error_on_api_failure(self):
        from app.providers.massive import MassiveDataProvider
        provider = MassiveDataProvider.__new__(MassiveDataProvider)
        mock_client = MagicMock()
        mock_client.get_aggs.side_effect = Exception("429 Too Many Requests")
        provider._client = mock_client
        with pytest.raises(ProviderError) as exc_info:
            # signature: (symbol, timespan, multiplier, from_date, to_date)
            provider.get_historical_bars("AAPL", "minute", 1, "2026-01-01", "2026-01-02")
        assert exc_info.value.is_retryable is True
        assert exc_info.value.context["provider"] == "polygon"
        assert exc_info.value.context["symbol"] == "AAPL"

    def test_get_historical_bars_returns_empty_list_when_client_not_initialized(self):
        """Uninitialized-client path is a config failure — returns [] so callers outside
        refresh_stock_data are not broken. Only API call failures raise ProviderError."""
        from app.providers.massive import MassiveDataProvider
        provider = MassiveDataProvider.__new__(MassiveDataProvider)
        provider._client = None
        result = provider.get_historical_bars("AAPL", "minute", 1, "2026-01-01", "2026-01-02")
        assert result == []
```

**Verify failure:**
```bash
cd /workspace/markethawk/backend
python -m pytest tests/providers/test_provider_errors.py -v 2>&1 | tail -10
# Expected: test_resolve_bar_size — ValueError raised, not ProviderError
#           test_connect — ConnectionError raised, not ProviderError
#           test_get_historical_bars_* — returns [] instead of raising
```

**Implement — `backend/app/providers/ibkr.py`:**

Add import at top of file:
```python
from app.exceptions import ProviderError
```

Replace line 400 (`raise ConnectionError(...)`) with:
```python
raise ProviderError(
    f"clientId={client_id} rejected — {reason}",
    is_retryable=True,
    provider="ibkr",
    endpoint="connect",
)
```

Also add `except ProviderError: raise` **before** the `except Exception as e:` block at line 412 (which is the catch-all inside the retry loop). Without this, the `ProviderError` raised at line 400 is immediately caught by line 412 and swallowed before it can propagate out of `connect()`:
```python
except ProviderError:
    raise  # propagate typed domain error — caller decides whether to retry
except Exception as e:
    # existing retry-backoff logic unchanged
    self._ib = None
    self._connected = False
    ...
```

Replace line 460 (`raise ValueError(...)`) with:
```python
raise ProviderError(
    f"IBKRDataProvider: Unsupported timespan '{timespan}'. "
    f"Valid options: {list(TIMESPAN_TO_IBKR.keys())}",
    is_retryable=False,
    provider="ibkr",
    endpoint="_resolve_bar_size",
)
```

Replace line 669 (`raise ValueError(f"IBKRDataProvider: Cannot parse bar date: {bar_date!r}")`) with:
```python
raise ProviderError(
    f"IBKRDataProvider: Cannot parse bar date: {bar_date!r}",
    is_retryable=False,
    provider="ibkr",
    endpoint="_parse_bar_date",
)
```

**Implement — `backend/app/providers/massive.py`:**

Add import at top of file:
```python
from app.exceptions import ProviderError
```

`get_historical_bars()` begins at line 63. The client not-initialized guard (lines 84–86) currently returns `[]`. **Do not change this guard to raise** — many callers outside `refresh_stock_data` (e.g., `scanner.py`, `liquidity_hunt.py`, `tasks.py`) call `get_historical_bars` or `get_aggregates` directly and tolerate an empty return. An uninitialized client is a configuration failure, not an API failure; the spec targets API call failures only. Leave the guard as-is:
```python
if not self._client:
    logger.error("MassiveDataProvider: client not initialized — POLYGON_API_KEY may be missing")
    return []
```

Replace lines 134–141 (`except Exception as e: ... return []`) in `get_historical_bars`:
```python
except Exception as e:
    raise ProviderError(
        f"Polygon fetch failed for {symbol} {timespan}×{multiplier} ({from_date} → {to_date}): {e}",
        is_retryable=True,
        provider="polygon",
        endpoint="get_historical_bars",
        symbol=symbol,
        timespan=timespan,
    ) from e
```

**Note:** `get_ticker_details`, `get_snapshot_all`, and `get_snapshot_price` are enrichment helpers where "no data" is a valid outcome — their `return {}` / `return []` / `return None` on failure is intentional and unchanged.

**Verify pass:**
```bash
cd /workspace/markethawk/backend
python -m pytest tests/providers/test_provider_errors.py -v
# Expected: 4 passed
```

**Commit:**
```bash
git add backend/app/providers/ibkr.py backend/app/providers/massive.py \
        backend/tests/providers/test_provider_errors.py
git commit -m "feat(#64): replace raw ConnectionError/ValueError raises in providers with ProviderError"
```

---

## Task 3: Migrate StockDataService — Fix is_available Guard and Replace Dict Error Returns

**Files:** `backend/app/services/stock_data.py`, `backend/app/routers/stocks.py`, `backend/app/tasks.py`
**Test:** `backend/tests/services/test_error_conventions.py` (new, first section)

### Background

`StockDataService.refresh_stock_data()` has two bugs to fix together:

1. **Bug: `is_available()` tuple guard always evaluates as truthy.** Line 279 reads `if not massive.is_available():` — but `massive.is_available()` returns `tuple[bool, str]` (a non-empty tuple is always truthy in Python, so the guard never fires). This must be fixed to `available, _ = massive.is_available(); if not available:` so the provider-unavailable path actually executes.

2. **Bug: error dict return.** Line 280 returns `{"status": "error", "message": "..."}` and line 418 returns `{"status": "error", "message": str(e)}`. After this task both raise `DataFetchError`. `ProviderError` from the provider layer is wrapped at the service seam into `DataFetchError` so the service's public contract is consistent.

Callers: `routers/stocks.py` (line 146, must catch `DataFetchError`) and `tasks.py` (lines 1229/1234, must handle `DataFetchError`).

### TDD Steps

**Write the failing test:**

```python
# backend/tests/services/test_error_conventions.py

import pytest
from unittest.mock import MagicMock, patch
from app.exceptions import DataFetchError, ProviderError


class TestStockDataServiceErrors:
    def test_refresh_stock_data_raises_data_fetch_error_when_provider_unavailable(self):
        from app.services.stock_data import StockDataService
        db = MagicMock()
        with patch("app.services.stock_data.DataProviderFactory.get") as mock_factory:
            mock_provider = MagicMock()
            mock_provider.is_available.return_value = (False, "API key missing")
            mock_factory.return_value = mock_provider
            with pytest.raises(DataFetchError) as exc_info:
                StockDataService.refresh_stock_data(db, "AAPL", timespan="minute")
        assert exc_info.value.is_retryable is False
        assert exc_info.value.context.get("provider") == "polygon"
        assert exc_info.value.context.get("symbol") == "AAPL"

    def test_refresh_stock_data_raises_data_fetch_error_wrapping_provider_error(self):
        """ProviderError from provider layer is wrapped into DataFetchError at service seam.

        The call chain is: refresh_stock_data → get_aggregates → get_historical_bars.
        Patch get_aggregates (not get_historical_bars directly) so the exception travels
        through the real call chain and hits refresh_stock_data's except ProviderError block.
        """
        from app.services.stock_data import StockDataService
        db = MagicMock()
        # first() returns None → db_range is None → avoids TypeError from MagicMock > datetime
        db.query.return_value.filter.return_value.first.return_value = None
        with patch("app.services.stock_data.DataProviderFactory.get") as mock_factory:
            mock_provider = MagicMock()
            mock_provider.is_available.return_value = (True, "Ready")
            mock_factory.return_value = mock_provider
            with patch.object(
                StockDataService, "get_aggregates",
                side_effect=ProviderError("rate limited", is_retryable=True, provider="polygon"),
            ):
                with pytest.raises(DataFetchError) as exc_info:
                    StockDataService.refresh_stock_data(db, "TSLA", timespan="minute")
        assert exc_info.value.is_retryable is True
        assert exc_info.value.context.get("symbol") == "TSLA"

    def test_refresh_stock_data_success_dict_shape_unchanged(self):
        from app.services.stock_data import StockDataService
        db = MagicMock()
        # first() returns None → db_range is None → avoids TypeError from MagicMock > datetime
        db.query.return_value.filter.return_value.first.return_value = None
        db.query.return_value.filter.return_value.scalar.return_value = None
        db.query.return_value.filter.return_value.all.return_value = []
        with patch("app.services.stock_data.DataProviderFactory.get") as mock_factory:
            mock_provider = MagicMock()
            mock_provider.is_available.return_value = (True, "Ready")
            mock_provider.get_historical_bars.return_value = []
            mock_factory.return_value = mock_provider
            result = StockDataService.refresh_stock_data(db, "AAPL", timespan="day")
        assert result["status"] == "success"
        assert "added" in result
```

**Verify failure:**
```bash
cd /workspace/markethawk/backend
python -m pytest tests/services/test_error_conventions.py::TestStockDataServiceErrors -v 2>&1 | tail -10
# Expected: AssertionError — provider guard never fires (tuple always truthy);
#           API failures return dict instead of raising DataFetchError
```

**Implement — `backend/app/services/stock_data.py`:**

Add import near top:
```python
from app.exceptions import DataFetchError, ProviderError
```

Fix line 279 and replace line 280 — the provider availability guard:
```python
available, _ = massive.is_available()
if not available:
    raise DataFetchError(
        "Polygon (Massive) provider not available",
        is_retryable=False,
        provider="polygon",
        symbol=ticker,
    )
```

Replace lines 415–418 (`except Exception as e: ... return {"status": "error", ...}`):
```python
except ProviderError as e:
    db.rollback()
    raise DataFetchError(
        str(e),
        is_retryable=e.is_retryable,
        provider=e.context.get("provider", "polygon"),
        symbol=ticker,
        timespan=timespan,
    ) from e
except DataFetchError:
    db.rollback()
    raise
except Exception as e:
    logging.error(f"Error refreshing data for {ticker}: {e}")
    db.rollback()
    raise DataFetchError(
        str(e),
        is_retryable=False,
        provider="polygon",
        symbol=ticker,
        timespan=timespan,
    ) from e
```

**Note — `is_available()` guard scope:** There are 6 `is_available()` guards in `stock_data.py` — lines 31, 78, 128, 279, 442, and 478. **All 6 need the tuple-destructure fix** (`available, _ = massive.is_available(); if not available:`). At line 442 the local variable is named `p`, not `massive` — use `available, _ = p.is_available()` there.

**Only line 279/280 gets the additional `raise DataFetchError(...)` treatment.** Lines 31, 78, 128, 442, and 478 guard methods other than `refresh_stock_data` (e.g., `get_historical_data`, `get_pre_market_movers`) that correctly return empty lists/dicts when the provider is unavailable. Do not change those return paths — only fix the tuple unpack on those 5 guards.

Also update `StockDataService.get_aggregates()` (around line 421): the `except Exception` catch-all (lines ~458–463) currently logs and returns `[]`. After Task 2, `get_historical_bars()` raises `ProviderError` on API failure. `get_aggregates` is called from `refresh_stock_data` at line 345, so `ProviderError` must propagate through `get_aggregates` to reach `refresh_stock_data`'s `except ProviderError` block. Add `except ProviderError: raise` before the generic catch-all:
```python
except ProviderError:
    raise  # propagate to refresh_stock_data caller
except Exception as e:
    logging.exception(f"❌ Provider fetch FAILED for {ticker} ...")
    return []
```

**Implement — `backend/app/routers/stocks.py`:**

Add import at top:
```python
from app.exceptions import DataFetchError
```

Replace the `refresh_stock_data` endpoint handler (lines 132–151):
```python
@router.post("/refresh/{ticker}")
def refresh_stock_data(
    ticker: str,
    timespan: str = "day",
    multiplier: int = 1,
    full_history: bool = False,
    period: Optional[str] = None,
    db: Session = Depends(get_db),
):
    """Trigger a refresh of stock data from Polygon to DB."""
    try:
        ticker = ticker.upper()
        if _is_futures_ticker(db, ticker):
            return {"status": "skipped", "message": "Futures data is synced via IBKR, not Polygon."}
        result = StockDataService.refresh_stock_data(
            db, ticker, timespan, multiplier, full_history, period
        )
        return result
    except DataFetchError as e:
        status = 503 if e.is_retryable else 422
        raise HTTPException(status_code=status, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error refreshing data: {str(e)}")
```

**Implement — `backend/app/tasks.py`:**

Add import after existing imports:
```python
from app.exceptions import DataFetchError
```

Locate the two `StockDataService.refresh_stock_data(...)` calls at lines 1229 and 1234. Wrap both calls (currently inside an `if fetch_missing_data:` block):

```python
if fetch_missing_data:
    daily_period_days = (date.today() - (start - timedelta(days=90))).days
    minute_period_days = (date.today() - start).days + 5
    try:
        StockDataService.refresh_stock_data(
            db, ticker, timespan='day', period=f"{daily_period_days}d"
        )
        StockDataService.refresh_stock_data(
            db, ticker, timespan='minute', period=f"{minute_period_days}d"
        )
    except DataFetchError as e:
        if e.is_retryable:
            raise
        logger.warning(
            "refresh_stock_data non-retryable failure for %s: %s",
            ticker, e,
            extra={"error_type": "DataFetchError", "retryable": False, **e.context},
        )
```

**Verify pass:**
```bash
cd /workspace/markethawk/backend
python -m pytest tests/services/test_error_conventions.py::TestStockDataServiceErrors -v
# Expected: 3 passed
```

**Commit:**
```bash
git add backend/app/services/stock_data.py backend/app/routers/stocks.py \
        backend/app/tasks.py backend/tests/services/test_error_conventions.py
git commit -m "feat(#64): fix is_available guard; replace dict error returns in StockDataService with DataFetchError"
```

---

## Task 4: Migrate FuturesDataService — Replace RuntimeError Raises

**Files:** `backend/app/services/futures_data.py`, `backend/app/tasks.py`
**Test:** `backend/tests/services/test_error_conventions.py` (append `TestFuturesDataServiceErrors` class)

### Background

`FuturesDataService.sync_contract_catalog()` raises `RuntimeError` at two points: line 98 (IBKR provider unavailable) and line 108 (IBKR returned no contracts). `sync_contract_catalog` is called from within `FuturesDataService.download_full_history()`, which in turn is called by the `sync_futures_aggregates` Celery task in `tasks.py` at line 503. The task's `except Exception as e:` block at line 517 uses `self.retry(exc=e, countdown=60)` for all exceptions blindly — after this task it catches `ProviderError` by name and respects `is_retryable`.

### TDD Steps

**Append to `backend/tests/services/test_error_conventions.py`:**

```python
class TestFuturesDataServiceErrors:
    @pytest.mark.asyncio
    async def test_sync_contract_catalog_raises_provider_error_when_ibkr_unavailable(self):
        from app.services.futures_data import FuturesDataService
        db = MagicMock()
        with patch("app.services.futures_data.DataProviderFactory.get") as mock_factory:
            mock_provider = MagicMock()
            mock_provider.is_available.return_value = (False, "TWS not running")
            mock_factory.return_value = mock_provider
            with pytest.raises(ProviderError) as exc_info:
                await FuturesDataService.sync_contract_catalog(db, "ES", "CME")
        assert exc_info.value.is_retryable is True
        assert exc_info.value.context["provider"] == "ibkr"

    @pytest.mark.asyncio
    async def test_sync_contract_catalog_raises_provider_error_when_no_contracts(self):
        from app.services.futures_data import FuturesDataService
        db = MagicMock()
        with patch("app.services.futures_data.DataProviderFactory.get") as mock_factory:
            mock_provider = MagicMock()
            mock_provider.is_available.return_value = (True, "Ready")
            mock_provider.get_futures_contracts = AsyncMock(return_value=[])
            mock_factory.return_value = mock_provider
            with pytest.raises(ProviderError) as exc_info:
                await FuturesDataService.sync_contract_catalog(db, "ES", "CME")
        assert exc_info.value.is_retryable is True
        assert exc_info.value.context["provider"] == "ibkr"
```

**Verify failure:**
```bash
cd /workspace/markethawk/backend
python -m pytest tests/services/test_error_conventions.py::TestFuturesDataServiceErrors -v 2>&1 | tail -5
# Expected: AssertionError — raises RuntimeError, not ProviderError
```

**Implement — `backend/app/services/futures_data.py`:**

Add import:
```python
from app.exceptions import ProviderError
```

Replace line 98 (`raise RuntimeError(f"IBKR provider is not available: {reason}")`):
```python
raise ProviderError(
    f"IBKR provider is not available: {reason}",
    is_retryable=True,
    provider="ibkr",
    endpoint="sync_contract_catalog",
    symbol=symbol,
)
```

Replace lines 108–111 (`raise RuntimeError(f"IBKR returned no contracts...")`):
```python
raise ProviderError(
    f"IBKR returned no contracts for {symbol} on {exchange}. "
    "TWS may be unreachable or the symbol/exchange is incorrect.",
    is_retryable=True,
    provider="ibkr",
    endpoint="sync_contract_catalog",
    symbol=symbol,
    exchange=exchange,
)
```

**Implement — `backend/app/tasks.py`:**

Add `ProviderError` to the import added in Task 3:
```python
from app.exceptions import DataFetchError, ProviderError
```

In the `sync_futures_aggregates` Celery task, replace the `except Exception as e:` block at line 517. **IMPORTANT: the `finally` block at line 521 (`ibkr.disconnect()`, `loop.close()`, `db.close()`) must be preserved exactly as-is.** Only replace the `except` clause:
```python
except ProviderError as e:
    logger.warning(
        "sync_futures_aggregates ProviderError for %s: %s",
        symbol, e,
        extra={"error_type": "ProviderError", "retryable": e.is_retryable, **e.context},
    )
    db.rollback()
    if e.is_retryable:
        raise self.retry(exc=e, countdown=60)
except Exception as e:
    logger.error(f"❌ Error syncing futures aggregates for {symbol}: {e}")
    db.rollback()
    raise self.retry(exc=e, countdown=60)
finally:
    # PRESERVE UNCHANGED — releases IBKR clientId, closes event loop, closes DB session
    from app.providers import DataProviderFactory
    ibkr = DataProviderFactory.get_or_none("ibkr")
    if ibkr:
        ibkr.disconnect()
    loop.close()
    db.close()
```

**Verify pass:**
```bash
cd /workspace/markethawk/backend
python -m pytest tests/services/test_error_conventions.py::TestFuturesDataServiceErrors -v
# Expected: 2 passed
```

**Commit:**
```bash
git add backend/app/services/futures_data.py backend/app/tasks.py \
        backend/tests/services/test_error_conventions.py
git commit -m "feat(#64): replace RuntimeError in FuturesDataService with ProviderError; update task retry logic"
```

---

## Task 5: Add `failed_tickers` JSONB Column to ScannerRun

**Files:** `backend/app/models/scanner_run.py`, Alembic migration

### TDD Steps

**Write the failing test (no DB session needed — model introspection only):**

```python
# append to backend/tests/services/test_error_conventions.py

class TestScannerRunModel:
    def test_scanner_run_has_failed_tickers_column(self):
        from app.models.scanner_run import ScannerRun
        assert hasattr(ScannerRun, "failed_tickers")

    def test_failed_tickers_column_is_nullable(self):
        from app.models.scanner_run import ScannerRun
        col = ScannerRun.__table__.columns["failed_tickers"]
        assert col.nullable is True
```

**Verify failure:**
```bash
cd /workspace/markethawk/backend
python -m pytest tests/services/test_error_conventions.py::TestScannerRunModel -v 2>&1 | tail -5
# Expected: AttributeError — ScannerRun has no failed_tickers
```

**Implement — `backend/app/models/scanner_run.py`:**

Add import:
```python
from sqlalchemy.dialects.postgresql import JSONB
```

Append column after `error_message`:
```python
failed_tickers = Column(JSONB, nullable=True, default=None)
```

**Generate and apply migration:**
```bash
cd /workspace/markethawk/backend
docker-compose exec backend python -m alembic revision --autogenerate \
    -m "add_failed_tickers_to_scanner_runs"
# Expected output:
#   Generating /app/alembic/versions/<hash>_add_failed_tickers_to_scanner_runs.py ... done

docker-compose exec backend python -m alembic upgrade head
# Expected output:
#   Running upgrade <prev_rev> -> <new_rev>, add_failed_tickers_to_scanner_runs
```

**Verify pass:**
```bash
cd /workspace/markethawk/backend
python -m pytest tests/services/test_error_conventions.py::TestScannerRunModel -v
# Expected: 2 passed
```

**Commit:**
```bash
git add backend/app/models/scanner_run.py \
        backend/app/alembic/versions/*_add_failed_tickers_to_scanner_runs.py
git commit -m "feat(#64): add failed_tickers JSONB column to scanner_runs table"
```

---

## Task 6: Migrate ScannerService — Per-Ticker Error Collection and Silent Pass Fixes

**Files:** `backend/app/services/scanner.py`, `backend/app/tasks.py`
**Test:** append `TestScannerServiceErrorHandling` to `backend/tests/services/test_error_conventions.py`

### Background

Four sites in `scanner.py`:
1. **Line 258** — `except Exception: pass` inside `_get_batch_enrichment_data()`, market context enrichment (ES/NQ pct_change)
2. **Line 302** — `except Exception: pass` inside `_get_batch_enrichment_data()`, sector ETF enrichment
3. **Line 610** — `except Exception as e: logging.error(...)` inside `run_pre_market_scan()` per-ticker loop
4. **Line 740** — `except Exception as e: logging.error(...)` inside `run_oversold_bounce_scan()` per-ticker loop

Sites 1 and 2 are enrichment steps where failure is acceptable (scan can proceed with partial data) — they become named catches with structured logging. Sites 3 and 4 collect failures into a `failed_tickers` list.

**Design decision for `ScannerRun.failed_tickers` persistence:** Neither `run_pre_market_scan()` nor `run_oversold_bounce_scan()` creates a `ScannerRun` — that happens in `tasks.py` (`run_universe_scan` at line 1380). The cleanest solution is to add an optional `scanner_run=None` parameter to both scan methods. The tasks.py caller (`run_universe_scan`) passes `scanner_run=run`; callers that don't need persistence pass nothing.

**`_for_date` wrappers do not forward `scanner_run` — this is intentional.** `run_pre_market_scan_for_date` (line 750) and `run_oversold_bounce_scan_for_date` exist to support ad-hoc range scans that have no `ScannerRun` in scope. Do not add `scanner_run` parameter forwarding to these wrappers.

### TDD Steps

**Write the failing test:**

```python
# append to backend/tests/services/test_error_conventions.py
import asyncio
from app.exceptions import ScanError, DataFetchError

class TestScannerServiceErrorHandling:
    def test_run_pre_market_scan_collects_failed_tickers_and_does_not_raise(self):
        """Typed exceptions during per-ticker processing are collected, not re-raised."""
        from app.services.scanner import ScannerService
        from unittest.mock import MagicMock, patch, AsyncMock

        db = MagicMock()
        db.query.return_value.filter.return_value.all.return_value = []

        with patch.object(
            ScannerService, "calculate_day_metrics",
            new_callable=AsyncMock,
            side_effect=DataFetchError(
                "no data", is_retryable=False, provider="polygon", symbol="FAIL"
            )
        ), patch.object(
            # _get_batch_enrichment_data is called via asyncio.to_thread() — a plain sync
            # callable. Use a regular MagicMock (not AsyncMock) so the call returns the
            # tuple directly instead of a coroutine object.
            ScannerService, "_get_batch_enrichment_data",
            return_value=({}, {}, {})
        ):
            results = asyncio.run(
                ScannerService.run_pre_market_scan(["FAIL"], db)
            )

        assert results == []
        db.commit.assert_called()

    def test_run_pre_market_scan_persists_failed_tickers_when_scanner_run_passed(self):
        """When a ScannerRun is passed, failed_tickers are written to it."""
        from app.services.scanner import ScannerService
        from unittest.mock import MagicMock, patch, AsyncMock

        db = MagicMock()
        scanner_run = MagicMock()

        with patch.object(
            ScannerService, "calculate_day_metrics",
            new_callable=AsyncMock,
            side_effect=DataFetchError(
                "rate limited", is_retryable=True, provider="polygon", symbol="TSLA"
            )
        ), patch.object(
            ScannerService, "_get_batch_enrichment_data",
            return_value=({}, {}, {})
        ):
            asyncio.run(
                ScannerService.run_pre_market_scan(["TSLA"], db, scanner_run=scanner_run)
            )

        assert scanner_run.failed_tickers is not None
        assert len(scanner_run.failed_tickers) == 1
        assert scanner_run.failed_tickers[0]["ticker"] == "TSLA"
        assert scanner_run.failed_tickers[0]["error_type"] == "DataFetchError"
```

**Verify failure:**
```bash
cd /workspace/markethawk/backend
python -m pytest tests/services/test_error_conventions.py::TestScannerServiceErrorHandling -v 2>&1 | tail -5
# Expected: TypeError — run_pre_market_scan does not accept scanner_run parameter
```

**Implement — `backend/app/services/scanner.py`:**

Add import:
```python
from app.exceptions import ScanError, DataFetchError, ProviderError
```

**Fix sites 1 & 2 (lines 258, 302) — market context and sector ETF enrichment blocks:**

Replace `except Exception: pass` at line 258 with:
```python
except (DataFetchError, ProviderError) as e:
    logger.warning(
        "Market context enrichment skipped: %s", e,
        extra={"error_type": type(e).__name__, "retryable": e.is_retryable, **e.context},
    )
except Exception as e:
    logger.warning("Market context enrichment skipped (unexpected): %s", e)
```

Replace `except Exception: pass` at line 302 with:
```python
except (DataFetchError, ProviderError) as e:
    logger.warning(
        "Sector ETF enrichment skipped: %s", e,
        extra={"error_type": type(e).__name__, "retryable": e.is_retryable, **e.context},
    )
except Exception as e:
    logger.warning("Sector ETF enrichment skipped (unexpected): %s", e)
```

**Fix `run_pre_market_scan` signature and per-ticker loop (lines 379–614):**

Change the method signature at line 380:
```python
async def run_pre_market_scan(
    tickers: List[str], db: Session, event_date: date = None, scanner_run=None
) -> List[Dict[str, Any]]:
```

Add `failed_tickers = []` after `results = []` at line 386.

Replace the per-ticker except block at lines 610–611:
```python
except (ScanError, DataFetchError, ProviderError) as e:
    failed_tickers.append({
        "ticker": ticker,
        "error_type": type(e).__name__,
        "message": str(e),
        "retryable": e.is_retryable,
        **e.context,
    })
    logger.warning(
        "%s: %s",
        type(e).__name__, e,
        extra={"error_type": type(e).__name__, "retryable": e.is_retryable, **e.context},
    )
# Unexpected Exception propagates — structural failures abort the scan
```

Before `db.commit()` (currently at line 613):
```python
if failed_tickers and scanner_run is not None:
    scanner_run.failed_tickers = failed_tickers
```

**Apply the same pattern to `run_oversold_bounce_scan`** (line 617, same structure):
- Change signature to add `scanner_run=None` parameter
- Add `failed_tickers = []` after `results = []`
- Replace the per-ticker except at lines 740–741 with the same named-catch + append pattern
- Persist `scanner_run.failed_tickers` before `db.commit()`

**Implement — `backend/app/tasks.py`:**

In `run_universe_scan` (around lines 1476–1482), pass `scanner_run=run` to the two scan calls:

```python
elif scanner_type == "oversold_bounce":
    day_events = asyncio.run(
        ScannerService.run_oversold_bounce_scan(tickers, db, event_date=day, scanner_run=run)
    )
else:
    day_events = asyncio.run(
        ScannerService.run_pre_market_scan(tickers, db, event_date=day, scanner_run=run)
    )
```

**Verify pass:**
```bash
cd /workspace/markethawk/backend
python -m pytest tests/services/test_error_conventions.py::TestScannerServiceErrorHandling -v
# Expected: 2 passed
```

**Commit:**
```bash
git add backend/app/services/scanner.py backend/app/tasks.py \
        backend/tests/services/test_error_conventions.py
git commit -m "feat(#64): collect per-ticker failures in ScannerService; persist to ScannerRun.failed_tickers"
```

---

## Task 7: Normalize DiscoveryService — No Bare Silent Swallows

**Files:** `backend/app/services/discovery_service.py`

### Background

Two `except Exception` blocks in `discovery_service.py`:
- **Line 90** — `except Exception as e: logger.error(...); self.db.rollback(); raise` — already correct (re-raises). No change.
- **Line 192** — `except Exception as e: logger.error(...)` inside a debug-logging block — intentionally swallows a non-critical failure. Add a clarifying comment.

### Implementation

Replace line 192 block in `backend/app/services/discovery_service.py`:
```python
except Exception as e:
    # Debug query serialization failure — non-fatal, query still executes below
    logger.error(f"Failed to log debug query: {e}")
```

**Commit:**
```bash
git add backend/app/services/discovery_service.py
git commit -m "fix(#64): document intentional swallow in DiscoveryService debug-logging block"
```

---

## Task 8: Register FastAPI MarketHawkError Handler

**Files:** `backend/app/main.py`
**Test:** append `TestFastAPIErrorHandler` to `backend/tests/services/test_error_conventions.py`

### Background

`main.py` registers a global `Exception` handler at line 196 inside `create_app()`. A `MarketHawkError` handler must be registered **before** it — FastAPI resolves handlers most-specific-first. `ProviderError(is_retryable=True)` → HTTP 503; `DataFetchError(is_retryable=False)` → HTTP 422.

### TDD Steps

**Write the failing test:**

```python
# append to backend/tests/services/test_error_conventions.py
from fastapi.testclient import TestClient

class TestFastAPIErrorHandler:
    def test_markethawk_error_returns_503_for_retryable(self):
        from app.main import create_app
        from app.exceptions import DataFetchError

        app = create_app()

        @app.get("/test-retryable")
        def _raise():
            raise DataFetchError("rate limited", is_retryable=True, provider="polygon")

        client = TestClient(app, raise_server_exceptions=False)
        resp = client.get("/test-retryable")
        assert resp.status_code == 503
        assert resp.json()["retryable"] is True

    def test_markethawk_error_returns_422_for_non_retryable(self):
        from app.main import create_app
        from app.exceptions import ProviderError

        app = create_app()

        @app.get("/test-non-retryable")
        def _raise():
            raise ProviderError("bad symbol", is_retryable=False, provider="ibkr")

        client = TestClient(app, raise_server_exceptions=False)
        resp = client.get("/test-non-retryable")
        assert resp.status_code == 422
        assert resp.json()["retryable"] is False

    def test_unexpected_exception_still_returns_500(self):
        from app.main import create_app

        app = create_app()

        @app.get("/test-unexpected")
        def _raise():
            raise RuntimeError("unexpected internal error")

        client = TestClient(app, raise_server_exceptions=False)
        resp = client.get("/test-unexpected")
        assert resp.status_code == 500
```

**Verify failure:**
```bash
cd /workspace/markethawk/backend
python -m pytest tests/services/test_error_conventions.py::TestFastAPIErrorHandler -v 2>&1 | tail -5
# Expected: AssertionError — DataFetchError falls through to 500 handler
```

**Implement — `backend/app/main.py`:**

Add import (with existing FastAPI imports):
```python
from app.exceptions import MarketHawkError
```

Inside `create_app()`, the new `MarketHawkError` handler **must appear in source order before** the `@app.exception_handler(Exception)` decorator line (currently line 196). FastAPI resolves handlers by registration order — if `Exception` is registered first, it catches `MarketHawkError` before the typed handler is reached.

Add these lines **directly above** `@app.exception_handler(Exception)` at line 196:

```python
@app.exception_handler(MarketHawkError)
async def markethawk_error_handler(request: Request, exc: MarketHawkError):
    status_code = 503 if exc.is_retryable else 422
    return JSONResponse(
        status_code=status_code,
        content={"error": str(exc), "retryable": exc.is_retryable},
    )

# The existing Exception handler below must remain AFTER the MarketHawkError handler above
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    # existing handler body — unchanged
```

**Verify pass:**
```bash
cd /workspace/markethawk/backend
python -m pytest tests/services/test_error_conventions.py::TestFastAPIErrorHandler -v
# Expected: 3 passed
```

**Full test suite:**
```bash
cd /workspace/markethawk/backend
python -m pytest tests/test_exceptions.py tests/providers/test_provider_errors.py \
    tests/services/test_error_conventions.py -v
# Expected: all tests pass
```

**Commit:**
```bash
git add backend/app/main.py backend/tests/services/test_error_conventions.py
git commit -m "feat(#64): register MarketHawkError FastAPI handler — 503 for retryable, 422 for non-retryable"
```

---

## Final Validation

```bash
# 1. Confirm backend reloads cleanly
docker-compose logs backend --tail=20 | grep -E "ERROR|Started|Uvicorn"

# 2. Health check
curl -s http://localhost:8000/api/health | python -m json.tool

# 3. Full test suite
cd /workspace/markethawk/backend
python -m pytest tests/test_exceptions.py tests/providers/test_provider_errors.py \
    tests/services/test_error_conventions.py -v --tb=short

# 4. Verify migration applied
docker-compose exec backend python -m alembic current
# Expected: shows head revision — add_failed_tickers_to_scanner_runs

# 5. Confirm failed_tickers column exists in DB
docker-compose exec db psql -U postgres markethawk -c \
    "SELECT column_name, data_type FROM information_schema.columns \
     WHERE table_name='scanner_runs' AND column_name='failed_tickers';"
# Expected: 1 row — failed_tickers | jsonb
```
