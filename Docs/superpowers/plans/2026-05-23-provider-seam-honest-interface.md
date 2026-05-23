# Provider Seam — Honest Sync Interface

**Goal:** Replace the lying `async` declarations in `BaseDataProvider` with an honest sync interface, eliminate the concrete-type cast (`assert isinstance(massive, MassiveDataProvider)`) in `StockDataService.get_pre_market_movers()`, and consolidate Polygon snapshot normalization inside `MassiveDataProvider.get_snapshots()`.

**Architecture:** Four-file change to production code, two test files updated, two new test files added. No migration, no new models, no frontend changes. IBKR's async futures methods (`get_futures_bars`, `get_futures_contracts`) are untouched. Change flows: `base.py` → `massive.py` → `ibkr.py` → `stock_data.py`.

**Tech Stack:** Python 3.11, FastAPI, pytest

---

## File Structure

| File | Role in this change |
|------|---------------------|
| `backend/app/providers/base.py` | Replace two abstract async methods with three sync abstract methods |
| `backend/app/providers/massive.py` | Rename `get_historical_bars` → `get_bars`; add `get_snapshots` |
| `backend/app/providers/ibkr.py` | Remove dead `async get_historical_bars`; add sync stubs for new interface |
| `backend/app/services/stock_data.py` | Update 4 `get_historical_bars` call sites; replace snapshot concrete-cast block |
| `backend/tests/providers/test_get_historical_bars_pagination.py` | Update `_call` to use `get_bars` with new signature |
| `backend/tests/providers/test_get_snapshots.py` | **New** — cover `get_snapshots` normalization, filtering, error paths |
| `backend/tests/providers/test_ibkr_base_interface.py` | **New** — verify IBKR sync stubs satisfy base interface |
| `backend/tests/fixtures/providers.py` | Update `mock_polygon_provider` to expose `get_bars` and `get_snapshots` |

---

## Task 1: Rename `get_historical_bars` → `get_bars` across base interface and Polygon adapter

**Files:** `backend/app/providers/base.py`, `backend/app/providers/massive.py`, `backend/tests/providers/test_get_historical_bars_pagination.py`

### TDD Steps

**Step 1.1 — Update existing pagination test to call `get_bars`**

Edit `backend/tests/providers/test_get_historical_bars_pagination.py` — replace the `_call` method inside `TestGetHistoricalBarsPagination`:

```python
    def _call(self, provider, pages):
        """Set up get_aggs to return successive pages, then call get_bars."""
        provider._client.get_aggs.side_effect = pages
        return provider.get_bars(
            symbol="AAPL",
            from_date="2026-03-25",
            to_date="2026-04-24",
            timespan="minute",
            multiplier=1,
            limit=PAGE_LIMIT,
            paginate=True,
        )
```

Also update the class docstring reference (line 33 `"""...call get_historical_bars."""` → `"""...call get_bars."""`).

**Step 1.2 — Verify tests fail**

```bash
docker-compose exec backend python -m pytest tests/providers/test_get_historical_bars_pagination.py -v
# Expected: AttributeError: 'MassiveDataProvider' object has no attribute 'get_bars'
# All 7 tests should collect and fail.
```

**Step 1.3 — Update `providers/base.py`**

Replace the entire Market Data section (current `get_historical_bars` + `get_ticker_details`). Also update the class-level docstring from "All providers expose a consistent async interface" → "All providers expose a consistent sync interface" to remove the misleading claim.

