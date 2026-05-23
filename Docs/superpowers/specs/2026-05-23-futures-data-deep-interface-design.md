# Futures Data Deep Interface — Design Spec

**Issue**: [#63 — Deepen the Futures Data module: clear interface over 1,023-line implementation](https://github.com/omniscient/markethawk/issues/63)  
**Date**: 2026-05-23  
**Branch**: refine/issue-63-deepen-the-futures-data-module--clear-in  
**Status**: Pending Review

---

## Overview

`backend/app/services/futures_data.py` is a 1,023-line module with no clear caller-facing boundary. Six public static methods expose internal pipeline steps (contract catalog sync, per-contract bar download, rollover detection, gap fill, series assembly) directly to callers. Routers and Celery tasks must know the correct call order and pass infrastructure concerns (DB sessions, IBKR exchange codes) themselves.

This spec collapses the six public methods to two: `get_continuous_series` (read) and `sync_contracts` (catalog refresh). Everything else — the download pipeline, rollover detection, gap fill, and session management — becomes private implementation detail.

---

## Requirements

1. **Two public methods only**: `get_continuous_series` and `sync_contracts`. All other current public methods are renamed with a `_` prefix.
2. **No `db` parameter on public methods**: the service opens and closes its own `SessionLocal` sessions per call.
3. **No `exchange` parameter on public methods**: the service resolves exchange from `SYMBOL_EXCHANGE_MAP` internally. Raises `ValueError` for unknown symbols.
4. **`timespan` and `multiplier` remain as optional kwargs** on `get_continuous_series` — they are data-shape parameters, not orchestration concerns.
5. **`get_contracts` and `get_rollovers` are removed from the service**. The futures router queries `FuturesContract` and `FuturesRollover` ORM models directly for the `/contracts/{symbol}` and `/rollovers/{symbol}` endpoints.
6. **The futures router is updated** to use the new interface: removes `db` from service calls, replaces removed service calls with direct ORM queries, and removes the `POST /fill-gaps/{symbol}` endpoint (gap fill is now a private pipeline concern).
7. **No behavior changes to `get_continuous_series`**: it reads from the database and assembles the series as it does today. It does not trigger downloads.
8. **`sync_contracts` is catalog-only**: after calling it, the caller has fresh `FuturesContract` rows (metadata only) but no OHLCV bars, rollover records, or gap fills.

---

## Architecture

### New Public Interface

```python
class FuturesDataService:

    @staticmethod
    def get_continuous_series(
        symbol: str,
        start: Optional[str] = None,
        end: Optional[str] = None,
        timespan: str = "day",
        multiplier: int = 1,
    ) -> pd.DataFrame:
        """
        Return a stitched continuous price series from the database.
        Columns: timestamp, open, high, low, close, volume, vwap, contract_month.
        Returns an empty DataFrame if no data exists for the symbol.
        """

    @staticmethod
    async def sync_contracts(symbol: str) -> List[Dict[str, Any]]:
        """
        Refresh the contract catalog for a symbol from IBKR.
        Updates the futures_contracts table with current contract months,
        expiry dates, and con_ids. Does not download OHLCV bars.
        Returns the list of contracts found.
        """
```

### Private Methods (renamed from public)

| Old name | New name | Notes |
|---|---|---|
| `sync_contract_catalog(db, symbol, exchange)` | `_sync_contract_catalog(db, symbol, exchange)` | Called by `sync_contracts` |
| `download_contract(db, symbol, exchange, ...)` | `_download_contract(db, symbol, exchange, ...)` | Called by `_download_full_history` |
| `download_full_history(db, symbol, exchange, ...)` | `_download_full_history(db, symbol, exchange, ...)` | Called by `_refresh` |
| `fill_data_gaps(db, symbol, exchange, ...)` | `_fill_data_gaps(db, symbol, exchange, ...)` | Called by `_download_full_history` |
| `detect_rollovers(db, symbol, exchange, ...)` | `_detect_rollovers(db, symbol, exchange, ...)` | Called by `_download_full_history` |
| `get_contracts(db, symbol)` | **removed** | Router queries ORM directly |
| `get_rollovers(db, symbol)` | **removed** | Router queries ORM directly |

The private helpers `_detect_single_rollover` and `_build_time_slices` (already module-level functions, not on the class) are unchanged.

### Session Management

The two public methods open their own sessions:

```python
@staticmethod
def get_continuous_series(symbol, ...):
    with SessionLocal() as db:
        # read from DB, assemble DataFrame
        ...

@staticmethod
async def sync_contracts(symbol):
    exchange = _resolve_exchange(symbol)   # raises ValueError if unknown
    with SessionLocal() as db:
        return await FuturesDataService._sync_contract_catalog(db, symbol, exchange)
```

A module-level helper resolves exchange:

```python
def _resolve_exchange(symbol: str) -> str:
    exchange = SYMBOL_EXCHANGE_MAP.get(symbol.upper())
    if not exchange:
        raise ValueError(f"Unknown futures symbol '{symbol}'. Add it to SYMBOL_EXCHANGE_MAP.")
    return exchange
```

### Router Changes (`backend/app/routers/futures.py`)

| Endpoint | Before | After |
|---|---|---|
| `GET /history/{symbol}` | `FuturesDataService.get_continuous_series(db=db, ...)` | `FuturesDataService.get_continuous_series(symbol, start=from_date, end=to_date, ...)` — `db` removed from call; `db` dependency removed from route handler if no longer needed |
| `GET /contracts/{symbol}` | `FuturesDataService.get_contracts(db, symbol)` | Direct ORM query: `db.query(FuturesContract).filter(...).all()` |
| `GET /rollovers/{symbol}` | `FuturesDataService.get_rollovers(db, symbol)` | Direct ORM query: `db.query(FuturesRollover).filter(...).all()` |
| `POST /download/{symbol}` | `FuturesDataService.download_full_history(db=db, ...)` | `FuturesDataService.sync_contracts(symbol)` in background — catalog refresh only |
| `POST /fill-gaps/{symbol}` | `FuturesDataService.fill_data_gaps(db=db, ...)` | **Removed**. Gap fill is a private pipeline concern, no longer exposed. |

**Note on `GET /history/{symbol}`**: Since `get_continuous_series` now manages its own session, the route handler's `db: Session = Depends(get_db)` dependency is only needed if the handler still queries the DB directly (e.g., for validation). If not, the dependency can be removed from the handler signature entirely.

**Note on `POST /download/{symbol}`**: After this refactoring, this endpoint triggers catalog refresh only (`sync_contracts`). Callers that need to trigger a full bar download (IBKR → DB → rollovers → gap fill) have no public API for it. The `universe` router (`routers/universe.py`) also calls `download_full_history` for the Catch Up feature. That call should be updated to call the private `_download_full_history` (or the task-level wrapper in `tasks.py`). Python `_` convention is advisory; routers accessing private methods is acceptable during a phased migration. A follow-up issue can expose a proper `refresh` method if the need arises.

### Celery Task Update (`backend/app/tasks.py`)

The `sync_futures_aggregates` task currently calls `FuturesDataService.download_full_history(...)` directly. After this change it should call the private `_download_full_history` directly (same advisory `_` convention applies) or be left as-is since Celery tasks are internal orchestration.

### Universe Router Update (`backend/app/routers/universe.py`)

Currently imports `FuturesDataService` and calls `download_full_history` for the Catch Up feature. After this change it should call `_download_full_history` directly (or through the Celery task path).

---

## Alternatives Considered

### Option A — Keep all current public methods, add docstrings (rejected)
Add clear async/sync tags and ordering constraints via docstrings. Fast, no risk of breakage. Rejected because it's cosmetic — callers still need to read the docs and pass `db`, `exchange`, and know the call order. The interface remains shallow.

### Option B — Split into multiple service classes (rejected)
Create `ContractCatalogService`, `BarDownloadService`, `RolloverService`, `SeriesAssemblyService`. Provides the strongest separation of concerns. Rejected because the issue explicitly proposes keeping everything in one file behind a 2-method interface. Four classes for one module is over-engineering for this scope.

### Option C — Service owns sessions, 2-method public interface (chosen)
Collapses public surface to `get_continuous_series` + `sync_contracts`. Session lifecycle moves inside the service. Router code becomes simpler (no db injection to the service). Consistent with the issue's stated solution and wins.

---

## Open Questions

1. **Full download trigger via public API**: After this refactor, there is no public method to trigger a full IBKR bar download + rollover detection + gap fill. Callers (the Download button in the UI, Celery tasks) must call the private `_download_full_history`. A follow-up could expose `refresh(symbol)` as a third public method if this pattern proves painful.

2. **Lazy loading in `get_continuous_series`**: Q1 brainstorming raised the idea that `get_continuous_series` could detect missing data and trigger `_download_full_history` internally (lazy on-demand fetch). This is not included in this spec because: (a) `get_continuous_series` is sync and IBKR calls are async, making lazy loading complex; (b) it changes the current behavior (fast DB read → potentially slow IBKR call). This is a candidate for a follow-up spec.

3. **`exchange` parameter removal from `POST /download`**: The current `POST /download/{symbol}` endpoint accepts `exchange` as a required query parameter. After moving exchange resolution inside the service, this parameter becomes unused in service calls. The endpoint signature should drop it (callers relying on it will need updating).

---

## Assumptions

- `SYMBOL_EXCHANGE_MAP` covers all symbols in production use. If a symbol is not in the map, the service raises `ValueError` rather than silently failing.
- The `db` sessions opened internally by the service use the same `SessionLocal` factory as the rest of the app (`app.core.database.SessionLocal`). No new connection pools.
- Private method `_` renaming is advisory — Python does not enforce it. Callers (tasks, routers) that need the full pipeline may call `_download_full_history` directly during the migration period.
- No changes to the `FuturesContract`, `FuturesAggregate`, `FuturesRollover` ORM models or database schema.
- No frontend changes required. The router endpoints retain the same URLs and response shapes.

---

## Files Involved

| File | Change type |
|---|---|
| `backend/app/services/futures_data.py` | **Refactor** — rename 5 methods to `_` prefix, remove 2, update 2 public methods to drop `db` and manage sessions internally |
| `backend/app/routers/futures.py` | **Update** — inline ORM queries for contracts/rollovers, remove `db` from service calls, remove `/fill-gaps` endpoint, update `/download` to call `sync_contracts` |
| `backend/app/routers/universe.py` | **Update** — change `download_full_history` call to `_download_full_history` (or task path) |
| `backend/app/tasks.py` | **Update** — change `download_full_history` call to `_download_full_history` |

---

## Acceptance Criteria

- [ ] `FuturesDataService` exposes exactly two public methods: `get_continuous_series` and `sync_contracts`
- [ ] All other current public methods are prefixed with `_`
- [ ] Neither public method accepts a `db` parameter
- [ ] Neither public method accepts an `exchange` parameter
- [ ] `GET /api/futures/history/{symbol}` still returns correct stitched data
- [ ] `GET /api/futures/contracts/{symbol}` and `/rollovers/{symbol}` still return correct data (now via direct ORM query in router)
- [ ] `POST /api/futures/fill-gaps/{symbol}` endpoint is removed
- [ ] Celery task and universe router updated to use private `_download_full_history`
- [ ] `npx tsc --noEmit` passes (no frontend changes expected)
- [ ] Backend reloads cleanly with no import errors after changes
