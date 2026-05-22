# Implementation Plan: Scanner Validation Skill

**Date:** 2026-05-22  
**Issue:** [#5 — Scanner validation skill: guided day-by-day QA walkthrough](https://github.com/omniscient/markethawk/issues/5)  
**Spec:** [Docs/superpowers/specs/2026-05-14-scanner-validation-skill-design.md](../specs/2026-05-14-scanner-validation-skill-design.md)  
**Branch:** `plan/issue-5-scanner-validation-skill`

## Goal

Add a `/validate-scanner` Claude Code skill that walks through scanner signals one trading day at a time, presents each signal with price/volume context, accepts user verdicts (confirm/reject/enhance/skip/quit), persists verdicts to a new `signal_reviews` DB table, and supports resumability via a local cursor JSON. Requires 3 backend changes, 1 frontend change, and 1 skill file.

## Architecture

```
/validate-scanner skill (SKILL.md)
  │
  ├── Backend
  │     ├── GET /api/scanner/results — add start_date / end_date params
  │     ├── POST /api/signal-reviews — write verdict to DB
  │     └── GET /api/signal-reviews  — list for report generation
  │
  ├── New model: SignalReview (signal_reviews table + Alembic migration)
  │     └── FK → scanner_events.id
  │
  ├── Frontend
  │     └── StockDetailPage: useSearchParams → highlightDate (existing Chart prop)
  │
  └── Runtime
        └── Docs/scanner-validation/{scanner_type}_progress.json  (cursor only)
```

## Tech Stack

- Backend: FastAPI, SQLAlchemy (sync `Session`), PostgreSQL, Alembic
- Frontend: React 18, TypeScript, react-router-dom v7, `lightweight-charts ^5.1.0`
- Tests: pytest (backend), `npx tsc --noEmit` (frontend)

## File Structure

| File | Change |
|------|--------|
| `backend/app/routers/scanner.py` | Add `start_date`/`end_date` query params to `get_scanner_results` |
| `backend/app/models/signal_review.py` | **New** — `SignalReview` model |
| `backend/app/models/scanner_event.py` | Add `reviews` relationship |
| `backend/app/models/__init__.py` | Register `SignalReview` |
| `backend/app/schemas/signal_review.py` | **New** — request/response schemas |
| `backend/app/routers/signal_reviews.py` | **New** — POST + GET endpoints |
| `backend/app/routers/__init__.py` | Export `signal_reviews_router` |
| `backend/app/main.py` | Include `signal_reviews_router` |
| `backend/app/alembic/versions/<hash>_add_signal_reviews.py` | **New** — migration |
| `backend/tests/api/test_signal_reviews.py` | **New** — API tests |
| `backend/tests/api/test_scanner.py` | Add date-filter tests |
| `frontend/src/pages/StockDetailPage.tsx` | Wire `?date=` → `highlightDate` |
| `.claude/skills/validate-scanner/SKILL.md` | **New** — skill instructions |
| `Docs/scanner-validation/.gitkeep` | **New** — keeps directory in git |
| `Docs/scanner-validation/.gitignore` | **New** — ignores `*.json` progress files |

---

## Task 1: Add date range filter to `GET /api/scanner/results`

**Files:** `backend/app/routers/scanner.py`, `backend/tests/api/test_scanner.py`  
**Time:** ~15 min

### Step 1.1 — Write failing tests

Add to `backend/tests/api/test_scanner.py`. The fixture seeds events for `today`, `today-1`, and `today-2` (from `get_market_today()`), so tests use those relative dates:

```python
from datetime import timedelta
from app.utils.session import get_market_today


def test_results_filter_by_start_date(db: Session):
    seed_scanner_events(db)
    today = get_market_today()
    today_str = str(today)

    app.dependency_overrides[get_db] = lambda: db
    response = client.get(f"/api/scanner/results?start_date={today_str}")
    app.dependency_overrides.clear()

    assert response.status_code == 200
    data = response.json()
    assert len(data) > 0
    assert all(e["event_date"] >= today_str for e in data)


def test_results_filter_by_end_date(db: Session):
    seed_scanner_events(db)
    today = get_market_today()
    two_days_ago = str(today - timedelta(days=2))

    app.dependency_overrides[get_db] = lambda: db
    response = client.get(f"/api/scanner/results?end_date={two_days_ago}")
    app.dependency_overrides.clear()

    assert response.status_code == 200
    data = response.json()
    assert len(data) > 0
    assert all(e["event_date"] <= two_days_ago for e in data)


def test_results_filter_by_date_range(db: Session):
    seed_scanner_events(db)
    today = get_market_today()
    yesterday = str(today - timedelta(days=1))

    app.dependency_overrides[get_db] = lambda: db
    response = client.get(f"/api/scanner/results?start_date={yesterday}&end_date={yesterday}")
    app.dependency_overrides.clear()

    assert response.status_code == 200
    data = response.json()
    assert len(data) > 0
    assert all(e["event_date"] == yesterday for e in data)
```

### Step 1.2 — Verify tests fail

```bash
docker-compose exec backend python -m pytest tests/api/test_scanner.py::test_results_filter_by_start_date -x -v
# Expected: FAILED — no start_date param exists yet
```

### Step 1.3 — Implement

In `backend/app/routers/scanner.py`, add two imports at the top of the file if not present:

```python
from datetime import date
from fastapi import Query
```

Then in the `get_scanner_results` function signature (currently at line ~340), add after `limit` and `offset`:

```python
@router.get("/results", response_model=List[ScannerEventResponse])
def get_scanner_results(
    ticker: Optional[str] = None,
    scanner_type: Optional[str] = None,
    event_type: Optional[str] = None,
    universe_id: Optional[int] = None,
    sort_by: Optional[str] = "signal_quality_score",
    sort_order: Optional[str] = "desc",
    limit: int = 100,
    offset: int = 0,
    start_date: Optional[date] = Query(None),
    end_date: Optional[date] = Query(None),
    db: Session = Depends(get_db),
):
```

After the existing `if universe_id:` block, before the sorting logic, add:

```python
    if start_date:
        query = query.filter(ScannerEvent.event_date >= start_date)
    if end_date:
        query = query.filter(ScannerEvent.event_date <= end_date)
```

### Step 1.4 — Verify tests pass

```bash
docker-compose exec backend python -m pytest tests/api/test_scanner.py -k "date" -v
# Expected: 3 passed
```

### Step 1.5 — Validate live

```bash
docker-compose logs backend --tail=5  # confirm reload
curl -s "http://localhost:8000/api/scanner/results?start_date=2025-01-01&end_date=2025-01-01&limit=3" | python3 -m json.tool
# Expected: JSON array (possibly empty if no events that day)
```

### Step 1.6 — Commit

```bash
git add backend/app/routers/scanner.py backend/tests/api/test_scanner.py
git commit -m "feat(scanner): add start_date/end_date filter to GET /api/scanner/results"
```

---

## Task 2: Create `SignalReview` model and migration

**Files:** `backend/app/models/signal_review.py` (new), `backend/app/models/scanner_event.py`, `backend/app/models/__init__.py`  
**Time:** ~20 min

### Step 2.1 — Create `backend/app/models/signal_review.py`

```python
from datetime import datetime, timezone
from sqlalchemy import Column, Integer, String, DateTime, ForeignKey
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import relationship

from app.core.database import Base


class SignalReview(Base):
    __tablename__ = "signal_reviews"

    id = Column(Integer, primary_key=True, index=True)
    scanner_event_id = Column(
        Integer, ForeignKey("scanner_events.id", ondelete="CASCADE"), nullable=False, index=True
    )
    verdict = Column(String(20), nullable=False)          # confirmed | rejected | enhanced
    reject_reason = Column(String(50), nullable=True)     # noise | too_late | stale_data | split_artifact | threshold_too_loose | other
    notes = Column(String(1000), nullable=True)
    enhance_suggestion = Column(JSONB, nullable=True)     # {threshold, current_value, proposed_value, rationale, file, line_hint}
    reviewed_at = Column(
        DateTime,
        default=lambda: datetime.now(timezone.utc).replace(tzinfo=None),
        nullable=False,
    )
    reviewed_by = Column(String(100), nullable=True)      # reserved for future multi-user

    event = relationship("ScannerEvent", back_populates="reviews")
```

### Step 2.2 — Add `reviews` relationship to `ScannerEvent`

Edit `backend/app/models/scanner_event.py`. At the top, add the relationship import:

```python
from sqlalchemy.orm import relationship
```

At the end of the `ScannerEvent` class body, before `__table_args__`:

```python
    reviews = relationship("SignalReview", back_populates="event", cascade="all, delete-orphan")
```

### Step 2.3 — Register in `backend/app/models/__init__.py`

Add after the `SignalCluster` import:

```python
from app.models.signal_review import SignalReview
```

Add `"SignalReview"` to the `__all__` list.

### Step 2.4 — Generate and apply migration

```bash
docker-compose exec backend python -m alembic revision --autogenerate -m "add_signal_reviews"
# Expected: Generating .../alembic/versions/<hash>_add_signal_reviews.py ... done

docker-compose exec backend python -m alembic upgrade head
# Expected: Running upgrade ... -> <hash>, add_signal_reviews ... done
```

### Step 2.5 — Verify migration applied

```bash
docker-compose exec backend python -c "
from app.core.database import SessionLocal
from app.models.signal_review import SignalReview
db = SessionLocal()
print(db.query(SignalReview).count(), 'rows in signal_reviews')
db.close()
"
# Expected: 0 rows in signal_reviews
```

### Step 2.6 — Commit

```bash
git add backend/app/models/signal_review.py backend/app/models/scanner_event.py backend/app/models/__init__.py backend/app/alembic/versions/
git commit -m "feat(model): add SignalReview model and migration"
```

---

## Task 3: Signal-reviews Pydantic schemas

**Files:** `backend/app/schemas/signal_review.py` (new)  
**Time:** ~10 min

### Step 3.1 — Create `backend/app/schemas/signal_review.py`

```python
from datetime import datetime
from typing import Any, Dict, Optional
from pydantic import BaseModel, ConfigDict, field_validator


VALID_VERDICTS = {"confirmed", "rejected", "enhanced"}
VALID_REJECT_REASONS = {"noise", "too_late", "stale_data", "split_artifact", "threshold_too_loose", "other"}


class SignalReviewCreate(BaseModel):
    scanner_event_id: int
    verdict: str
    reject_reason: Optional[str] = None
    notes: Optional[str] = None
    enhance_suggestion: Optional[Dict[str, Any]] = None

    @field_validator("verdict")
    @classmethod
    def verdict_must_be_valid(cls, v: str) -> str:
        if v not in VALID_VERDICTS:
            raise ValueError(f"verdict must be one of {VALID_VERDICTS}")
        return v

    @field_validator("reject_reason")
    @classmethod
    def reject_reason_must_be_valid(cls, v: Optional[str]) -> Optional[str]:
        if v is not None and v not in VALID_REJECT_REASONS:
            raise ValueError(f"reject_reason must be one of {VALID_REJECT_REASONS}")
        return v

    def model_post_init(self, __context: Any) -> None:
        if self.verdict == "rejected" and not self.reject_reason:
            raise ValueError("reject_reason is required when verdict is 'rejected'")


class SignalReviewResponse(BaseModel):
    id: int
    scanner_event_id: int
    verdict: str
    reject_reason: Optional[str]
    notes: Optional[str]
    enhance_suggestion: Optional[Dict[str, Any]]
    reviewed_at: datetime
    reviewed_by: Optional[str]
    # Joined fields from ScannerEvent (populated in GET list endpoint)
    ticker: Optional[str] = None
    event_date: Optional[str] = None
    scanner_type: Optional[str] = None

    model_config = ConfigDict(from_attributes=True)
```

### Step 3.2 — Commit (no separate test step — schemas are covered by router tests in Task 4)

```bash
git add backend/app/schemas/signal_review.py
git commit -m "feat(schema): add SignalReview Pydantic schemas"
```

---

## Task 4: Signal-reviews FastAPI router

**Files:** `backend/app/routers/signal_reviews.py` (new), `backend/app/routers/__init__.py`, `backend/app/main.py`, `backend/tests/api/test_signal_reviews.py` (new)  
**Time:** ~25 min

### Step 4.1 — Write failing tests

Create `backend/tests/api/test_signal_reviews.py`:

```python
"""
Integration tests for POST/GET /api/signal-reviews.
"""
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.main import app
from app.core.database import get_db
from app.models.scanner_event import ScannerEvent
from tests.fixtures.scanner import seed_scanner_events

client = TestClient(app)


def _get_first_event_id(db: Session) -> int:
    seed_scanner_events(db)
    event = db.query(ScannerEvent).first()
    return event.id


def test_create_confirmed_review(db: Session):
    event_id = _get_first_event_id(db)

    app.dependency_overrides[get_db] = lambda: db
    response = client.post("/api/signal-reviews", json={
        "scanner_event_id": event_id,
        "verdict": "confirmed",
    })
    app.dependency_overrides.clear()

    assert response.status_code == 201
    data = response.json()
    assert data["verdict"] == "confirmed"
    assert data["scanner_event_id"] == event_id
    assert data["id"] > 0


def test_create_rejected_review_requires_reason(db: Session):
    event_id = _get_first_event_id(db)

    app.dependency_overrides[get_db] = lambda: db
    response = client.post("/api/signal-reviews", json={
        "scanner_event_id": event_id,
        "verdict": "rejected",
        # missing reject_reason
    })
    app.dependency_overrides.clear()

    assert response.status_code == 422


def test_create_rejected_review_with_reason(db: Session):
    event_id = _get_first_event_id(db)

    app.dependency_overrides[get_db] = lambda: db
    response = client.post("/api/signal-reviews", json={
        "scanner_event_id": event_id,
        "verdict": "rejected",
        "reject_reason": "noise",
        "notes": "Volume spike was a data artifact",
    })
    app.dependency_overrides.clear()

    assert response.status_code == 201
    data = response.json()
    assert data["reject_reason"] == "noise"


def test_create_review_invalid_event_id(db: Session):
    app.dependency_overrides[get_db] = lambda: db
    response = client.post("/api/signal-reviews", json={
        "scanner_event_id": 999999,
        "verdict": "confirmed",
    })
    app.dependency_overrides.clear()

    assert response.status_code == 404


def test_create_review_invalid_verdict(db: Session):
    event_id = _get_first_event_id(db)

    app.dependency_overrides[get_db] = lambda: db
    response = client.post("/api/signal-reviews", json={
        "scanner_event_id": event_id,
        "verdict": "maybe",
    })
    app.dependency_overrides.clear()

    assert response.status_code == 422


def test_list_reviews_by_scanner_type(db: Session):
    event_id = _get_first_event_id(db)
    event = db.query(ScannerEvent).filter(ScannerEvent.id == event_id).first()
    scanner_type = event.scanner_type

    from app.models.signal_review import SignalReview
    review = SignalReview(scanner_event_id=event_id, verdict="confirmed")
    db.add(review)
    db.flush()

    app.dependency_overrides[get_db] = lambda: db
    response = client.get(f"/api/signal-reviews?scanner_type={scanner_type}")
    app.dependency_overrides.clear()

    assert response.status_code == 200
    data = response.json()
    assert len(data) >= 1
    assert all(r["scanner_type"] == scanner_type for r in data)


def test_list_reviews_liquidity_hunt_alias(db: Session):
    # seed_scanner_events creates liquidity_hunt_pre events; querying with
    # the 'liquidity_hunt' umbrella alias must return them
    seed_scanner_events(db)
    lh_event = (
        db.query(ScannerEvent)
        .filter(ScannerEvent.scanner_type == "liquidity_hunt_pre")
        .first()
    )
    from app.models.signal_review import SignalReview
    review = SignalReview(scanner_event_id=lh_event.id, verdict="confirmed")
    db.add(review)
    db.flush()

    app.dependency_overrides[get_db] = lambda: db
    response = client.get("/api/signal-reviews?scanner_type=liquidity_hunt")
    app.dependency_overrides.clear()

    assert response.status_code == 200
    data = response.json()
    assert len(data) >= 1
    assert all(r["scanner_type"] in ("liquidity_hunt", "liquidity_hunt_pre", "liquidity_hunt_post") for r in data)


def test_list_reviews_missing_scanner_type(db: Session):
    app.dependency_overrides[get_db] = lambda: db
    response = client.get("/api/signal-reviews")
    app.dependency_overrides.clear()

    assert response.status_code == 422
```

### Step 4.2 — Verify tests fail

```bash
docker-compose exec backend python -m pytest tests/api/test_signal_reviews.py -x -v 2>&1 | head -30
# Expected: ImportError or 404 — router doesn't exist yet
```

### Step 4.3 — Create `backend/app/routers/signal_reviews.py`

```python
"""
Signal reviews router — POST/GET /api/signal-reviews.
"""
from datetime import date
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models.scanner_event import ScannerEvent
from app.models.signal_review import SignalReview
from app.schemas.signal_review import SignalReviewCreate, SignalReviewResponse

router = APIRouter(prefix="/api/signal-reviews", tags=["signal-reviews"])


@router.post("", response_model=SignalReviewResponse, status_code=201)
def create_signal_review(payload: SignalReviewCreate, db: Session = Depends(get_db)):
    event = db.query(ScannerEvent).filter(ScannerEvent.id == payload.scanner_event_id).first()
    if not event:
        raise HTTPException(status_code=404, detail="ScannerEvent not found")

    review = SignalReview(
        scanner_event_id=payload.scanner_event_id,
        verdict=payload.verdict,
        reject_reason=payload.reject_reason,
        notes=payload.notes,
        enhance_suggestion=payload.enhance_suggestion,
    )
    db.add(review)
    db.commit()
    db.refresh(review)
    return review


@router.get("", response_model=List[SignalReviewResponse])
def list_signal_reviews(
    scanner_type: str = Query(...),
    start_date: Optional[date] = Query(None),
    end_date: Optional[date] = Query(None),
    db: Session = Depends(get_db),
):
    query = (
        db.query(SignalReview, ScannerEvent.ticker, ScannerEvent.event_date, ScannerEvent.scanner_type)
        .join(ScannerEvent, SignalReview.scanner_event_id == ScannerEvent.id)
    )
    # Mirror the liquidity_hunt alias expansion from GET /api/scanner/results
    if scanner_type == "liquidity_hunt":
        query = query.filter(ScannerEvent.scanner_type.in_(["liquidity_hunt", "liquidity_hunt_pre", "liquidity_hunt_post"]))
    else:
        query = query.filter(ScannerEvent.scanner_type == scanner_type)
    if start_date:
        query = query.filter(ScannerEvent.event_date >= start_date)
    if end_date:
        query = query.filter(ScannerEvent.event_date <= end_date)

    rows = query.order_by(ScannerEvent.event_date, ScannerEvent.ticker).all()

    results = []
    for review, ticker, event_date, stype in rows:
        results.append(SignalReviewResponse(
            id=review.id,
            scanner_event_id=review.scanner_event_id,
            verdict=review.verdict,
            reject_reason=review.reject_reason,
            notes=review.notes,
            enhance_suggestion=review.enhance_suggestion,
            reviewed_at=review.reviewed_at,
            reviewed_by=review.reviewed_by,
            ticker=ticker,
            event_date=str(event_date),
            scanner_type=stype,
        ))
    return results
```

### Step 4.4 — Register the router

In `backend/app/routers/__init__.py`, add:

```python
from app.routers.signal_reviews import router as signal_reviews_router
```

Add `"signal_reviews_router"` to `__all__`.

In `backend/app/main.py`, add to the import line:

```python
from app.routers import ..., signal_reviews_router
```

And in the `include_router` block:

```python
    app.include_router(signal_reviews_router)
```

### Step 4.5 — Verify tests pass

```bash
docker-compose exec backend python -m pytest tests/api/test_signal_reviews.py -v
# Expected: 8 passed
```

### Step 4.6 — Validate live

```bash
docker-compose logs backend --tail=5  # confirm reload

# Get a real event ID
EVENT_ID=$(curl -s "http://localhost:8000/api/scanner/results?limit=1" | python3 -c "import sys,json; print(json.load(sys.stdin)[0]['id'])" 2>/dev/null || echo "1")
echo "Using event_id: $EVENT_ID"

curl -s -X POST http://localhost:8000/api/scanner/results/  # just confirm 200

curl -s -X POST http://localhost:8000/api/signal-reviews \
  -H "Content-Type: application/json" \
  -d "{\"scanner_event_id\": $EVENT_ID, \"verdict\": \"confirmed\"}" | python3 -m json.tool

curl -s "http://localhost:8000/api/signal-reviews?scanner_type=pre_market_volume_spike" | python3 -m json.tool
```

### Step 4.7 — Commit

```bash
git add backend/app/routers/signal_reviews.py backend/app/routers/__init__.py backend/app/main.py backend/tests/api/test_signal_reviews.py backend/app/schemas/signal_review.py
git commit -m "feat(api): add POST/GET /api/signal-reviews endpoints"
```

---

## Task 5: Wire `?date=` query param in StockDetailPage

**Files:** `frontend/src/pages/StockDetailPage.tsx`  
**Time:** ~10 min

### Step 5.1 — Understand existing wiring

`StockDetailPage.tsx` already has:
- `const [highlightDate, setHighlightDate] = React.useState<string | undefined>(undefined);`
- This is passed down as a prop to the `Chart` component → `StockChart` component
- `StockChart` already calls `timeScale.setVisibleRange()` when `highlightDate` changes

The only change needed is to initialise `highlightDate` from the `?date=` URL param on mount.

**Note on visible range:** The existing `StockChart.tsx` uses a ±30 calendar day window when `highlightDate` is set (via `setVisibleRange`). The spec says ±5 trading days (~7 calendar days). The ±30 day window is broader — it satisfies the spec (the target date will be visible and centred) but shows more context than specified. This is acceptable without further changes to `StockChart.tsx`.

### Step 5.2 — Implement

At the top of `StockDetailPage.tsx`, add `useSearchParams` to the `react-router-dom` import:

```typescript
import { useParams, Link, useSearchParams } from 'react-router-dom';
```

Inside the `StockDetailPage` component body, after `const { ticker } = useParams...`, add:

```typescript
  const [searchParams] = useSearchParams();
```

Change the `highlightDate` initial state from `undefined` to the URL param:

```typescript
  const [highlightDate, setHighlightDate] = React.useState<string | undefined>(
    searchParams.get('date') ?? undefined
  );
```

### Step 5.3 — TypeScript check

```bash
cd frontend && npx tsc --noEmit
# Expected: no errors
```

### Step 5.4 — Browser verify

```bash
# Start frontend if not running
cd frontend && npm run dev &

# Open in browser:
# http://localhost:3333/stock/AAPL?date=2025-01-15
# Chart should center on Jan 15, 2025 with ±5 trading days visible
```

### Step 5.5 — Commit

```bash
git add frontend/src/pages/StockDetailPage.tsx
git commit -m "feat(frontend): wire ?date= query param to chart highlight in StockDetailPage"
```

---

## Task 6: Create `/validate-scanner` skill

**Files:** `.claude/skills/validate-scanner/SKILL.md` (new)  
**Time:** ~30 min

### Step 6.1 — Create `.claude/skills/validate-scanner/SKILL.md`

```markdown
---
name: validate-scanner
description: |
  Guided day-by-day review of scanner signals against real market data. Walks through
  one trading day at a time, presents each signal with indicator values and a chart URL,
  accepts confirm/reject/enhance/skip/quit verdicts, persists verdicts to signal_reviews
  DB table, and generates a summary report. Also handles /validate-scanner report for
  on-demand reporting from prior sessions.
argument-hint: "<scanner_type> [start_date] [end_date] | report"
---

# /validate-scanner

Interactive QA skill for scanner output. Reviews signals one trading day at a time.

## Invocation

```
/validate-scanner <scanner_type> [start_date] [end_date]
/validate-scanner report
```

**Known scanner types:** `pre_market_volume_spike`, `oversold_bounce`, `liquidity_hunt`
(alias for `liquidity_hunt_pre` + `liquidity_hunt_post`), `live_volume_spike`, `live_price_move`

**Live types** (`live_volume_spike`, `live_price_move`) produce events only during live
sessions and will likely return no historical results — warn the user if selected.

---

## Execution Steps

### Phase 1: Parse Arguments

1. Parse skill args. If `args[0]` is `"report"`, jump to **Phase 5: Report**.
2. If `scanner_type` is missing, display this menu and prompt:
   ```
   Known scanner types:
     1. pre_market_volume_spike
     2. oversold_bounce
     3. liquidity_hunt  (covers liquidity_hunt_pre + liquidity_hunt_post)
     4. live_volume_spike  ⚠️  historical events unlikely
     5. live_price_move    ⚠️  historical events unlikely
   Enter scanner type:
   ```
3. Validate `scanner_type` is in the known set. Reject unknown types with an error.
4. If `start_date` or `end_date` is missing, prompt:
   ```
   Start date (YYYY-MM-DD):
   End date   (YYYY-MM-DD):
   ```
5. Prompt for a universe_id to enable live re-scan in the enhance flow:
   ```
   Universe ID for re-scan (optional — press Enter to skip live re-scan):
   ```
   Store as `session_universe_id` (None if skipped). When None, the enhance flow will record suggestions but skip the live PATCH + re-scan step.
6. If `scanner_type` is `liquidity_hunt`, internally expand to query for
   `liquidity_hunt_pre` AND `liquidity_hunt_post` by using the existing API alias
   (`GET /api/scanner/results?scanner_type=liquidity_hunt` — the backend handles expansion).

---

### Phase 2: Load or Create Cursor

The cursor file path is: `Docs/scanner-validation/{scanner_type}_progress.json`

**If the file exists AND `scanner_type`/`start_date`/`end_date` match:**
- Load it and resume from `current_day` at `current_signal_index`.
- Print: `Resuming from {current_day} (signal {current_signal_index + 1})…`

**If the file exists but date range differs:**
- Show the existing session info and ask:
  ```
  Found existing session: {existing_start} → {existing_end} (last day: {current_day})
  New range requested:    {start_date} → {end_date}
  [r] Resume existing session
  [n] Start fresh (existing progress preserved in DB)
  ```
- If `n`, overwrite the cursor file with the new session.

**If no file exists:**
- Create the cursor file:
  ```json
  {
    "scanner_type": "<scanner_type>",
    "start_date": "<start_date>",
    "end_date": "<end_date>",
    "days_completed": [],
    "current_day": "<start_date>",
    "current_signal_index": 0,
    "enhance_suggestions": []
  }
  ```

---

### Phase 3: Day Loop

Enumerate trading days in `[start_date, end_date]`:
- Skip Saturdays and Sundays.
- Skip days in the `market_holidays` table: query
  `GET /api/system/market-holidays` if that endpoint exists;
  otherwise query the DB directly via a bash command:
  ```bash
  docker-compose exec backend python -c "
  from app.core.database import SessionLocal
  from app.models.market_holiday import MarketHoliday
  db = SessionLocal()
  holidays = [str(h.date) for h in db.query(MarketHoliday).all()]
  db.close()
  print(' '.join(holidays))
  "
  ```
  Store the list at session start; skip any day that appears in it.

For each trading day **starting at `current_day`**:

#### 3a. Fetch signals for the day

```bash
curl -s "http://localhost:8000/api/scanner/results?scanner_type={scanner_type}&start_date={day}&end_date={day}&limit=200" | python3 -m json.tool
```

If the array is empty, print:
```
── {day} — No signals ──
```
Update cursor: mark day complete, advance `current_day`. Save cursor JSON. Continue.

#### 3b. Signal loop

For each event in the array, starting at `current_signal_index`:

**Print the signal block:**
```
─────────────────────────────────────────────────────────────
{ticker}  │  {event_date}  │  {scanner_type}  │  {severity.upper()}
Prior close: ${previous_close}   Open: ${opening_price}   ({gap_pct:+.1f}%)

Indicators:
{for each key, value in event["indicators"].items()}
  {key}: {value}

Criteria met:
{for each key, value in event["criteria_met"].items()}
  {key}: {"✓" if value else "✗"}
```

Then fetch outcome data:
```bash
curl -s "http://localhost:8000/api/outcomes/event/{event_id}" | python3 -m json.tool
```
If `summary` is not null, print:
```
Outcome:  MFE: {mfe_pct:+.1f}% at {mfe_interval}  │  MAE: {mae_pct:+.1f}%  │  EOD: {eod_pct:+.1f}%
```
Otherwise print: `Outcome: not yet tracked`

Print the chart URL:
```
Chart:  http://localhost:3333/stock/{ticker}?date={event_date}
─────────────────────────────────────────────────────────────
Signal {signal_idx + 1}/{total_signals} on {day}
```

**Prompt the user:**
```
[c] confirm   [r] reject <reason>   [e] enhance   [s] skip   [q] quit
Verdict: _
```

**Handle input:**

| Input | Action |
|-------|--------|
| `c` | Write `verdict=confirmed` to DB (POST /api/signal-reviews). Advance index. |
| `r noise` / `r too_late` / `r stale_data` / `r split_artifact` / `r threshold_too_loose` / `r other` | Write `verdict=rejected, reject_reason=<reason>`. Advance. |
| `r` (no reason) | Prompt: `Reason [noise/too_late/stale_data/split_artifact/threshold_too_loose/other]: ` then proceed as above. |
| `e` | Run enhance flow (see §3c). Advance. |
| `s` | Skip — do NOT write to DB. Advance index. |
| `q` | Save cursor, print session summary so far, exit. |

**After each verdict (except skip/quit), POST to DB:**
```bash
curl -s -X POST http://localhost:8000/api/signal-reviews \
  -H "Content-Type: application/json" \
  -d '{
    "scanner_event_id": {event_id},
    "verdict": "{verdict}",
    "reject_reason": "{reject_reason_or_null}",
    "notes": "{notes_or_null}",
    "enhance_suggestion": {enhance_suggestion_or_null}
  }' | python3 -m json.tool