```python
# ------------------------------------------------------------------ #
#  Market Data                                                         #
# ------------------------------------------------------------------ #

@abstractmethod
def get_bars(
    self,
    symbol: str,
    from_date: str,
    to_date: str,
    timespan: str,
    multiplier: int = 1,
    **kwargs,
) -> List[Dict[str, Any]]:
    """
    Returns OHLCV dicts: {timestamp (UTC-aware datetime), open, high, low,
    close, volume, vwap, transactions}.

    Args:
        symbol:     Ticker / symbol string (e.g. "AAPL", "ES").
        from_date:  Start date string "YYYY-MM-DD".
        to_date:    End date string "YYYY-MM-DD".
        timespan:   Bar size: "minute", "hour", "day", "week", "month".
        multiplier: Bar multiplier (e.g. 5 for 5-minute bars).
        **kwargs:   Provider-specific extras (e.g. adjusted=True, paginate=True).
    """
    ...

def get_snapshots(self, symbols: Optional[List[str]] = None) -> List[Dict[str, Any]]:
    """
    Returns normalized snapshot dicts: {ticker, price, change_pct, volume, prev_close}.

    symbols=None means "all available" (used for pre-market movers).
    symbols=[...] means filter to those tickers only.
    Override in providers that support snapshots; default returns empty list.

    Promoted to @abstractmethod in Task 2 once both adapters implement it.
    """
    return []

@abstractmethod
def get_ticker_details(self, symbol: str) -> Dict[str, Any]:
    """
    Fetch reference/fundamental info for a symbol.

    Returns a dict with a best-effort subset of:
        { "name", "sector", "industry", "market_cap", "description" }

    Providers that don't support this should return {} rather than raising.
    """
    ...
```

**Step 1.4 — Rename method in `providers/massive.py`**

Change only the method signature (lines 63–75 in current file). Body is unchanged.

Before:
```python
def get_historical_bars(
    self,
    symbol: str,
    timespan: str,
    multiplier: int,
    from_date: str,
    to_date: str,
    adjusted: bool = True,
    sort: str = "asc",
    limit: int = 50000,
    paginate: bool = False,
    **kwargs,
) -> List[Dict[str, Any]]:
```

After:
```python
def get_bars(
    self,
    symbol: str,
    from_date: str,
    to_date: str,
    timespan: str,
    multiplier: int = 1,
    adjusted: bool = True,
    sort: str = "asc",
    limit: int = 50000,
    paginate: bool = False,
    **kwargs,
) -> List[Dict[str, Any]]:
```

The docstring and entire body remain identical.

**Step 1.4b — Fix `async def get_ticker_details` on `providers/ibkr.py`**

After Step 1.3 changes `base.py` to declare `get_ticker_details` as a sync abstract method, `ibkr.py`'s `async def get_ticker_details` (line 194) no longer satisfies the contract. Fix this in the same Task 1 commit to avoid a broken intermediate state.

In `backend/app/providers/ibkr.py`, change line 194 from:

```python
async def get_ticker_details(self, symbol: str) -> Dict[str, Any]:
    """IBKR does not provide fundamental data in a convenient way; return empty."""
    return {}
```

To:

```python
def get_ticker_details(self, symbol: str) -> Dict[str, Any]:
    """IBKR does not provide fundamental data in a convenient way; return empty."""
    return {}
```

(Task 2 will add the `get_snapshots` stub to IBKR when it promotes that method to `@abstractmethod`. Task 3 will add the `get_bars` stub. This step only removes the `async` keyword from `get_ticker_details` to fix the abstract contract immediately.)

**Step 1.5 — Verify pagination tests pass**

```bash
docker-compose exec backend python -m pytest tests/providers/test_get_historical_bars_pagination.py -v
# Expected: 7 passed
```

**Step 1.6 — Commit**

```bash
git add backend/app/providers/base.py \
        backend/app/providers/massive.py \
        backend/app/providers/ibkr.py \
        backend/tests/providers/test_get_historical_bars_pagination.py
git commit -m "refactor(providers): rename get_historical_bars → get_bars; add get_snapshots to base interface; fix ibkr get_ticker_details sync"
```

---

## Task 2: Implement `get_snapshots` on `MassiveDataProvider`

**Files:** `backend/app/providers/massive.py`, `backend/tests/providers/test_get_snapshots.py` (new)

### TDD Steps

**Step 2.1 — Write failing test**

Create `backend/tests/providers/test_get_snapshots.py`:

```python
from unittest.mock import MagicMock
from app.providers.massive import MassiveDataProvider


def _make_provider():
    p = MassiveDataProvider.__new__(MassiveDataProvider)
    p._client = MagicMock()
    return p


def _make_snap(ticker, prev_close, price, volume, change_pct):
    s = MagicMock()
    s.ticker = ticker
    s.prev_day = MagicMock()
    s.prev_day.close = prev_close
    s.prev_day.c = prev_close
    s.day = MagicMock()
    s.day.volume = volume
    s.min = MagicMock()
    s.min.close = price
    s.min.accumulated_volume = 0
    s.last_trade = MagicMock()
    s.last_trade.price = 0
    s.last_trade.p = 0
    s.todays_change_percent = change_pct
    return s


class TestGetSnapshots:
    def test_returns_normalized_dicts(self):
        p = _make_provider()
        raw = [_make_snap("AAPL", prev_close=150.0, price=155.0, volume=500_000, change_pct=3.33)]
        p._client.get_snapshot_all.return_value = raw

        result = p.get_snapshots()

        assert len(result) == 1
        assert result[0] == {
            "ticker": "AAPL",
            "price": 155.0,
            "change_pct": 3.33,
            "volume": 500_000,
            "prev_close": 150.0,
        }

    def test_filters_by_symbols_when_provided(self):
        p = _make_provider()
        raw = [
            _make_snap("AAPL", 150.0, 155.0, 500_000, 3.33),
            _make_snap("MSFT", 300.0, 305.0, 300_000, 1.67),
        ]
        p._client.get_snapshot_all.return_value = raw

        result = p.get_snapshots(symbols=["AAPL"])

        assert len(result) == 1
        assert result[0]["ticker"] == "AAPL"

    def test_symbols_filter_is_case_insensitive(self):
        p = _make_provider()
        raw = [_make_snap("AAPL", 150.0, 155.0, 500_000, 3.33)]
        p._client.get_snapshot_all.return_value = raw

        result = p.get_snapshots(symbols=["aapl"])

        assert len(result) == 1

    def test_skips_zero_prev_close(self):
        p = _make_provider()
        raw = [_make_snap("ZERO", prev_close=0, price=10.0, volume=100_000, change_pct=0)]
        p._client.get_snapshot_all.return_value = raw

        result = p.get_snapshots()

        assert result == []

    def test_skips_zero_price(self):
        p = _make_provider()
        s = _make_snap("NOPRICE", prev_close=100.0, price=0, volume=100_000, change_pct=0)
        s.min.close = 0
        s.last_trade.price = 0
        s.last_trade.p = 0
        p._client.get_snapshot_all.return_value = [s]

        result = p.get_snapshots()

        assert result == []

    def test_volume_prefers_accumulated_when_larger(self):
        p = _make_provider()
        s = _make_snap("VOL", prev_close=100.0, price=105.0, volume=1_000, change_pct=5.0)
        s.min.accumulated_volume = 50_000
        p._client.get_snapshot_all.return_value = [s]

        result = p.get_snapshots()

        assert result[0]["volume"] == 50_000

    def test_returns_empty_when_no_client(self):
        p = MassiveDataProvider.__new__(MassiveDataProvider)
        p._client = None

        result = p.get_snapshots()

        assert result == []

    def test_returns_empty_on_api_exception(self):
        p = _make_provider()
        p._client.get_snapshot_all.side_effect = RuntimeError("API down")

        result = p.get_snapshots()

        assert result == []
```

**Step 2.2 — Verify tests fail**

```bash
docker-compose exec backend python -m pytest tests/providers/test_get_snapshots.py -v
# Expected: AttributeError: type object 'MassiveDataProvider' has no attribute 'get_snapshots'
# All 8 tests should collect and fail.
```

**Step 2.3 — Implement `get_snapshots` in `providers/massive.py`**

Insert after `get_ticker_details` (line 163), before the Polygon-specific extras section:

```python
def get_snapshots(self, symbols: Optional[List[str]] = None) -> List[Dict[str, Any]]:
    if not self._client:
        return []
    try:
        raw = self._client.get_snapshot_all(market_type="stocks") or []
        symbol_set = {s.upper() for s in symbols} if symbols else None
        result = []
        for s in raw:
            if symbol_set and s.ticker not in symbol_set:
                continue
            if not hasattr(s, 'ticker') or not hasattr(s, 'prev_day'):
                continue
            prev_close = getattr(s.prev_day, 'close', 0) or getattr(s.prev_day, 'c', 0)
            if prev_close == 0:
                continue
            price = (
                getattr(s.min, 'close', 0)
                or getattr(s.last_trade, 'price', 0)
                or getattr(s.last_trade, 'p', 0)
            )
            if price == 0:
                continue
            result.append({
                "ticker": s.ticker,
                "price": float(price),
                "change_pct": float(getattr(s, 'todays_change_percent', 0) or 0),
                "volume": int(max(
                    getattr(s.day, 'volume', 0) or 0,
                    getattr(s.min, 'accumulated_volume', 0) or 0,
                )),
                "prev_close": float(prev_close),
            })
        return result
    except Exception as e:
        logger.error(f"MassiveDataProvider: Error fetching snapshots: {e}")
        return []
```

**Step 2.3b — Promote `get_snapshots` to `@abstractmethod` in `base.py` and add stub to `ibkr.py`**

Now that `massive.py` implements `get_snapshots`, promote it to abstract in `base.py` and add the corresponding stub to `ibkr.py` so all concrete providers satisfy the contract before this commit lands.

In `backend/app/providers/base.py`, change:

```python
def get_snapshots(self, symbols: Optional[List[str]] = None) -> List[Dict[str, Any]]:
    """..."""
    return []
```

To:

```python
@abstractmethod
def get_snapshots(self, symbols: Optional[List[str]] = None) -> List[Dict[str, Any]]:
    """
    Returns normalized snapshot dicts: {ticker, price, change_pct, volume, prev_close}.

    symbols=None means "all available" (used for pre-market movers).
    symbols=[...] means filter to those tickers only.
    Providers that don't support snapshots should return [].
    """
    ...
```

In `backend/app/providers/ibkr.py`, add this stub inside the `BaseDataProvider interface` section (after `get_ticker_details`):

```python
def get_snapshots(self, symbols: Optional[List[str]] = None) -> List[Dict[str, Any]]:
    return []  # Not supported for futures
```

**Step 2.4 — Verify tests pass**

```bash
docker-compose exec backend python -m pytest tests/providers/test_get_snapshots.py -v
# Expected: 8 passed
```

**Step 2.5 — Commit**

```bash
git add backend/app/providers/massive.py \
        backend/app/providers/base.py \
        backend/app/providers/ibkr.py \
        backend/tests/providers/test_get_snapshots.py
git commit -m "feat(providers): implement get_snapshots; promote to @abstractmethod; add ibkr stub"
```

---

## Task 3: Update IBKR adapter — remove dead async override, add `get_bars` stub

**Note:** `get_snapshots` and the sync `get_ticker_details` were added to `ibkr.py` in Tasks 1 and 2 respectively. This task removes the dead `async get_historical_bars` and adds the `get_bars` stub.

**Files:** `backend/app/providers/ibkr.py`, `backend/tests/providers/test_ibkr_base_interface.py` (new)

### TDD Steps

**Step 3.1 — Write failing test**

Create `backend/tests/providers/test_ibkr_base_interface.py`:

```python
"""
Verify IBKRDataProvider satisfies the updated BaseDataProvider sync interface.
No live IBKR connection is needed — these test the stub return values only.
"""
import inspect
from app.providers.ibkr import IBKRDataProvider


class TestIBKRBaseInterface:
    def setup_method(self):
        self.provider = IBKRDataProvider.__new__(IBKRDataProvider)

    def test_get_bars_is_sync(self):
        assert not inspect.iscoroutinefunction(IBKRDataProvider.get_bars)

    def test_get_snapshots_is_sync(self):
        assert not inspect.iscoroutinefunction(IBKRDataProvider.get_snapshots)

    def test_get_ticker_details_is_sync(self):
        assert not inspect.iscoroutinefunction(IBKRDataProvider.get_ticker_details)

    def test_get_bars_returns_empty_list(self):
        result = self.provider.get_bars(
            symbol="ES",
            from_date="2026-01-01",
            to_date="2026-05-01",
            timespan="day",
        )
        assert result == []

    def test_get_snapshots_returns_empty_list(self):
        assert self.provider.get_snapshots() == []

    def test_get_snapshots_with_symbols_returns_empty_list(self):
        assert self.provider.get_snapshots(symbols=["ES"]) == []

    def test_get_ticker_details_returns_empty_dict(self):
        assert self.provider.get_ticker_details("ES") == {}
```

