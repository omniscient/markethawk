# Provider Seam — Honest Sync Interface

**Date:** 2026-05-23  
**Status:** Pending Review  
**Issue:** [#61](https://github.com/omniscient/markethawk/issues/61)  
**Scope:** `backend/app/providers/` + `backend/app/services/stock_data.py`

---

## Problem

The `BaseDataProvider` seam promises polymorphism it cannot deliver. It declares `async def get_historical_bars()` and `async def get_ticker_details()`, but every implementation is synchronous — Polygon's SDK is blocking and IBKR's `get_historical_bars` override (though genuinely async) is dead code; no call site ever routes to it. Additionally, `get_snapshot_all()` is a Polygon-specific method that leaks past the seam into `StockDataService`, requiring a concrete-type cast (`assert isinstance(massive, MassiveDataProvider)`) to call it.

The seam is hypothetical, not real. You cannot substitute a different adapter at runtime without rewriting call sites.

---

## Goals

1. Replace the lying `async` declarations with an honest sync interface.
2. Add `get_snapshots()` to the base contract, eliminating the concrete-type leak in `StockDataService.get_pre_market_movers()`.
3. Consolidate Polygon-specific snapshot normalization inside `massive.py`.
4. Make IBKR's base interface obligation match its actual role: stocks-only base methods it doesn't implement can be removed from its contract.

---

## Requirements

- The new base interface has two market-data methods: `get_bars()` and `get_snapshots()`.
- Both methods are synchronous (no `async`).
- `get_bars()` returns a list of normalized OHLCV dicts (same shape as today: `{timestamp, open, high, low, close, volume, vwap, transactions}`).
- `get_snapshots()` returns a list of normalized snapshot dicts: `{ticker, price, change_pct, volume, prev_close}`.
- `get_ticker_details()` remains on the base interface, changed from `async def` to `def`.
- `ibkr.py` drops `get_historical_bars()` from its base-contract obligation. IBKR only serves futures via provider-specific async methods (`get_futures_bars`, `get_futures_contracts`); these are unchanged.
- `StockDataService.get_pre_market_movers()` calls `provider.get_snapshots()` on the base interface — no concrete-type cast.
- `get_snapshot_price()` stays as a concrete method on `MassiveDataProvider` only (one caller: `tasks.py` order price check; not a general abstraction).
- No in-memory test adapter shipped in this issue (the clean sync interface makes one possible in a future issue).
- No changes to DB write logic (tz-stripping at write sites stays as-is; adapters already return UTC-aware datetimes).
- All existing callers of `StockDataService.get_aggregates()` continue working without change to their call sites.

---

## Architecture

### Base Interface (`providers/base.py`)

**Before:**
```python
@abstractmethod
async def get_historical_bars(self, symbol, timespan, multiplier, from_date, to_date, **kwargs) -> List[Dict]

@abstractmethod
async def get_ticker_details(self, symbol) -> Dict
```

**After:**
```python
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
    """

@abstractmethod
def get_snapshots(self, symbols: Optional[List[str]] = None) -> List[Dict[str, Any]]:
    """
    Returns normalized snapshot dicts: {ticker, price, change_pct, volume, prev_close}.
    symbols=None means "all available" (used for pre-market movers).
    symbols=[...] means filter to those tickers only (used by test adapters).
    Providers that don't support snapshots should return [].
    """

@abstractmethod
def get_ticker_details(self, symbol: str) -> Dict[str, Any]:
    """Unchanged contract; `async` keyword removed."""
```

### Polygon Adapter (`providers/massive.py`)

- Rename `get_historical_bars` → `get_bars` (no logic change, only signature).
- Add `get_snapshots(symbols)`: wraps `get_snapshot_all()` internally and moves the normalization logic currently in `StockDataService.get_pre_market_movers()` (volume extraction, `change_pct` computation, `prev_close` extraction) inside this method.
- `get_snapshot_all()`, `get_snapshot_price()`, and `get_client()` stay as concrete methods (not on base interface).

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

### IBKR Adapter (`providers/ibkr.py`)

- Remove `async def get_historical_bars()` override (or demote to a non-abstract concrete method if keeping it for future use — preferred: remove entirely since it has zero callers and the IBKR provider's `supported_asset_classes` is `["futures"]`).
- Add stub implementations for the new base methods that return empty (IBKR doesn't serve stocks):

```python
def get_bars(self, symbol, from_date, to_date, timespan, multiplier=1, **kwargs):
    return []  # IBKR serves futures only; use get_futures_bars() instead

def get_snapshots(self, symbols=None):
    return []  # Not supported for futures

def get_ticker_details(self, symbol):
    return {}  # Unchanged behavior
```

### Stock Data Service (`services/stock_data.py`)

- `get_aggregates()`: call `p.get_bars(...)` instead of `p.get_historical_bars(...)`. No other changes.
- `get_pre_market_movers()`: replace the `assert isinstance(massive, MassiveDataProvider)` + `massive.get_snapshot_all()` block with `snapshots = massive.get_snapshots()` (no `symbols` arg = fetch all). The normalization loop that follows is removed (it now lives in `get_snapshots()`). The DB enrichment step (`TickerReference` lookup for name/sector/market_cap) stays in the service — it's correctly a service-layer concern.
- `get_historical_data()` and `get_pre_market_data()`: update calls from `massive.get_historical_bars(...)` → `massive.get_bars(...)`.

---

## File Change Summary

| File | Change |
|------|--------|
| `providers/base.py` | Replace `async get_historical_bars` + `async get_ticker_details` with sync `get_bars`, `get_snapshots`, `get_ticker_details` |
| `providers/massive.py` | Rename method; add `get_snapshots()` with inline normalization |
| `providers/ibkr.py` | Remove `get_historical_bars` override; add no-op `get_bars`, `get_snapshots`; keep all futures methods unchanged |
| `services/stock_data.py` | Call `get_bars` at 4 call sites; replace concrete-cast snapshot block with `get_snapshots()` call; remove normalization loop |

No migration, no new models, no frontend changes.

---

## Alternatives Considered

### Keep `async`, wrap Polygon in `asyncio.run()`

Would make the interface async-honest for IBKR's sake, but Celery tasks are synchronous and calling `asyncio.run()` inside a synchronous context requires event loop management. Polygon calls are blocking HTTP — wrapping them in a coroutine adds complexity with zero benefit. Rejected: added overhead, no actual async win for the stock path.

### Split into `SyncDataProvider` and `AsyncDataProvider` interfaces

Appropriate if IBKR and Polygon had overlapping stock/futures use cases. In practice IBKR is futures-only (`supported_asset_classes = ["futures"]`) and Polygon is stocks-only in this system. The split would add an extra level of inheritance for no current benefit. Rejected: YAGNI.

---

## Open Questions

- Once the seam is clean, should `get_bars` return `pd.DataFrame` directly (as several callers construct one immediately after)? The dict-list form is retained here for consistency with existing patterns and to avoid coupling the interface to pandas. Worth revisiting in a follow-up.

---

## Assumptions

- The `get_historical_bars` → `get_bars` rename is a purely internal change; no external clients consume this interface directly.
- `tasks.py:1163` (`provider.get_snapshot_price(order.symbol)`) is acceptable as a direct concrete-type call; it is not part of this cleanup.
- IBKR's async futures methods (`get_futures_bars`, `get_futures_contracts`) remain unchanged and outside the base contract.