```

**Save cursor JSON after every verdict** (not just at day end):
```json
{
  "scanner_type": "...",
  "start_date": "...",
  "end_date": "...",
  "days_completed": ["2025-01-02", ...],
  "current_day": "2025-01-06",
  "current_signal_index": 3,
  "enhance_suggestions": [...]
}
```

#### 3c. Enhance flow

When the user selects `e`:

1. Ask: `What would you like to improve? (free text description):`
2. Determine whether the threshold is `SystemConfig`-backed or hardcoded:

   **SystemConfig-backed thresholds** (live-patchable):
   | Key | Description |
   |-----|-------------|
   | `timesfm_fallback_multiplier` | Volume multiplier (default 4.0) |
   | `timesfm_anomaly_threshold` | Score cutoff (default 2.0) |
   | `timesfm_min_history_bars` | Min history bars (default 30) |
   | `timesfm_enabled` | Use ML vs static multiplier |

   If the user's description mentions one of these, proceed with live-patch:
   - Get current value: `curl -s http://localhost:8000/api/system/config | python3 -m json.tool`
   - Ask: `Proposed value for {key} (current: {current_value}):`
   - Apply: `curl -s -X PATCH http://localhost:8000/api/system/config -H "Content-Type: application/json" -d '{"<key>": <value>}'`
   - If `session_universe_id` is set, re-run that day:
     ```bash
     curl -s -X POST http://localhost:8000/api/scanner/run \
       -H "Content-Type: application/json" \
       -d '{"universe_id": {session_universe_id}, "start_date": "{day}", "end_date": "{day}"}'
     ```
     Poll status: `curl -s http://localhost:8000/api/scanner/runs/{scan_id}/status` every 3s until `status == "completed"`.
     Fetch updated results and show before/after event counts.
   - If `session_universe_id` is None, print: `Re-scan skipped (no universe_id provided at session start). Config patched — run a manual scan to see the effect.`
   - Record in `enhance_suggestions` array in cursor:
     ```json
     {"type": "systemconfig", "key": "timesfm_fallback_multiplier",
      "old_value": "4.0", "new_value": "3.5", "day": "2025-01-06",
      "before_events": 12, "after_events": 8}
     ```

   **Hardcoded thresholds** (suggestion-only):
   - Ask: `Which threshold? (e.g. pre_market_volume, avg_volume_20d, rsi_threshold):`
   - Ask: `Current value (from scanner.py):`
   - Ask: `Proposed value:`
   - Ask: `Rationale:`
   - Record in cursor `enhance_suggestions`:
     ```json
     {"type": "hardcoded", "threshold": "pre_market_volume",
      "current_value": "100000", "proposed_value": "200000",
      "rationale": "Too many noise signals in low-float stocks",
      "file": "backend/app/services/scanner.py", "line_hint": "search for 100000"}
     ```
   - Print: `Suggestion recorded. Will appear in session summary.`