**Step 3.2 — Verify tests fail**

```bash
docker-compose exec backend python -m pytest tests/providers/test_ibkr_base_interface.py -v
# Expected: AttributeError for get_bars; test_get_bars_* tests fail.
# NOTE: test_get_snapshots_* and test_get_ticker_details_* will already PASS
# because those methods were added in Tasks 1 and 2 — this is expected.
```

**Step 3.3 — Update `providers/ibkr.py`**

Remove the entire `async def get_historical_bars(...)` block (lines 159–193 in the original file). `get_ticker_details` was already made sync in Task 1 (Step 1.4b). `get_snapshots` was already added in Task 2 (Step 2.3b). Only `get_bars` remains to be added.

Add `get_bars` inside the `BaseDataProvider interface` section (after `get_ticker_details`):

```python
def get_bars(
    self,
    symbol: str,
    from_date: str,
    to_date: str,
    timespan: str,
    multiplier: int = 1,
    **kwargs,
) -> List[Dict[str, Any]]:
    return []  # IBKR serves futures only; use get_futures_bars() instead
```

All futures methods (`get_futures_contracts`, `get_futures_bars`, `connect`, `disconnect`, `_get_connection`, `_fetch_bars_chunked`, `_bar_date_to_utc`, `_resolve_bar_size`) remain unchanged.

**Step 3.4 — Verify tests pass**

```bash
docker-compose exec backend python -m pytest tests/providers/ -v
# Expected: all tests in providers/ pass, including the existing ibkr_orders test
```

**Step 3.5 — Commit**

```bash
git add backend/app/providers/ibkr.py backend/tests/providers/test_ibkr_base_interface.py
git commit -m "refactor(ibkr): remove dead async get_historical_bars; add sync get_bars stub"
```

---

## Task 4: Update `StockDataService` call sites and test fixtures

**Files:** `backend/app/services/stock_data.py`, `backend/tests/fixtures/providers.py`, `backend/tests/api/test_stocks.py`

### TDD Steps

**Step 4.1 — Update mock fixture and related test assertions**

In `backend/tests/fixtures/providers.py`, replace the entire `mock_polygon_provider` fixture. This removes:
- `mock.get_historical_bars.side_effect` (old interface)
- `mock.get_aggregates = mock.get_historical_bars` (alias, no longer needed)

And adds `get_bars` and `get_snapshots`. Full replacement:

```python
@pytest.fixture
def mock_polygon_provider():
    mock = MagicMock()
    mock.name = "massive"
    mock.supported_asset_classes = ["stocks"]
    mock.is_available.return_value = (True, "Ready (mock)")
    mock.get_bars.side_effect = lambda symbol, from_date, to_date, timespan, **kwargs: _make_canned_bars(symbol)
    mock.get_snapshots.return_value = []
    mock.get_ticker_details.side_effect = lambda symbol: _make_canned_ticker_details(symbol)

    original = DataProviderFactory._providers.get("massive")
    DataProviderFactory._providers["massive"] = mock

    yield mock

    if original is not None:
        DataProviderFactory._providers["massive"] = original
    else:
        DataProviderFactory._providers.pop("massive", None)
```

Also update the assertion in `backend/tests/api/test_stocks.py` line 187:

Before:
```python
mock_polygon_provider.get_historical_bars.assert_not_called()
```

After:
```python
mock_polygon_provider.get_bars.assert_not_called()
```

This prevents the assertion from silently passing via MagicMock's auto-attribute creation — after the rename it must assert the method that is actually called.

**Step 4.2 — Run full test suite to capture baseline**

```bash
docker-compose exec backend python -m pytest -v 2>&1 | tail -30
# Note: tests that called get_historical_bars through mock will already fail —
# this is the expected "red" state before updating stock_data.py.
```

**Step 4.3 — Update call sites in `services/stock_data.py`**

