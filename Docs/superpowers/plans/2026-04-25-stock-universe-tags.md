# Stock Universe Tags Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Show which universes a stock belongs to as informational pill tags in the Stock Detail page header, next to the sector badge.

**Architecture:** A new `GET /api/universe/by-ticker/{ticker}` endpoint queries `StockUniverseTicker` + `StockUniverse` and returns a minimal list of `{id, name}`. The frontend calls this via React Query in `StockDetailPage` and renders the tags inline.

**Tech Stack:** FastAPI, SQLAlchemy (sync), Pydantic v2, React 18, TypeScript, React Query, Tailwind CSS

---

## File Map

| Action | Path | Responsibility |
|--------|------|----------------|
| Modify | `backend/app/schemas/universe.py` | Add `UniverseSummary` response schema |
| Modify | `backend/app/routers/universe.py` | Add `GET /by-ticker/{ticker}` endpoint |
| Create | `backend/tests/api/test_universe_by_ticker.py` | API tests for the new endpoint |
| Modify | `frontend/src/api/scanner.ts` | Add `UniverseSummary` type + `fetchUniversesForTicker` |
| Modify | `frontend/src/pages/StockDetailPage.tsx` | React Query call + tag rendering |

---

## Task 1: Add `UniverseSummary` Pydantic schema

**Files:**
- Modify: `backend/app/schemas/universe.py`

- [ ] **Step 1: Add the schema**

Open `backend/app/schemas/universe.py` and append after the existing `StockUniverseResponse` class:

```python
class UniverseSummary(BaseModel):
    """Minimal universe info returned for ticker membership lookups."""
    id: int
    name: str

    model_config = ConfigDict(from_attributes=True)
```

- [ ] **Step 2: Export it from the schemas package**

Open `backend/app/schemas/__init__.py`. Replace the existing `from app.schemas.universe import ...` block and add `UniverseSummary` to `__all__`:

```python
from app.schemas.universe import (
    StockUniverseCreate,
    StockUniverseUpdate,
    StockUniverseResponse,
    UniverseSummary,
)
```

Also add `"UniverseSummary"` to the `__all__` list:

```python
__all__ = [
    "StockUniverseCreate",
    "StockUniverseUpdate",
    "StockUniverseResponse",
    "UniverseSummary",
    # ... keep all existing names
]
```

- [ ] **Step 3: Commit**

```bash
git add backend/app/schemas/universe.py backend/app/schemas/__init__.py
git commit -m "feat(schemas): add UniverseSummary schema for ticker membership"
```

---

## Task 2: Add the backend endpoint

**Files:**
- Modify: `backend/app/routers/universe.py`

- [ ] **Step 1: Import `UniverseSummary`**

In `backend/app/routers/universe.py`, the existing import block reads:

```python
from app.schemas import (
    StockUniverseCreate,
    StockUniverseUpdate,
    StockUniverseResponse,
    MonitoredStockResponse,
)
```

Add `UniverseSummary` to it:

```python
from app.schemas import (
    StockUniverseCreate,
    StockUniverseUpdate,
    StockUniverseResponse,
    MonitoredStockResponse,
    UniverseSummary,
)
```

- [ ] **Step 2: Add the endpoint**

After the existing `@router.post("/create", ...)` endpoint (around line 45), add:

```python
@router.get("/by-ticker/{ticker}", response_model=List[UniverseSummary])
def get_universes_for_ticker(
    ticker: str,
    db: Session = Depends(get_db),
):
    """Return all active universes that contain the given ticker."""
    ticker_upper = ticker.upper()
    rows = (
        db.query(StockUniverse)
        .join(StockUniverseTicker, StockUniverseTicker.universe_id == StockUniverse.id)
        .filter(
            StockUniverseTicker.ticker == ticker_upper,
            StockUniverse.is_active == True,
        )
        .order_by(StockUniverse.name)
        .all()
    )
    return rows
```

- [ ] **Step 3: Commit**

```bash
git add backend/app/routers/universe.py
git commit -m "feat(universe): add GET /by-ticker/{ticker} endpoint"
```

---

## Task 3: Write and run backend tests

**Files:**
- Create: `backend/tests/api/test_universe_by_ticker.py`

- [ ] **Step 1: Write the tests**

Create `backend/tests/api/test_universe_by_ticker.py`:

```python
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.main import app
from app.models import StockUniverse, StockUniverseTicker
from app.core.database import get_db

client = TestClient(app)


def _seed(db: Session, universe_name: str, ticker: str, is_active: bool = True) -> StockUniverse:
    universe = StockUniverse(
        name=universe_name,
        description=None,
        criteria={},
        is_active=is_active,
    )
    db.add(universe)
    db.flush()
    db.add(StockUniverseTicker(universe_id=universe.id, ticker=ticker))
    db.flush()
    return universe


def test_returns_universes_for_ticker(db: Session):
    _seed(db, "Momentum", "AAPL")
    _seed(db, "Tech Picks", "AAPL")

    app.dependency_overrides[get_db] = lambda: db
    response = client.get("/api/universe/by-ticker/AAPL")
    app.dependency_overrides.clear()

    assert response.status_code == 200
    names = [u["name"] for u in response.json()]
    assert "Momentum" in names
    assert "Tech Picks" in names


def test_returns_empty_for_unknown_ticker(db: Session):
    app.dependency_overrides[get_db] = lambda: db
    response = client.get("/api/universe/by-ticker/ZZZZ")
    app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json() == []


def test_excludes_inactive_universes(db: Session):
    _seed(db, "Active Universe", "MSFT", is_active=True)
    _seed(db, "Inactive Universe", "MSFT", is_active=False)

    app.dependency_overrides[get_db] = lambda: db
    response = client.get("/api/universe/by-ticker/MSFT")
    app.dependency_overrides.clear()

    assert response.status_code == 200
    names = [u["name"] for u in response.json()]
    assert "Active Universe" in names
    assert "Inactive Universe" not in names


def test_ticker_lookup_is_case_insensitive(db: Session):
    _seed(db, "Mixed Case", "NVDA")

    app.dependency_overrides[get_db] = lambda: db
    response = client.get("/api/universe/by-ticker/nvda")
    app.dependency_overrides.clear()

    assert response.status_code == 200
    assert len(response.json()) >= 1
```

- [ ] **Step 2: Run tests to verify they pass**

```bash
cd backend && python -m pytest tests/api/test_universe_by_ticker.py -v
```

Expected output: all 4 tests PASS. If any fail due to SQLite schema issues (UUID or JSON column), check the conftest — the `db_engine` fixture catches those errors and skips. In that case, validate the endpoint manually instead (see Task 4).

- [ ] **Step 3: Commit**

```bash
git add backend/tests/api/test_universe_by_ticker.py
git commit -m "test(universe): add tests for GET /by-ticker/{ticker}"
```

---

## Task 4: Validate the endpoint live

- [ ] **Step 1: Confirm backend reloaded**

```bash
docker-compose logs backend --tail=10
```

Expected: recent log line showing the app started (no import errors).

- [ ] **Step 2: Curl the endpoint with a real ticker**

Replace `AAPL` with a ticker you know is in a universe:

```bash
curl -s http://localhost:8000/api/universe/by-ticker/AAPL | python -m json.tool
```

Expected: JSON array like `[{"id": 1, "name": "My Universe"}]` or `[]` if AAPL is in no universes.

- [ ] **Step 3: Curl with a nonsense ticker**

```bash
curl -s http://localhost:8000/api/universe/by-ticker/ZZZNOTREAL | python -m json.tool
```

Expected: `[]` — not a 404.

---

## Task 5: Add frontend API function

**Files:**
- Modify: `frontend/src/api/scanner.ts`

- [ ] **Step 1: Add the type and function**

In `frontend/src/api/scanner.ts`, find the `// ---- Universe` section (around line 195). Add the following **before** the existing `fetchStockUniverses` function:

```ts
export interface UniverseSummary {
  id: number;
  name: string;
}

export const fetchUniversesForTicker = async (ticker: string): Promise<UniverseSummary[]> => {
  const response = await apiClient.get(`/universe/by-ticker/${ticker}`);
  return response.data;
};
```

- [ ] **Step 2: TypeScript check**

```bash
cd frontend && npx tsc --noEmit
```

Expected: no errors.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/api/scanner.ts
git commit -m "feat(api): add fetchUniversesForTicker to scanner API client"
```

---

## Task 6: Add tags to the Stock Detail page

**Files:**
- Modify: `frontend/src/pages/StockDetailPage.tsx`

- [ ] **Step 1: Import the new API function**

At the top of `frontend/src/pages/StockDetailPage.tsx`, the stocks import reads:

```ts
import { fetchStockDetails, refreshStockData, syncMissingStockAggregates } from '../api/stocks';
```

Add the universe import on the next line:

```ts
import { fetchUniversesForTicker } from '../api/scanner';
```

- [ ] **Step 2: Add the React Query call**

After the existing `systemInfo` query (around line 147), add:

```ts
const { data: tickerUniverses = [] } = useQuery({
  queryKey: ['tickerUniverses', symbol],
  queryFn: () => fetchUniversesForTicker(symbol),
  enabled: !!symbol,
  staleTime: 300_000,
});
```

- [ ] **Step 3: Render the tags**

In the JSX header section, locate the sector badge (around line 284):

```tsx
<div className="px-2 py-0.5 bg-gray-800 rounded text-xs font-bold text-gray-400 uppercase">
  {details.info.sector || 'Unknown Sector'}
</div>
```

Immediately after that closing `</div>`, add the universe tags:

```tsx
{tickerUniverses.map((u) => (
  <div
    key={u.id}
    className="px-2 py-0.5 bg-purple-900/50 border border-purple-700/50 rounded text-xs font-bold text-purple-300 uppercase"
  >
    {u.name}
  </div>
))}
```

- [ ] **Step 4: TypeScript check**

```bash
cd frontend && npx tsc --noEmit
```

Expected: no errors.

- [ ] **Step 5: Verify in the browser**

1. Open http://localhost:3000
2. Navigate to a stock detail page for a ticker that belongs to at least one universe.
3. Confirm purple pill tags appear next to the sector badge in the header.
4. Navigate to a ticker in no universes — confirm no tags appear and nothing breaks.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/pages/StockDetailPage.tsx
git commit -m "feat(stock-detail): show universe membership tags in header"
```