3. Write `verdict=enhanced` with `enhance_suggestion` JSON to DB.

#### 3d. Day completion

After all signals for a day are processed, print a day summary:
```
── Day complete: {day} ──
  {n_confirmed} confirmed, {n_rejected} rejected, {n_enhanced} enhanced, {n_skipped} skipped
  Top reject reason: {most_common_reason or "n/a"}
```

Mark day complete in cursor: add to `days_completed`, set `current_day` to next trading day, reset `current_signal_index` to 0. Save cursor.

---

### Phase 4: Session Completion

When all days in the range are done (or the user quits):

Print:
```
════════════════════════════════════════
Session complete. Generating report…
════════════════════════════════════════
```

Then run **Phase 5: Report**.

---

### Phase 5: Report

1. Read cursor from `Docs/scanner-validation/{scanner_type}_progress.json` if it exists.
   - If invoked as `/validate-scanner report` with no scanner_type, list available `*.json` files in `Docs/scanner-validation/` and prompt the user to select one.

2. Fetch all reviews from DB:
   ```bash
   curl -s "http://localhost:8000/api/signal-reviews?scanner_type={scanner_type}&start_date={start_date}&end_date={end_date}" | python3 -m json.tool
   ```

3. Print the report:
   ```
   ════════════════════════════════════════
   SCANNER VALIDATION REPORT
   Type:  {scanner_type}
   Range: {start_date} → {end_date}
   ════════════════════════════════════════

   Days reviewed:  {len(days_completed)}
   Total signals:  {total}
   ─────────────────────────────────────────
   Confirmed:      {n_confirmed} ({pct:.0%})
   Rejected:       {n_rejected} ({pct:.0%})
   Enhanced:       {n_enhanced} ({pct:.0%})
   Skipped:        {n_skipped} (not in DB)
   ─────────────────────────────────────────

   Top Rejection Reasons:
   {ranked list of reason: count}

   Enhance Suggestions ({n_hardcoded} hardcoded, {n_systemconfig} applied):
   {for each suggestion: threshold, current→proposed, rationale, affected_days}

   ════════════════════════════════════════
   ```