**Call site 1 — `get_historical_data` (line ~40):**

Before:
```python
aggs = massive.get_historical_bars(
    symbol=ticker.upper(),
    timespan="day",
    multiplier=1,
    from_date=start_date.strftime("%Y-%m-%d"),
    to_date=end_date.strftime("%Y-%m-%d"),
    limit=50000,
)
```

After:
```python
aggs = massive.get_bars(
    symbol=ticker.upper(),
    from_date=start_date.strftime("%Y-%m-%d"),
    to_date=end_date.strftime("%Y-%m-%d"),
    timespan="day",
    multiplier=1,
    limit=50000,
)
```

**Call site 2 — `get_pre_market_data` (line ~88):**

Before:
```python
aggs = massive.get_historical_bars(
    symbol=ticker.upper(),
    timespan="minute",
    multiplier=1,
    from_date=today_et.strftime("%Y-%m-%d"),
    to_date=today_et.strftime("%Y-%m-%d"),
    limit=50000,
)
```

After:
```python
aggs = massive.get_bars(
    symbol=ticker.upper(),
    from_date=today_et.strftime("%Y-%m-%d"),
    to_date=today_et.strftime("%Y-%m-%d"),
    timespan="minute",
    multiplier=1,
    limit=50000,
)
```

**Call site 3 — `get_aggregates` (line ~446):**

Before:
```python
return p.get_historical_bars(
    symbol=ticker.upper(),
    timespan=timespan,
    multiplier=multiplier,
    from_date=from_date,
    to_date=to_date,
    adjusted=adjusted,
    sort=sort,
    limit=limit,
    paginate=paginate,
)
```

After:
```python
return p.get_bars(
    symbol=ticker.upper(),
    from_date=from_date,
    to_date=to_date,
    timespan=timespan,
    multiplier=multiplier,
    adjusted=adjusted,
    sort=sort,
    limit=limit,
    paginate=paginate,
)
```

**Call site 4 — `get_pre_market_movers` (lines ~477–529): replace entire snapshot fetch + normalization block**

Remove these lines from the top of the method body:
```python
from app.providers.massive import MassiveDataProvider
massive = DataProviderFactory.get("massive")
if not massive.is_available():
    logging.error("Massive (Polygon) provider not available")
    return []

assert isinstance(massive, MassiveDataProvider)
snapshots = massive.get_snapshot_all(market_type="stocks")

if not snapshots:
    logging.warning("No snapshots returned from Polygon")
    return []

movers = []
for s in snapshots:
    if not hasattr(s, 'ticker') or not hasattr(s, 'prev_day'):
        continue
    day_vol = getattr(s.day, 'volume', 0) or 0
    min_acc_vol = getattr(s.min, 'accumulated_volume', 0) or 0
    volume = max(day_vol, min_acc_vol)
    if volume < min_volume:
        continue
    prev_close = getattr(s.prev_day, 'close', 0) or getattr(s.prev_day, 'c', 0)
    if prev_close == 0:
        continue
    change_percent = getattr(s, 'todays_change_percent', 0) or 0
    current_price = getattr(s.min, 'close', 0) or getattr(s.last_trade, 'price', 0) or getattr(s.last_trade, 'p', 0)
    if current_price == 0:
        continue
    movers.append({
        "ticker": s.ticker,
        "name": None,
        "price": float(current_price),
        "change_percent": float(change_percent),
        "change_value": float(getattr(s, 'todays_change', 0)),
        "volume": int(volume),
        "prev_close": float(prev_close)
    })
```

Replace with:
```python
massive = DataProviderFactory.get("massive")
if not massive.is_available():
    logging.error("Massive (Polygon) provider not available")
    return []

raw_snapshots = massive.get_snapshots()
if not raw_snapshots:
    logging.warning("No snapshots returned from Polygon")
    return []

movers = [
    {
        "ticker": s["ticker"],
        "name": None,
        "price": s["price"],
        "change_percent": s["change_pct"],
        "change_value": round(s["price"] - s["prev_close"], 4),
        "volume": s["volume"],
        "prev_close": s["prev_close"],
    }
    for s in raw_snapshots
    if s["volume"] >= min_volume
]
```

