# Implementation Plan — Futures Data Deep Interface

**Issue**: [#63 — Deepen the Futures Data module: clear interface over 1,023-line implementation](https://github.com/omniscient/markethawk/issues/63)  
**Spec**: `Docs/superpowers/specs/2026-05-23-futures-data-deep-interface-design.md`  
**Date**: 2026-05-23  
**Branch**: `refine/issue-63-deepen-the-futures-data-module--clear-in`

---

## Goal

Collapse `FuturesDataService` from 6 public methods to 2 (`get_continuous_series` and `sync_contracts`). Session and exchange management move inside the service. Router inlines ORM queries for contracts/rollovers and drops the `/fill-gaps` endpoint.

## Architecture

- **No `db` on public methods** — service opens `SessionLocal()` per call
- **No `exchange` on public methods** — `_resolve_exchange(symbol)` resolves from `SYMBOL_EXCHANGE_MAP`
- **Private `_` prefix** on 5 internal methods (advisory, not enforced by Python)
- **Router** inlines ORM queries instead of delegating to removed service methods
- **Callers outside the service** (`stock_data.py`, `normalization.py`, `tasks.py`) updated to drop `db`/call private methods as appropriate

## Tech Stack

FastAPI router, SQLAlchemy sync ORM sessions (`SessionLocal`), pytest integration tests (testcontainers Postgres)

## Files

| File | Change |
|---|---|
| `backend/app/services/futures_data.py` | Add `_resolve_exchange`, `sync_contracts`; rename 5 methods to `_` prefix; refactor `get_continuous_series` to own session; remove `get_contracts`, `get_rollovers` |
| `backend/app/routers/futures.py` | Inline ORM for contracts/rollovers; remove `/fill-gaps`; update `/download` to call `sync_contracts`; remove `db` dependency from `/history` handler |
| `backend/app/services/stock_data.py` | Drop `db=db` from `get_continuous_series` call |
| `backend/app/services/normalization.py` | `download_full_history` → `_download_full_history`; `download_contract` → `_download_contract` |
| `backend/app/tasks.py` | `download_full_history` → `_download_full_history` |
| `backend/tests/services/test_futures_data_interface.py` | New — signature and unit tests for public interface |
| `backend/tests/api/test_futures.py` | Update history tests to use `patch_futures_session` fixture |

---

## Task 1 — Signature tests + `_resolve_exchange` + `sync_contracts`

**Files**: `backend/tests/services/test_futures_data_interface.py` (new), `backend/app/services/futures_data.py`

### Step 1 — Write failing tests

Create `backend/tests/services/test_futures_data_interface.py`:

```python
import inspect
import pytest
from app.services.futures_data import FuturesDataService, _resolve_exchange


# --- _resolve_exchange ---

def test_resolve_exchange_returns_correct_exchange():
    assert _resolve_exchange("ES") == "CME"
    assert _resolve_exchange("NQ") == "CME"
    assert _resolve_exchange("GC") == "COMEX"
    assert _resolve_exchange("CL") == "NYMEX"
    assert _resolve_exchange("ZB") == "CBOT"


def test_resolve_exchange_is_case_insensitive():
    assert _resolve_exchange("es") == "CME"
    assert _resolve_exchange("Nq") == "CME"


def test_resolve_exchange_raises_for_unknown():
    with pytest.raises(ValueError, match="Unknown futures symbol"):
        _resolve_exchange("AAPL")

    with pytest.raises(ValueError, match="Unknown futures symbol"):
        _resolve_exchange("XX")


# --- Public interface contract ---

def test_sync_contracts_has_no_db_param():
    sig = inspect.signature(FuturesDataService.sync_contracts)
    assert "db" not in sig.parameters


def test_sync_contracts_has_no_exchange_param():
    sig = inspect.signature(FuturesDataService.sync_contracts)
    assert "exchange" not in sig.parameters


def test_get_continuous_series_has_no_db_param():
    sig = inspect.signature(FuturesDataService.get_continuous_series)
    assert "db" not in sig.parameters


def test_get_continuous_series_has_no_exchange_param():
    sig = inspect.signature(FuturesDataService.get_continuous_series)
    assert "exchange" not in sig.parameters
```

### Step 2 — Verify tests fail

```bash
cd backend && python -m pytest tests/services/test_futures_data_interface.py -v
# Expected: ImportError (cannot import _resolve_exchange) or multiple FAILED
```

### Step 3 — Add `SessionLocal` import + `_resolve_exchange` + `sync_contracts` to service

At the top of `backend/app/services/futures_data.py`, add the import after `from app.core.config import settings`:

```python
from app.core.database import SessionLocal
```

After the `SYMBOL_EXCHANGE_MAP` constant block (line ~64), add the module-level helper:

```python
def _resolve_exchange(symbol: str) -> str:
    exchange = SYMBOL_EXCHANGE_MAP.get(symbol.upper())
    if not exchange:
        raise ValueError(
            f"Unknown futures symbol '{symbol}'. Add it to SYMBOL_EXCHANGE_MAP."
        )
    return exchange
```

Inside `FuturesDataService`, add `sync_contracts` as the first public method (before `sync_contract_catalog`, around line 83):

```python
    @staticmethod
    async def sync_contracts(symbol: str) -> List[Dict[str, Any]]:
        """
        Refresh the contract catalog for a symbol from IBKR.
        Updates futures_contracts with current metadata only — no OHLCV bars.
        Returns the list of contracts found.
        """
        exchange = _resolve_exchange(symbol)
        with SessionLocal() as db:
            return await FuturesDataService.sync_contract_catalog(db, symbol, exchange)
```

### Step 4 — Verify tests pass

```bash
cd backend && python -m pytest tests/services/test_futures_data_interface.py -v
# Expected: 8 passed
```

### Step 5 — Commit

```
git add backend/app/services/futures_data.py backend/tests/services/test_futures_data_interface.py
git commit -m "feat(futures): add _resolve_exchange helper and sync_contracts public method"
```

---

## Task 2 — Rename 5 internal methods to `_` prefix

**Files**: `backend/app/services/futures_data.py` only

### Step 1 — Confirm tests pass baseline

```bash
cd backend && python -m pytest tests/api/test_futures.py -v
# All tests should pass before rename
```

### Step 2 — Rename method definitions and all internal callers

Rename the 5 method `def` signatures:

| Old | New |
|---|---|
| `async def sync_contract_catalog(` | `async def _sync_contract_catalog(` |
| `async def download_contract(` | `async def _download_contract(` |
| `async def download_full_history(` | `async def _download_full_history(` |
| `async def fill_data_gaps(` | `async def _fill_data_gaps(` |
| `async def detect_rollovers(` | `async def _detect_rollovers(` |

Update all callers **within** `futures_data.py` (4 call sites):

In `_download_full_history` (formerly `download_full_history`):
```python
# Line ~392: sync_contract_catalog → _sync_contract_catalog
await FuturesDataService._sync_contract_catalog(db, symbol, exchange)

# Line ~457: download_contract → _download_contract
result = await FuturesDataService._download_contract(
    db=db, symbol=symbol, exchange=exchange, contract_month=cm,
    timespan=timespan, multiplier=multiplier,
    force_refresh=force_refresh, from_date=from_date, to_date=to_date,
)

# Line ~477: detect_rollovers → _detect_rollovers
rollover_count = await FuturesDataService._detect_rollovers(
    db=db, symbol=symbol, exchange=exchange,
    timespan=timespan, multiplier=multiplier,
)

# Line ~487: fill_data_gaps → _fill_data_gaps
gap_result = await FuturesDataService._fill_data_gaps(
    db=db, symbol=symbol, exchange=exchange,
    timespan=timespan, multiplier=multiplier,
    from_date=from_date, to_date=to_date,
)
```

In `_fill_data_gaps` (formerly `fill_data_gaps`), update the single internal `download_contract` call (line ~621):
```python
result = await FuturesDataService._download_contract(
    db=db, symbol=symbol, exchange=exchange,
    contract_month=contract.contract_month,
    timespan=timespan, multiplier=multiplier,
    force_refresh=False, from_date=gap_start_str, to_date=gap_end_str,
)
```

Also update `sync_contracts` (added in Task 1) to use the renamed method:
```python
return await FuturesDataService._sync_contract_catalog(db, symbol, exchange)
```

### Step 3 — Verify tests pass after rename

```bash
cd backend && python -m pytest tests/api/test_futures.py tests/services/test_futures_data_interface.py -v
# All tests should still pass
```

### Step 4 — Commit

```
git add backend/app/services/futures_data.py
git commit -m "refactor(futures): rename 5 public pipeline methods to _ prefix"
```

---

## Task 3 — `get_continuous_series` drops `db` param; update `stock_data.py`

**Files**: `backend/app/services/futures_data.py`, `backend/app/services/stock_data.py`, `backend/tests/api/test_futures.py`

### Step 1 — Write session-patch fixture + failing test

In `backend/tests/api/test_futures.py`, add the fixture at the top of the file (after existing imports):

```python
from unittest.mock import patch


@pytest.fixture
def patch_futures_session(db):
    class _FakeCM:
        def __enter__(self): return db
        def __exit__(self, *args): return False

    with patch("app.services.futures_data.SessionLocal", new=lambda: _FakeCM()):
        yield
```

Add a new test that uses `patch_futures_session` (to confirm the fixture pattern works):

```python
def test_history_uses_patched_session(patch_futures_session, db: Session):
    seed_futures_contracts(db, symbol="MES", exchange="CME", count=1)
    seed_futures_aggregates(db, symbol="MES", contract_month="20250321", count=3)

    response = client.get("/api/futures/history/MES")

    assert response.status_code == 200
    assert response.json()["data_points"] == 3
```

This will **fail** because `get_continuous_series` still requires `db`:

```bash
cd backend && python -m pytest tests/api/test_futures.py::test_history_uses_patched_session -v
# Expected: FAILED (TypeError: get_continuous_series() missing argument 'db')
```

### Step 2 — Refactor `get_continuous_series`

Replace the method signature and opening in `backend/app/services/futures_data.py`:

**Old signature** (line ~749):
```python
    @staticmethod
    def get_continuous_series(
        db: Session,
        symbol: str,
        timespan: str = "day",
        multiplier: int = 1,
        from_date: Optional[str] = None,
        to_date: Optional[str] = None,
    ) -> pd.DataFrame:
        """
        Assemble and return a continuous (stitched) price series for a futures symbol.
        ...
        """
        # 1. Load rollover table for this symbol
        rollovers = (
```

**New signature** (wrap existing body in `with SessionLocal() as db:`):
```python
    @staticmethod
    def get_continuous_series(
        symbol: str,
        timespan: str = "day",
        multiplier: int = 1,
        from_date: Optional[str] = None,
        to_date: Optional[str] = None,
    ) -> pd.DataFrame:
        """
        Assemble and return a continuous (stitched) price series for a futures symbol.

        The returned DataFrame has columns:
            timestamp, open, high, low, close, volume, vwap, contract_month
        """
        with SessionLocal() as db:
            # 1. Load rollover table for this symbol
            rollovers = (
```

The entire original body (lines ~766–863) is indented one level deeper inside the `with SessionLocal() as db:` block. The final `return df` at the end must be inside the `with` block.

Also remove the `db: Session` import-only usage — the `Session` type is still needed for private methods, so keep `from sqlalchemy.orm import Session`.

### Step 3 — Update `stock_data.py` caller

In `backend/app/services/stock_data.py` at line ~236, remove `db=db`:

**Old**:
```python
            df = FuturesDataService.get_continuous_series(
                db=db,
                symbol=symbol,
                timespan=timespan,
                multiplier=multiplier,
                from_date=from_date,
            )
```

**New**:
```python
            df = FuturesDataService.get_continuous_series(
                symbol=symbol,
                timespan=timespan,
                multiplier=multiplier,
                from_date=from_date,
            )
```

### Step 4 — Update existing history tests to use `patch_futures_session`

The three existing history tests currently use `app.dependency_overrides[get_db]` which won't route the session into the service after this change. Update them to use the new fixture instead:

```python
def test_history_returns_correct_shape(patch_futures_session, db: Session):
    seed_futures_contracts(db, symbol="ES", exchange="CME", count=1)
    seed_futures_aggregates(db, symbol="ES", contract_month="20250321", count=5)

    response = client.get("/api/futures/history/ES")

    assert response.status_code == 200
    data = response.json()
    assert data["symbol"] == "ES"
    assert data["timespan"] == "day"
    assert data["data_points"] == 5
    bar = data["data"][0]
    assert "timestamp" in bar
    assert "open" in bar
    assert "high" in bar
    assert "low" in bar
    assert "close" in bar
    assert "volume" in bar


def test_history_empty_db_returns_zero_data_points(patch_futures_session, db: Session):
    response = client.get("/api/futures/history/ZZ")

    assert response.status_code == 200
    data = response.json()
    assert data["symbol"] == "ZZ"
    assert data["data_points"] == 0
    assert data["data"] == []


def test_history_symbol_is_case_insensitive(patch_futures_session, db: Session):
    seed_futures_contracts(db, symbol="NQ", exchange="CME", count=1)
    seed_futures_aggregates(db, symbol="NQ", contract_month="20250321", count=3)

    response = client.get("/api/futures/history/nq")

    assert response.status_code == 200
    data = response.json()
    assert data["symbol"] == "NQ"
    assert data["data_points"] == 3
```

Remove the `app.dependency_overrides[get_db] = lambda: db` and `app.dependency_overrides.clear()` lines from these three tests.

### Step 5 — Verify all tests pass

```bash
cd backend && python -m pytest tests/api/test_futures.py tests/services/test_futures_data_interface.py -v
# Expected: all tests pass
```

### Step 6 — Commit

```
git add backend/app/services/futures_data.py backend/app/services/stock_data.py backend/tests/api/test_futures.py
git commit -m "refactor(futures): get_continuous_series manages own session, drop db param"
```

---

## Task 4 — Update futures router (inline ORM, update /download, remove /fill-gaps, clean /history)

**Files**: `backend/app/routers/futures.py`

### Step 1 — Write test for removed endpoint

Add to `backend/tests/api/test_futures.py`:

```python
def test_fill_gaps_endpoint_removed(db: Session):
    app.dependency_overrides[get_db] = lambda: db
    response = client.post("/api/futures/fill-gaps/ES")
    app.dependency_overrides.clear()

    assert response.status_code == 404
```

Verify it fails (returns 200/422, not 404):
```bash
cd backend && python -m pytest tests/api/test_futures.py::test_fill_gaps_endpoint_removed -v
# Expected: FAILED
```

### Step 2 — Rewrite the futures router

Replace the full content of `backend/app/routers/futures.py` with:

```python
"""
Futures Router.

Provides REST API endpoints for accessing futures historical data,
rollover schedules, and contract catalogs.
"""

import logging

from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from sqlalchemy.orm import Session
from typing import Optional
import pandas as pd

from app.core.database import get_db
from app.models.futures_contract import FuturesContract
from app.models.futures_rollover import FuturesRollover
from app.services.futures_data import FuturesDataService, _resolve_exchange
from app.providers import DataProviderFactory

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/futures", tags=["futures"])


@router.get("/history/{symbol}")
def get_futures_history(
    symbol: str,
    timespan: str = "day",
    multiplier: int = 1,
    from_date: Optional[str] = None,
    to_date: Optional[str] = None,
):
    """
    Get stitched continuous historical bars for a futures symbol.
    Uses the volume-based rollover map stored in the database.
    """
    try:
        df = FuturesDataService.get_continuous_series(
            symbol=symbol.upper(),
            timespan=timespan,
            multiplier=multiplier,
            from_date=from_date,
            to_date=to_date,
        )

        if df.empty:
            return {
                "symbol": symbol.upper(),
                "timespan": timespan,
                "data_points": 0,
                "data": []
            }

        df['timestamp'] = df['timestamp'].dt.tz_localize('UTC').dt.strftime('%Y-%m-%dT%H:%M:%SZ')

        for col in ['open', 'high', 'low', 'close', 'vwap']:
            if col in df.columns:
                df[col] = df[col].astype(float)

        df = df.where(pd.notnull(df), None)

        data_dict = df.to_dict("records")

        return {
            "symbol": symbol.upper(),
            "timespan": timespan,
            "data_points": len(data_dict),
            "data": data_dict
        }

    except Exception as e:
        logger.error(f"Error serving futures history for {symbol}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/contracts/{symbol}")
def get_futures_contracts(
    symbol: str,
    db: Session = Depends(get_db),
):
    """List all known contract months for a symbol."""
    try:
        contracts = (
            db.query(FuturesContract)
            .filter(FuturesContract.symbol == symbol.upper())
            .order_by(FuturesContract.contract_month.asc())
            .all()
        )
        result = [
            {
                "symbol": c.symbol,
                "exchange": c.exchange,
                "contract_month": c.contract_month,
                "expiry_date": c.expiry_date.isoformat() if c.expiry_date else None,
                "con_id": c.con_id,
                "is_expired": c.is_expired,
                "data_downloaded": c.data_downloaded,
                "first_bar_date": c.first_bar_date.isoformat() if c.first_bar_date else None,
                "last_bar_date": c.last_bar_date.isoformat() if c.last_bar_date else None,
            }
            for c in contracts
        ]
        return {
            "symbol": symbol.upper(),
            "count": len(result),
            "contracts": result
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/rollovers/{symbol}")
def get_futures_rollovers(
    symbol: str,
    db: Session = Depends(get_db),
):
    """List the detected rollover dates used to stitch the continuous series."""
    try:
        rollovers = (
            db.query(FuturesRollover)
            .filter(FuturesRollover.symbol == symbol.upper())
            .order_by(FuturesRollover.roll_date.asc())
            .all()
        )
        result = [
            {
                "symbol": r.symbol,
                "from_contract": r.from_contract,
                "to_contract": r.to_contract,
                "roll_date": r.roll_date.isoformat() if r.roll_date else None,
                "detection_method": r.detection_method,
            }
            for r in rollovers
        ]
        return {
            "symbol": symbol.upper(),
            "count": len(result),
            "rollovers": result
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/download/{symbol}")
def trigger_download(
    symbol: str,
    background_tasks: BackgroundTasks,
):
    """
    Trigger a background contract catalog refresh for a futures symbol.
    Updates futures_contracts table metadata only — does not download OHLCV bars.
    """
    symbol = symbol.upper()
    try:
        _resolve_exchange(symbol)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    background_tasks.add_task(FuturesDataService.sync_contracts, symbol)

    return {
        "status": "started",
        "message": f"Contract catalog refresh for {symbol} started in background.",
    }


@router.get("/providers")
def list_providers():
    """List all known data providers and their supported asset classes."""
    return {"available": DataProviderFactory.get_all_with_classes()}
```

### Step 3 — Verify all futures tests pass

```bash
cd backend && python -m pytest tests/api/test_futures.py -v
# Expected: all tests pass including test_fill_gaps_endpoint_removed
```

### Step 4 — Commit

```
git add backend/app/routers/futures.py backend/tests/api/test_futures.py
git commit -m "refactor(futures): inline ORM queries in router, remove fill-gaps endpoint, update download to sync_contracts"
```

---

## Task 5 — Remove `get_contracts` and `get_rollovers` from the service

**Files**: `backend/app/services/futures_data.py`

### Step 1 — Confirm no remaining callers

```bash
grep -rn "FuturesDataService.get_contracts\|FuturesDataService.get_rollovers" backend/app/
# Expected: no output (router was updated in Task 4)
```

### Step 2 — Delete the two methods

Delete the entire `get_contracts` static method (lines ~870–891) and the entire `get_rollovers` static method (lines ~893–911) from `FuturesDataService`.

The `# Convenience / Info` section header comment should also be removed since both methods under it are gone.

### Step 3 — Verify interface tests still pass

```bash
cd backend && python -m pytest tests/api/test_futures.py tests/services/test_futures_data_interface.py -v
# Expected: all tests pass
```

### Step 4 — Commit

```
git add backend/app/services/futures_data.py
git commit -m "refactor(futures): remove get_contracts and get_rollovers from service (router queries ORM directly)"
```

---

## Task 6 — Update `tasks.py` and `normalization.py`

**Files**: `backend/app/tasks.py`, `backend/app/services/normalization.py`

### Step 1 — Update `tasks.py`

In `backend/app/tasks.py` at the `sync_futures_aggregates` task (line ~503–513), rename the call:

**Old**:
```python
        result = loop.run_until_complete(
            FuturesDataService.download_full_history(
                db=db,
                symbol=symbol,
                exchange=exchange,
                timespan=timespan,
                multiplier=multiplier,
                force_refresh=force,
                from_date=from_date,
                to_date=to_date,
            )
        )
```

**New**:
```python
        result = loop.run_until_complete(
            FuturesDataService._download_full_history(
                db=db,
                symbol=symbol,
                exchange=exchange,
                timespan=timespan,
                multiplier=multiplier,
                force_refresh=force,
                from_date=from_date,
                to_date=to_date,
            )
        )
```

### Step 2 — Update `normalization.py`

In `backend/app/services/normalization.py`, update two call sites:

**Line ~257** — fallback full re-sync:

**Old**:
```python
        result = await FuturesDataService.download_full_history(
            db=db, symbol=symbol, exchange=exchange,
            timespan=timespan, multiplier=multiplier,
            force_refresh=False, from_date=from_date, to_date=to_date,
        )
```

**New**:
```python
        result = await FuturesDataService._download_full_history(
            db=db, symbol=symbol, exchange=exchange,
            timespan=timespan, multiplier=multiplier,
            force_refresh=False, from_date=from_date, to_date=to_date,
        )
```

**Line ~272** — per-contract download:

**Old**:
```python
        result = await FuturesDataService.download_contract(
            db=db,
            symbol=symbol,
            exchange=exchange,
            contract_month=contract.contract_month,
            timespan=timespan,
            multiplier=multiplier,
            force_refresh=False,
            from_date=from_date,
            to_date=to_date,
        )
```

**New**:
```python
        result = await FuturesDataService._download_contract(
            db=db,
            symbol=symbol,
            exchange=exchange,
            contract_month=contract.contract_month,
            timespan=timespan,
            multiplier=multiplier,
            force_refresh=False,
            from_date=from_date,
            to_date=to_date,
        )
```

### Step 3 — Verify `universe.py` needs no change

The spec lists `universe.py` as a file to update, but the router dispatches through the `sync_futures_aggregates` Celery task and never calls `download_full_history` directly:

```bash
grep -rn "download_full_history" backend/app/routers/universe.py
# Expected: no output — universe.py dispatches via Celery task, not service directly
```

### Step 4 — Verify no remaining old public calls exist anywhere in the app

```bash
grep -rn "FuturesDataService\.download_full_history\b\|FuturesDataService\.download_contract\b\|FuturesDataService\.fill_data_gaps\b\|FuturesDataService\.detect_rollovers\b\|FuturesDataService\.sync_contract_catalog\b\|FuturesDataService\.get_contracts\b\|FuturesDataService\.get_rollovers\b" backend/app/
# Expected: no output
```

### Step 5 — Verify all tests pass

```bash
cd backend && python -m pytest tests/api/test_futures.py tests/services/test_futures_data_interface.py -v
# Expected: all tests pass
```

### Step 6 — Commit

```
git add backend/app/tasks.py backend/app/services/normalization.py
git commit -m "refactor(futures): update tasks.py and normalization.py to call private _download methods"
```

---

## Task 7 — Validate end-to-end

### Step 1 — Confirm backend reloads clean

```bash
docker-compose logs backend --tail=20
# Expected: no ImportError, no AttributeError, "Application startup complete"
```

If not running in Docker, restart the dev server and check for errors:
```bash
cd backend && uvicorn app.main:app --reload
```

### Step 2 — Curl the changed endpoints

```bash
# History — should return data or empty
curl -s http://localhost:8000/api/futures/history/ES | python -m json.tool | head -20

# Contracts — should return count + list
curl -s http://localhost:8000/api/futures/contracts/ES | python -m json.tool

# Rollovers — should return count + list
curl -s http://localhost:8000/api/futures/rollovers/ES | python -m json.tool

# Download — should return 400 for unknown symbol
curl -s -X POST "http://localhost:8000/api/futures/download/AAPL" | python -m json.tool
# Expected: {"detail": "Unknown futures symbol 'AAPL'. Add it to SYMBOL_EXCHANGE_MAP."}

# Download — should return 200 for known symbol
curl -s -X POST "http://localhost:8000/api/futures/download/ES" | python -m json.tool
# Expected: {"status": "started", "message": "Contract catalog refresh for ES started in background."}

# Fill-gaps — must be gone
curl -s -X POST "http://localhost:8000/api/futures/fill-gaps/ES"
# Expected: 404 Not Found
```

### Step 3 — Run full test suite

```bash
cd backend && python -m pytest tests/api/test_futures.py tests/services/test_futures_data_interface.py -v
# Expected: all pass
```

### Step 4 — TypeScript check (no frontend changes expected)

```bash
cd frontend && npx tsc --noEmit
# Expected: 0 errors
```

### Step 5 — Verify public interface is exactly 2 methods

```bash
python3 -c "
from app.services.futures_data import FuturesDataService
import inspect
public = [n for n, _ in inspect.getmembers(FuturesDataService, predicate=inspect.isfunction)
          if not n.startswith('_')]
print('Public methods:', public)
assert set(public) == {'get_continuous_series', 'sync_contracts'}, f'Unexpected: {public}'
print('OK — exactly 2 public methods')
"
```

Expected output:
```
Public methods: ['get_continuous_series', 'sync_contracts']
OK — exactly 2 public methods
```

---

## Acceptance Criteria Checklist

- [ ] `FuturesDataService` exposes exactly two public methods: `get_continuous_series` and `sync_contracts`
- [ ] All other current public methods are prefixed with `_`
- [ ] Neither public method accepts a `db` parameter
- [ ] Neither public method accepts an `exchange` parameter
- [ ] `GET /api/futures/history/{symbol}` still returns correct stitched data
- [ ] `GET /api/futures/contracts/{symbol}` and `/rollovers/{symbol}` still return correct data (now via direct ORM query in router)
- [ ] `POST /api/futures/fill-gaps/{symbol}` returns 404
- [ ] Celery task and normalization service updated to use `_download_full_history` / `_download_contract`
- [ ] `npx tsc --noEmit` passes
- [ ] Backend reloads cleanly with no import errors