---

## Error Handling

- If the backend is unreachable: print `Backend not responding. Is docker-compose up?` and exit.
- If an event has no `indicators` key: treat as empty dict; print `(no indicators)`.
- If outcome fetch returns 404: treat as `Outcome: not yet tracked`.
- If `Docs/scanner-validation/` directory doesn't exist: create it with `mkdir -p Docs/scanner-validation`.
```

### Step 6.2 — Verify skill is discoverable

Restart Claude Code in the project. The skill should appear in the available skills list as `validate-scanner`. Invoke with:
```
/validate-scanner pre_market_volume_spike 2025-01-15 2025-01-15
```

Verify the skill:
- Loads or creates the cursor JSON
- Fetches signals from the API
- Prints the signal block format
- Prompts for verdict

### Step 6.3 — Commit

```bash
git add .claude/skills/validate-scanner/SKILL.md
git commit -m "feat(skill): add /validate-scanner skill for guided signal QA"
```

---

## Task 7: Progress directory setup

**Files:** `Docs/scanner-validation/.gitkeep`, `Docs/scanner-validation/.gitignore`  
**Time:** ~5 min

### Step 7.1 — Create directory and files

```bash
mkdir -p Docs/scanner-validation

cat > Docs/scanner-validation/.gitignore << 'EOF'
# Ignore runtime cursor files — verdicts are canonical in the DB
*.json
EOF