The sort, limit, and DB enrichment block that follows these lines remains unchanged.

The full `get_pre_market_movers` method after the change:

```python
@staticmethod
def get_pre_market_movers(
    db: Optional[Session] = None,
    min_volume: int = 10000,
    limit: int = 100
) -> list[Dict[str, Any]]:
    try:
        massive = DataProviderFactory.get("massive")
        if not massive.is_available():
            logging.error("Massive (Polygon) provider not available")
            return []

        raw_snapshots = massive.get_snapshots()
        if not raw_snapshots:
            logging.warning("No snapshots returned from Polygon")
            return []

        movers = [
            {
                "ticker": s["ticker"],
                "name": None,
                "price": s["price"],
                "change_percent": s["change_pct"],
                "change_value": round(s["price"] - s["prev_close"], 4),
                "volume": s["volume"],
                "prev_close": s["prev_close"],
            }
            for s in raw_snapshots
            if s["volume"] >= min_volume
        ]

        # Sort by absolute change percent descending
        movers.sort(key=lambda x: abs(x["change_percent"]), reverse=True)
        top_movers = movers[:limit]

        # Enrich with DB data if available
        if db and top_movers:
            from app.models.ticker_reference import TickerReference
            ticker_list = [m["ticker"] for m in top_movers]
            refs = db.query(TickerReference).filter(TickerReference.ticker.in_(ticker_list)).all()
            ref_map = {r.ticker: r for r in refs}

            for m in top_movers:
                ref = ref_map.get(m["ticker"])
                if ref:
                    m["name"] = ref.name
                    m["sector"] = ref.sector
                    m["market_cap"] = ref.market_cap

        return top_movers

    except Exception as e:
        logging.error(f"Error fetching pre-market movers: {e}")
        return []
```

**Step 4.4 — Verify full test suite passes**

```bash
docker-compose exec backend python -m pytest -v 2>&1 | tail -30
# Expected: same or better pass count vs. before Task 4
```

Also confirm the concrete-type cast is gone:

```bash
grep -n "isinstance.*MassiveDataProvider" backend/app/services/stock_data.py
# Expected: no output
```

**`change_value` note:** The existing `get_pre_market_movers` used Polygon's `todays_change` attribute directly. The refactored version computes `round(price - prev_close, 4)` from the normalized snapshot fields. This is an intentional behavioral tradeoff: `todays_change` is no longer surfaced by `get_snapshots()` (not in the spec's return shape), and `price - prev_close` is equivalent for the scanner's ranking purpose (sorting by `abs(change_percent)` is unaffected). Downstream consumers of `change_value` (frontend `ScannerResults` table) display it for reference only; the difference is negligible in practice.

**`is_available()` note (pre-existing, out of scope):** `is_available()` returns `tuple[bool, str]` but callers use `if not provider.is_available()`. A non-empty tuple is always truthy, so this guard never fires as intended. This bug predates this issue and is unchanged here; do not fix it as part of this refactor.

**Step 4.5 — Commit**

```bash
git add backend/app/services/stock_data.py \
        backend/tests/fixtures/providers.py \
        backend/tests/api/test_stocks.py
git commit -m "refactor(stock_data): update 4 get_bars call sites; replace concrete-cast snapshot block with get_snapshots()"
```

---

## Validation

Run after all four tasks complete:

```bash
# 1. Confirm backend reloaded without import errors
docker-compose logs backend --tail=20

# 2. Full test suite
docker-compose exec backend python -m pytest -v

# 3. Smoke-test the stocks endpoint (exercises get_aggregates → get_bars path)
curl -s "http://localhost:8000/api/stocks/AAPL/history?period=5d" | python -m json.tool | head -20

# 4. Confirm no isinstance cast remains
grep -n "isinstance.*MassiveDataProvider" backend/app/services/stock_data.py
# Expected: no matches

# 5. Confirm the in-method import is also gone
grep -n "from app.providers.massive import" backend/app/services/stock_data.py
# Expected: no matches

# 6. Confirm no get_historical_bars remains in production code
grep -rn "get_historical_bars" backend/app/
# Expected: no matches
```