touch Docs/scanner-validation/.gitkeep
```

### Step 7.2 — Commit

```bash
git add Docs/scanner-validation/.gitkeep Docs/scanner-validation/.gitignore
git commit -m "chore: add Docs/scanner-validation directory for skill cursor files"
```

---

## Full Run Sequence (copy-paste order)

```bash
# Task 1
docker-compose exec backend python -m pytest tests/api/test_scanner.py::test_results_filter_by_start_date -x
# [edit scanner.py]
docker-compose exec backend python -m pytest tests/api/test_scanner.py -k "date" -v
git add backend/app/routers/scanner.py backend/tests/api/test_scanner.py && git commit -m "feat(scanner): add start_date/end_date filter to GET /api/scanner/results"

# Task 2
# [create signal_review.py, edit scanner_event.py, edit __init__.py]
docker-compose exec backend python -m alembic revision --autogenerate -m "add_signal_reviews"
docker-compose exec backend python -m alembic upgrade head
git add backend/app/models/ backend/app/alembic/versions/ && git commit -m "feat(model): add SignalReview model and migration"

# Task 3
# [create schemas/signal_review.py]
git add backend/app/schemas/signal_review.py && git commit -m "feat(schema): add SignalReview Pydantic schemas"

# Task 4
docker-compose exec backend python -m pytest tests/api/test_signal_reviews.py -x
# [create routers/signal_reviews.py, edit routers/__init__.py, edit main.py]
docker-compose exec backend python -m pytest tests/api/test_signal_reviews.py -v
git add backend/app/routers/ backend/app/main.py backend/tests/api/test_signal_reviews.py && git commit -m "feat(api): add POST/GET /api/signal-reviews endpoints"

# Task 5
# [edit StockDetailPage.tsx]
cd frontend && npx tsc --noEmit && cd ..
git add frontend/src/pages/StockDetailPage.tsx && git commit -m "feat(frontend): wire ?date= query param to chart highlight in StockDetailPage"

# Task 6
# [create .claude/skills/validate-scanner/SKILL.md]
git add .claude/skills/validate-scanner/ && git commit -m "feat(skill): add /validate-scanner skill for guided signal QA"

# Task 7
mkdir -p Docs/scanner-validation
echo "*.json" > Docs/scanner-validation/.gitignore
touch Docs/scanner-validation/.gitkeep
git add Docs/scanner-validation/ && git commit -m "chore: add Docs/scanner-validation directory for skill cursor files"
```

---

## Acceptance Criteria Mapping

| Spec requirement | Plan task |
|-----------------|-----------|
| `/validate-scanner` launchable from Claude Code | Task 6 |
| Walks one day at a time with signal context | Task 6 (Phase 3) |
| confirm/reject/enhance verdicts | Task 6 (§3b) |
| Enhance: live-patch SystemConfig + re-scan | Task 6 (§3c) |
| Progress persists across sessions | Task 6 (Phase 2) |
| Verdicts to `signal_reviews` DB | Tasks 2, 3, 4 |
| Summary report | Task 6 (Phase 5) |
| Works for any scanner type | Task 6 |
| `GET /api/scanner/results` date params | Task 1 |
| `StockDetailPage` `?date=` URL param | Task 5 |
