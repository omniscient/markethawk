# Human Signal Review (Issue #6) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add frontend review controls (confirm/reject/uncertain) on scanner results, consolidate backend review endpoints under `/api/scanner/`, and add a review stats card to the Scanner page.

**Architecture:** Evolve the existing `signal_reviews` table and `SignalReview` model (built for issue #5's `/validate-scanner` skill). Remove the standalone `signal_reviews` router, add three new endpoints to the scanner router. Build a `ReviewControls` component for inline verdict buttons and a `SignalReviewStats` card. The existing one-to-many relationship is preserved; the frontend shows the latest review per event.

**Tech Stack:** FastAPI, SQLAlchemy, Pydantic, React 18, TypeScript, React Query, Tailwind CSS, Lucide icons.

---

### Task 1: Add `uncertain` verdict and create `SignalReviewRequest` schema

**Files:**
- Modify: `backend/app/schemas/signal_review.py`

- [ ] **Step 1: Add `uncertain` to VALID_VERDICTS**

In `backend/app/schemas/signal_review.py`, change:

```python
VALID_VERDICTS = {"confirmed", "rejected", "enhanced"}
```

to:

```python
VALID_VERDICTS = {"confirmed", "rejected", "enhanced", "uncertain"}
```

- [ ] **Step 2: Add `SignalReviewRequest` schema**

Add this class after `SignalReviewCreate` in `backend/app/schemas/signal_review.py`. This schema is used by the new UUID-based endpoint where `scanner_event_id` comes from the URL, not the body:

```python
class SignalReviewRequest(BaseModel):
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
```

- [ ] **Step 3: Add `SignalReviewStatsResponse` schema**

Add at the end of `backend/app/schemas/signal_review.py`:

```python
class SignalReviewStatsResponse(BaseModel):
    total_events: int
    reviewed_count: int
    acceptance_rate: float
    by_scanner_type: List[Dict[str, Any]]
    top_rejection_reasons: List[Dict[str, Any]]
```

This requires adding `List` and `Dict` to the existing typing imports (both are already imported in the file).

- [ ] **Step 4: Commit**

```bash
git add backend/app/schemas/signal_review.py
git commit -m "feat(signal-review): add uncertain verdict and new request/stats schemas"
```

---

### Task 2: Add `latest_review` property to `ScannerEvent` model

**Files:**
- Modify: `backend/app/models/scanner_event.py`
- Modify: `backend/app/schemas/event.py`

- [ ] **Step 1: Add `latest_review` property to the model**

In `backend/app/models/scanner_event.py`, add a property after the `reviews` relationship (line 50):

```python
    @property
    def latest_review(self):
        if not self.reviews:
            return None
        return max(self.reviews, key=lambda r: r.reviewed_at)
```

- [ ] **Step 2: Add `latest_review` field to `ScannerEventResponse`**

In `backend/app/schemas/event.py`, first add the import at the top:

```python
from app.schemas.signal_review import SignalReviewResponse
```

Then add this field to `ScannerEventResponse` after `updated_at`:

```python
    latest_review: Optional[SignalReviewResponse] = None
```

This also requires adding `Optional` to the imports — check if it's already there (it is: `from typing import Dict, Any, Optional, List`).

- [ ] **Step 3: Add `joinedload` to `get_scanner_results` query**

In `backend/app/routers/scanner.py`, add to the imports at the top:

```python
from sqlalchemy.orm import Session, joinedload
```

Wait — `Session` is already imported from `sqlalchemy.orm`. Change the existing import:

```python
from sqlalchemy.orm import Session
```

to:

```python
from sqlalchemy.orm import Session, joinedload
```

Then in the `get_scanner_results` function (line 356), change:

```python
    query = db.query(ScannerEvent)
```

to:

```python
    query = db.query(ScannerEvent).options(joinedload(ScannerEvent.reviews))
```

- [ ] **Step 4: Commit**

```bash
git add backend/app/models/scanner_event.py backend/app/schemas/event.py backend/app/routers/scanner.py
git commit -m "feat(signal-review): embed latest_review in scanner results response"
```

---

### Task 3: Add review endpoints to scanner router

**Files:**
- Modify: `backend/app/routers/scanner.py`

- [ ] **Step 1: Add imports to scanner router**

In `backend/app/routers/scanner.py`, add these imports after the existing imports:

```python
from app.models.signal_review import SignalReview
from app.schemas.signal_review import SignalReviewRequest, SignalReviewResponse, SignalReviewStatsResponse
```

Also add `Response` to the FastAPI imports — change:

```python
from fastapi import APIRouter, Depends, HTTPException, Query, WebSocket, WebSocketDisconnect
```

to:

```python
from fastapi import APIRouter, Depends, HTTPException, Query, Response, WebSocket, WebSocketDisconnect
```

- [ ] **Step 2: Add POST /events/{event_uuid}/review**

Add this endpoint at the end of `backend/app/routers/scanner.py` (after the `clear_scanner_events` function):

```python
@router.post("/events/{event_uuid}/review", response_model=SignalReviewResponse, status_code=201)
def create_event_review(
    event_uuid: str,
    payload: SignalReviewRequest,
    db: Session = Depends(get_db),
):
    try:
        parsed_uuid = uuid.UUID(event_uuid)
    except ValueError:
        raise HTTPException(status_code=400, detail="invalid event UUID")

    event = db.query(ScannerEvent).filter(ScannerEvent.uuid == parsed_uuid).first()
    if not event:
        raise HTTPException(status_code=404, detail="ScannerEvent not found")

    review = SignalReview(
        scanner_event_id=event.id,
        verdict=payload.verdict,
        reject_reason=payload.reject_reason,
        notes=payload.notes,
        enhance_suggestion=payload.enhance_suggestion,
    )
    db.add(review)
    db.commit()
    db.refresh(review)
    return review
```

- [ ] **Step 3: Add GET /events/reviews**

Add this endpoint after the POST endpoint. Note: this must be defined **before** any route that would match `/events/{event_uuid}` to avoid route conflicts, but since `/events/reviews` is a static path and `/events/{event_uuid}/review` has a different suffix, FastAPI handles this correctly. Place it right after the POST:

```python
@router.get("/events/reviews", response_model=List[SignalReviewResponse])
def list_event_reviews(
    scanner_type: str = Query(...),
    start_date: Optional[date] = Query(None),
    end_date: Optional[date] = Query(None),
    verdict: Optional[str] = Query(None),
    db: Session = Depends(get_db),
):
    query = (
        db.query(SignalReview, ScannerEvent.ticker, ScannerEvent.event_date, ScannerEvent.scanner_type)
        .join(ScannerEvent, SignalReview.scanner_event_id == ScannerEvent.id)
    )
    if scanner_type == "liquidity_hunt":
        query = query.filter(ScannerEvent.scanner_type.in_(["liquidity_hunt", "liquidity_hunt_pre", "liquidity_hunt_post"]))
    else:
        query = query.filter(ScannerEvent.scanner_type == scanner_type)
    if start_date:
        query = query.filter(ScannerEvent.event_date >= start_date)
    if end_date:
        query = query.filter(ScannerEvent.event_date <= end_date)
    if verdict:
        query = query.filter(SignalReview.verdict == verdict)

    rows = query.order_by(ScannerEvent.event_date, ScannerEvent.ticker).all()

    return [
        SignalReviewResponse(
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
        )
        for review, ticker, event_date, stype in rows
    ]
```

- [ ] **Step 4: Add GET /reviews/stats**

Add this endpoint after the GET list endpoint:

```python
@router.get("/reviews/stats", response_model=SignalReviewStatsResponse)
def get_review_stats(
    scanner_type: Optional[str] = Query(None),
    start_date: Optional[date] = Query(None),
    end_date: Optional[date] = Query(None),
    db: Session = Depends(get_db),
):
    from sqlalchemy import func, distinct

    event_q = db.query(func.count(ScannerEvent.id))
    review_q = db.query(SignalReview).join(ScannerEvent, SignalReview.scanner_event_id == ScannerEvent.id)

    if scanner_type:
        if scanner_type == "liquidity_hunt":
            variants = ["liquidity_hunt", "liquidity_hunt_pre", "liquidity_hunt_post"]
            event_q = event_q.filter(ScannerEvent.scanner_type.in_(variants))
            review_q = review_q.filter(ScannerEvent.scanner_type.in_(variants))
        else:
            event_q = event_q.filter(ScannerEvent.scanner_type == scanner_type)
            review_q = review_q.filter(ScannerEvent.scanner_type == scanner_type)
    if start_date:
        event_q = event_q.filter(ScannerEvent.event_date >= start_date)
        review_q = review_q.filter(ScannerEvent.event_date >= start_date)
    if end_date:
        event_q = event_q.filter(ScannerEvent.event_date <= end_date)
        review_q = review_q.filter(ScannerEvent.event_date <= end_date)

    total_events = event_q.scalar() or 0
    reviewed_count = (
        review_q.with_entities(func.count(distinct(SignalReview.scanner_event_id))).scalar() or 0
    )

    confirmed_count = review_q.filter(SignalReview.verdict == "confirmed").count()
    rejected_count = review_q.filter(SignalReview.verdict == "rejected").count()
    denominator = confirmed_count + rejected_count
    acceptance_rate = round(confirmed_count / denominator, 3) if denominator > 0 else 0.0

    by_type_rows = (
        review_q.with_entities(
            ScannerEvent.scanner_type,
            SignalReview.verdict,
            func.count(SignalReview.id),
        )
        .group_by(ScannerEvent.scanner_type, SignalReview.verdict)
        .all()
    )
    type_map: dict = {}
    for stype, verdict, cnt in by_type_rows:
        if stype not in type_map:
            type_map[stype] = {"scanner_type": stype, "total": 0, "confirmed": 0, "rejected": 0, "uncertain": 0, "enhanced": 0}
        type_map[stype]["total"] += cnt
        if verdict in type_map[stype]:
            type_map[stype][verdict] += cnt

    reason_rows = (
        review_q.filter(SignalReview.reject_reason.isnot(None))
        .with_entities(SignalReview.reject_reason, func.count(SignalReview.id))
        .group_by(SignalReview.reject_reason)
        .order_by(func.count(SignalReview.id).desc())
        .limit(5)
        .all()
    )

    return SignalReviewStatsResponse(
        total_events=total_events,
        reviewed_count=reviewed_count,
        acceptance_rate=acceptance_rate,
        by_scanner_type=list(type_map.values()),
        top_rejection_reasons=[{"reason": r, "count": c} for r, c in reason_rows],
    )
```

- [ ] **Step 5: Commit**

```bash
git add backend/app/routers/scanner.py
git commit -m "feat(signal-review): add review endpoints to scanner router"
```

---

### Task 4: Remove old signal_reviews router

**Files:**
- Modify: `backend/app/routers/__init__.py`
- Modify: `backend/app/main.py`
- Delete: `backend/app/routers/signal_reviews.py`

- [ ] **Step 1: Remove from routers/__init__.py**

In `backend/app/routers/__init__.py`, remove:

```python
from app.routers.signal_reviews import router as signal_reviews_router
```

And remove `"signal_reviews_router"` from the `__all__` list.

- [ ] **Step 2: Remove from main.py**

In `backend/app/main.py` line 20, remove `signal_reviews_router` from the import:

```python
from app.routers import health_router, scanner_router, universe_router, stocks_router, news_router, live_data_router, journal_router, system_router, futures_router, alerts_router, watchlist_router, auto_trading_router, outcomes_router, signal_reviews_router
```

becomes:

```python
from app.routers import health_router, scanner_router, universe_router, stocks_router, news_router, live_data_router, journal_router, system_router, futures_router, alerts_router, watchlist_router, auto_trading_router, outcomes_router
```

And remove line 184:

```python
    app.include_router(signal_reviews_router)
```

- [ ] **Step 3: Delete the old router file**

```bash
git rm backend/app/routers/signal_reviews.py
```

- [ ] **Step 4: Commit**

```bash
git add backend/app/routers/__init__.py backend/app/main.py
git commit -m "refactor(signal-review): remove standalone signal_reviews router"
```

---

### Task 5: Update tests for new endpoint paths

**Files:**
- Modify: `backend/tests/api/test_signal_reviews.py`

- [ ] **Step 1: Rewrite test file for new endpoints**

Replace the entire contents of `backend/tests/api/test_signal_reviews.py`:

```python
"""
Integration tests for signal review endpoints under /api/scanner/.
"""
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.main import app
from app.core.database import get_db
from app.models.scanner_event import ScannerEvent
from app.models.signal_review import SignalReview
from tests.fixtures.scanner import seed_scanner_events

client = TestClient(app)


def _get_first_event(db: Session) -> ScannerEvent:
    seed_scanner_events(db)
    return db.query(ScannerEvent).first()


def test_create_confirmed_review(db: Session):
    event = _get_first_event(db)
    app.dependency_overrides[get_db] = lambda: db
    response = client.post(f"/api/scanner/events/{event.uuid}/review", json={
        "verdict": "confirmed",
    })
    app.dependency_overrides.clear()
    assert response.status_code == 201
    data = response.json()
    assert data["verdict"] == "confirmed"
    assert data["scanner_event_id"] == event.id


def test_create_uncertain_review(db: Session):
    event = _get_first_event(db)
    app.dependency_overrides[get_db] = lambda: db
    response = client.post(f"/api/scanner/events/{event.uuid}/review", json={
        "verdict": "uncertain",
        "notes": "Need to check chart",
    })
    app.dependency_overrides.clear()
    assert response.status_code == 201
    assert response.json()["verdict"] == "uncertain"


def test_create_rejected_review_requires_reason(db: Session):
    event = _get_first_event(db)
    app.dependency_overrides[get_db] = lambda: db
    response = client.post(f"/api/scanner/events/{event.uuid}/review", json={
        "verdict": "rejected",
    })
    app.dependency_overrides.clear()
    assert response.status_code == 422


def test_create_rejected_review_with_reason(db: Session):
    event = _get_first_event(db)
    app.dependency_overrides[get_db] = lambda: db
    response = client.post(f"/api/scanner/events/{event.uuid}/review", json={
        "verdict": "rejected",
        "reject_reason": "noise",
        "notes": "Volume spike was a data artifact",
    })
    app.dependency_overrides.clear()
    assert response.status_code == 201
    assert response.json()["reject_reason"] == "noise"


def test_create_review_invalid_uuid(db: Session):
    app.dependency_overrides[get_db] = lambda: db
    response = client.post("/api/scanner/events/not-a-uuid/review", json={
        "verdict": "confirmed",
    })
    app.dependency_overrides.clear()
    assert response.status_code == 400


def test_create_review_nonexistent_event(db: Session):
    import uuid
    fake_uuid = str(uuid.uuid4())
    app.dependency_overrides[get_db] = lambda: db
    response = client.post(f"/api/scanner/events/{fake_uuid}/review", json={
        "verdict": "confirmed",
    })
    app.dependency_overrides.clear()
    assert response.status_code == 404


def test_create_review_invalid_verdict(db: Session):
    event = _get_first_event(db)
    app.dependency_overrides[get_db] = lambda: db
    response = client.post(f"/api/scanner/events/{event.uuid}/review", json={
        "verdict": "maybe",
    })
    app.dependency_overrides.clear()
    assert response.status_code == 422


def test_list_reviews_by_scanner_type(db: Session):
    event = _get_first_event(db)
    review = SignalReview(scanner_event_id=event.id, verdict="confirmed")
    db.add(review)
    db.flush()

    app.dependency_overrides[get_db] = lambda: db
    response = client.get(f"/api/scanner/events/reviews?scanner_type={event.scanner_type}")
    app.dependency_overrides.clear()
    assert response.status_code == 200
    data = response.json()
    assert len(data) >= 1
    assert all(r["scanner_type"] == event.scanner_type for r in data)


def test_list_reviews_liquidity_hunt_alias(db: Session):
    seed_scanner_events(db)
    lh_event = (
        db.query(ScannerEvent)
        .filter(ScannerEvent.scanner_type == "liquidity_hunt_pre")
        .first()
    )
    review = SignalReview(scanner_event_id=lh_event.id, verdict="confirmed")
    db.add(review)
    db.flush()

    app.dependency_overrides[get_db] = lambda: db
    response = client.get("/api/scanner/events/reviews?scanner_type=liquidity_hunt")
    app.dependency_overrides.clear()
    assert response.status_code == 200
    data = response.json()
    assert len(data) >= 1


def test_list_reviews_filter_by_verdict(db: Session):
    event = _get_first_event(db)
    db.add(SignalReview(scanner_event_id=event.id, verdict="confirmed"))
    db.add(SignalReview(scanner_event_id=event.id, verdict="rejected", reject_reason="noise"))
    db.flush()

    app.dependency_overrides[get_db] = lambda: db
    response = client.get(f"/api/scanner/events/reviews?scanner_type={event.scanner_type}&verdict=confirmed")
    app.dependency_overrides.clear()
    assert response.status_code == 200
    data = response.json()
    assert all(r["verdict"] == "confirmed" for r in data)


def test_list_reviews_missing_scanner_type(db: Session):
    app.dependency_overrides[get_db] = lambda: db
    response = client.get("/api/scanner/events/reviews")
    app.dependency_overrides.clear()
    assert response.status_code == 422


def test_review_stats(db: Session):
    events = seed_scanner_events(db)
    db.add(SignalReview(scanner_event_id=events[0].id, verdict="confirmed"))
    db.add(SignalReview(scanner_event_id=events[1].id, verdict="rejected", reject_reason="noise"))
    db.add(SignalReview(scanner_event_id=events[2].id, verdict="uncertain"))
    db.flush()

    app.dependency_overrides[get_db] = lambda: db
    response = client.get("/api/scanner/reviews/stats")
    app.dependency_overrides.clear()
    assert response.status_code == 200
    data = response.json()
    assert data["total_events"] > 0
    assert data["reviewed_count"] == 3
    assert 0.0 <= data["acceptance_rate"] <= 1.0
    assert isinstance(data["by_scanner_type"], list)
    assert isinstance(data["top_rejection_reasons"], list)


def test_review_stats_with_scanner_type_filter(db: Session):
    events = seed_scanner_events(db)
    pmvs_events = [e for e in events if e.scanner_type == "pre_market_volume_spike"]
    for e in pmvs_events:
        db.add(SignalReview(scanner_event_id=e.id, verdict="confirmed"))
    db.flush()

    app.dependency_overrides[get_db] = lambda: db
    response = client.get("/api/scanner/reviews/stats?scanner_type=pre_market_volume_spike")
    app.dependency_overrides.clear()
    assert response.status_code == 200
    data = response.json()
    assert data["reviewed_count"] > 0
    assert all(row["scanner_type"] == "pre_market_volume_spike" for row in data["by_scanner_type"])


def test_scanner_results_include_latest_review(db: Session):
    event = _get_first_event(db)
    db.add(SignalReview(scanner_event_id=event.id, verdict="confirmed"))
    db.flush()

    app.dependency_overrides[get_db] = lambda: db
    response = client.get(f"/api/scanner/results?scanner_type={event.scanner_type}")
    app.dependency_overrides.clear()
    assert response.status_code == 200
    data = response.json()
    reviewed = [e for e in data if e.get("latest_review") is not None]
    assert len(reviewed) >= 1
    assert reviewed[0]["latest_review"]["verdict"] == "confirmed"
```

- [ ] **Step 2: Run the tests**

Run: `docker compose exec backend python -m pytest tests/api/test_signal_reviews.py -v`

Expected: all tests pass.

- [ ] **Step 3: Commit**

```bash
git add backend/tests/api/test_signal_reviews.py
git commit -m "test(signal-review): update tests for consolidated scanner endpoints"
```

---

### Task 6: Update validate-scanner skill

**Files:**
- Modify: `.claude/skills/validate-scanner/SKILL.md`

- [ ] **Step 1: Update POST endpoint reference**

In `.claude/skills/validate-scanner/SKILL.md`, find the verdict action table (around line 174) and change:

```
| `c` | Write `verdict=confirmed` to DB (POST /api/signal-reviews). Advance index. |
```

to:

```
| `c` | Write `verdict=confirmed` to DB (POST /api/scanner/events/{event_uuid}/review). Advance index. |
```

- [ ] **Step 2: Update the curl POST command**

Change the curl block (around line 183):

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

to:

```bash
curl -s -X POST http://localhost:8000/api/scanner/events/{event_uuid}/review \
  -H "Content-Type: application/json" \
  -d '{
    "verdict": "{verdict}",
    "reject_reason": "{reject_reason_or_null}",
    "notes": "{notes_or_null}",
    "enhance_suggestion": {enhance_suggestion_or_null}
  }' | python3 -m json.tool
```

Note: the `event_uuid` comes from the scanner results response (`event.uuid`). The `scanner_event_id` field is no longer in the request body.

- [ ] **Step 3: Update the GET reviews curl in Phase 5: Report**

Change the report curl (around line 293):

```bash
curl -s "http://localhost:8000/api/signal-reviews?scanner_type={scanner_type}&start_date={start_date}&end_date={end_date}" | python3 -m json.tool
```

to:

```bash
curl -s "http://localhost:8000/api/scanner/events/reviews?scanner_type={scanner_type}&start_date={start_date}&end_date={end_date}" | python3 -m json.tool
```

- [ ] **Step 4: Commit**

```bash
git add .claude/skills/validate-scanner/SKILL.md
git commit -m "chore(validate-scanner): update endpoints to consolidated /api/scanner/ paths"
```

---

### Task 7: Frontend TypeScript types and API client

**Files:**
- Modify: `frontend/src/api/scanner.ts`

- [ ] **Step 1: Add `SignalReview` type**

In `frontend/src/api/scanner.ts`, add after the `ScannerEvent` interface (after line 27):

```typescript
export interface SignalReview {
  id: number;
  scanner_event_id: number;
  verdict: 'confirmed' | 'rejected' | 'enhanced' | 'uncertain';
  reject_reason: string | null;
  notes: string | null;
  enhance_suggestion: Record<string, unknown> | null;
  reviewed_at: string;
  reviewed_by: string | null;
}

export type RejectionReason = 'too_late' | 'noise' | 'stale_data' | 'split_artifact';

export interface SignalReviewStats {
  total_events: number;
  reviewed_count: number;
  acceptance_rate: number;
  by_scanner_type: Array<{
    scanner_type: string;
    total: number;
    confirmed: number;
    rejected: number;
    uncertain: number;
    enhanced: number;
  }>;
  top_rejection_reasons: Array<{ reason: string; count: number }>;
}
```

- [ ] **Step 2: Add `latest_review` to `ScannerEvent`**

In the `ScannerEvent` interface, add after `updated_at: string;`:

```typescript
  latest_review?: SignalReview | null;
```

- [ ] **Step 3: Add API functions**

Add after the `fetchScannerHistory` function (around line 310):

```typescript
export const submitReview = async (
  eventUuid: string,
  payload: { verdict: string; reject_reason?: string | null; notes?: string | null },
): Promise<SignalReview> => {
  const response = await apiClient.post(`/scanner/events/${eventUuid}/review`, payload);
  return response.data;
};

export const fetchReviewStats = async (params?: {
  scanner_type?: string;
  start_date?: string;
  end_date?: string;
}): Promise<SignalReviewStats> => {
  const response = await apiClient.get('/scanner/reviews/stats', { params });
  return response.data;
};
```

- [ ] **Step 4: Type-check**

Run: `cd frontend && npx tsc --noEmit`

Expected: no errors.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/api/scanner.ts
git commit -m "feat(frontend): add signal review types and API client functions"
```

---

### Task 8: ReviewControls component

**Files:**
- Create: `frontend/src/components/ReviewControls.tsx`

- [ ] **Step 1: Create the component**

Create `frontend/src/components/ReviewControls.tsx`:

```tsx
import React, { useState } from 'react';
import { ThumbsUp, ThumbsDown, HelpCircle, Check, X, Wrench } from 'lucide-react';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { submitReview, SignalReview, RejectionReason } from '../api/scanner';

interface ReviewControlsProps {
  eventUuid: string;
  latestReview: SignalReview | null | undefined;
}

const REJECTION_REASONS: { value: RejectionReason; label: string }[] = [
  { value: 'too_late', label: 'Too Late' },
  { value: 'noise', label: 'Noise' },
  { value: 'stale_data', label: 'Stale Data' },
  { value: 'split_artifact', label: 'Split Artifact' },
];

const ReviewControls: React.FC<ReviewControlsProps> = ({ eventUuid, latestReview }) => {
  const queryClient = useQueryClient();
  const [showRejectPopover, setShowRejectPopover] = useState(false);
  const [rejectReason, setRejectReason] = useState<RejectionReason>('noise');
  const [rejectNotes, setRejectNotes] = useState('');
  const [editing, setEditing] = useState(false);

  const mutation = useMutation({
    mutationFn: (payload: { verdict: string; reject_reason?: string | null; notes?: string | null }) =>
      submitReview(eventUuid, payload),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['scannerResults'] });
      queryClient.invalidateQueries({ queryKey: ['reviewStats'] });
      setShowRejectPopover(false);
      setEditing(false);
    },
  });

  const handleConfirm = (e: React.MouseEvent) => {
    e.stopPropagation();
    mutation.mutate({ verdict: 'confirmed' });
  };

  const handleUncertain = (e: React.MouseEvent) => {
    e.stopPropagation();
    mutation.mutate({ verdict: 'uncertain' });
  };

  const handleRejectClick = (e: React.MouseEvent) => {
    e.stopPropagation();
    setShowRejectPopover(true);
  };

  const handleRejectSubmit = (e: React.MouseEvent) => {
    e.stopPropagation();
    mutation.mutate({
      verdict: 'rejected',
      reject_reason: rejectReason,
      notes: rejectNotes || null,
    });
  };

  const showButtons = !latestReview || editing;

  if (!showButtons && latestReview) {
    const badgeConfig: Record<string, { icon: React.ElementType; color: string; title: string }> = {
      confirmed: { icon: Check, color: 'text-green-400 bg-green-500/20 border-green-500/30', title: 'Confirmed' },
      rejected: { icon: X, color: 'text-red-400 bg-red-500/20 border-red-500/30', title: `Rejected: ${latestReview.reject_reason}` },
      uncertain: { icon: HelpCircle, color: 'text-gray-400 bg-gray-500/20 border-gray-500/30', title: 'Uncertain' },
      enhanced: { icon: Wrench, color: 'text-blue-400 bg-blue-500/20 border-blue-500/30', title: 'Enhanced' },
    };
    const cfg = badgeConfig[latestReview.verdict] || badgeConfig.uncertain;
    const Icon = cfg.icon;

    return (
      <button
        onClick={(e) => { e.stopPropagation(); setEditing(true); }}
        className={`inline-flex items-center px-1.5 py-0.5 rounded border text-xs ${cfg.color} hover:opacity-80 transition-opacity`}
        title={cfg.title}
      >
        <Icon className="h-3 w-3" />
      </button>
    );
  }

  return (
    <div className="relative flex items-center gap-1" onClick={(e) => e.stopPropagation()}>
      <button
        onClick={handleConfirm}
        disabled={mutation.isPending}
        className="p-1 rounded hover:bg-green-500/20 text-gray-500 hover:text-green-400 transition-colors"
        title="Confirm"
      >
        <ThumbsUp className="h-3.5 w-3.5" />
      </button>
      <button
        onClick={handleRejectClick}
        disabled={mutation.isPending}
        className="p-1 rounded hover:bg-red-500/20 text-gray-500 hover:text-red-400 transition-colors"
        title="Reject"
      >
        <ThumbsDown className="h-3.5 w-3.5" />
      </button>
      <button
        onClick={handleUncertain}
        disabled={mutation.isPending}
        className="p-1 rounded hover:bg-gray-500/20 text-gray-500 hover:text-gray-300 transition-colors"
        title="Uncertain"
      >
        <HelpCircle className="h-3.5 w-3.5" />
      </button>

      {showRejectPopover && (
        <div className="absolute right-0 top-full mt-1 z-50 bg-gray-800 border border-gray-700 rounded-lg shadow-xl p-3 w-56">
          <label className="block text-[10px] font-bold text-gray-500 uppercase mb-1">Reason</label>
          <select
            value={rejectReason}
            onChange={(e) => setRejectReason(e.target.value as RejectionReason)}
            className="w-full px-2 py-1 bg-gray-900 border border-gray-700 rounded text-sm text-financial-light mb-2"
            onClick={(e) => e.stopPropagation()}
          >
            {REJECTION_REASONS.map((r) => (
              <option key={r.value} value={r.value}>{r.label}</option>
            ))}
          </select>
          <label className="block text-[10px] font-bold text-gray-500 uppercase mb-1">Notes</label>
          <textarea
            value={rejectNotes}
            onChange={(e) => setRejectNotes(e.target.value)}
            className="w-full px-2 py-1 bg-gray-900 border border-gray-700 rounded text-sm text-financial-light mb-2 resize-none"
            rows={2}
            placeholder="Optional notes..."
            onClick={(e) => e.stopPropagation()}
          />
          <div className="flex gap-2">
            <button
              onClick={handleRejectSubmit}
              disabled={mutation.isPending}
              className="flex-1 px-2 py-1 bg-red-600 text-white text-xs font-bold rounded hover:bg-red-500"
            >
              Reject
            </button>
            <button
              onClick={(e) => { e.stopPropagation(); setShowRejectPopover(false); }}
              className="px-2 py-1 bg-gray-700 text-gray-300 text-xs rounded hover:bg-gray-600"
            >
              Cancel
            </button>
          </div>
        </div>
      )}
    </div>
  );
};

export default ReviewControls;
```

- [ ] **Step 2: Type-check**

Run: `cd frontend && npx tsc --noEmit`

Expected: no errors.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/components/ReviewControls.tsx
git commit -m "feat(frontend): add ReviewControls component with verdict buttons and reject popover"
```

---

### Task 9: Wire ReviewControls into ScannerResults

**Files:**
- Modify: `frontend/src/components/ScannerResults.tsx`

- [ ] **Step 1: Add import**

In `frontend/src/components/ScannerResults.tsx`, add after the existing imports:

```typescript
import ReviewControls from './ReviewControls';
```

- [ ] **Step 2: Add Review column header**

In the `<thead>` section, add a new `<th>` after the Score `SortableHeader` (after line 217):

```tsx
                <th className="py-3 px-4">Review</th>
```

- [ ] **Step 3: Add Review column cell**

In the `<tbody>` row, change the last `<td>` (Score cell, line 260) from having `rounded-r-xl` to not having it, and add a new `<td>` after it:

Change:

```tsx
                  <td className="py-4 px-4 bg-gray-800 rounded-r-xl">
                    <ScoreQualityBadge
                      score={event.signal_quality_score ?? null}
                      criteriaMet={event.criteria_met}
                    />
                  </td>
```

to:

```tsx
                  <td className="py-4 px-4 bg-gray-800">
                    <ScoreQualityBadge
                      score={event.signal_quality_score ?? null}
                      criteriaMet={event.criteria_met}
                    />
                  </td>
                  <td className="py-4 px-4 bg-gray-800 rounded-r-xl">
                    <ReviewControls
                      eventUuid={event.uuid}
                      latestReview={event.latest_review ?? null}
                    />
                  </td>
```

- [ ] **Step 4: Type-check**

Run: `cd frontend && npx tsc --noEmit`

Expected: no errors.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/ScannerResults.tsx
git commit -m "feat(frontend): add Review column to ScannerResults table"
```

---

### Task 10: Wire ReviewControls into RecentEvents

**Files:**
- Modify: `frontend/src/components/RecentEvents.tsx`

- [ ] **Step 1: Add import**

In `frontend/src/components/RecentEvents.tsx`, add after the existing imports:

```typescript
import ReviewControls from './ReviewControls';
```

- [ ] **Step 2: Update grid header**

Change the header grid (line 61-67):

```tsx
      <div className="grid grid-cols-12 gap-4 px-4 py-2 text-xs font-medium text-gray-400 border-b border-gray-700">
        <div className="col-span-2">Ticker</div>
        <div className="col-span-2">Date</div>
        <div className="col-span-5">Summary</div>
        <div className="col-span-2">Severity</div>
        <div className="col-span-1">Details</div>
      </div>
```

to:

```tsx
      <div className="grid grid-cols-12 gap-4 px-4 py-2 text-xs font-medium text-gray-400 border-b border-gray-700">
        <div className="col-span-2">Ticker</div>
        <div className="col-span-2">Date</div>
        <div className="col-span-4">Summary</div>
        <div className="col-span-2">Severity</div>
        <div className="col-span-1">Details</div>
        <div className="col-span-1">Review</div>
      </div>
```

- [ ] **Step 3: Update grid body**

Change the Summary cell from `col-span-5` to `col-span-4`:

```tsx
          <div className="col-span-5">
```

to:

```tsx
          <div className="col-span-4">
```

And add a new Review cell after the Details cell (after line 103):

```tsx
          <div className="col-span-1 flex items-center justify-center">
            <ReviewControls
              eventUuid={event.uuid}
              latestReview={event.latest_review ?? null}
            />
          </div>
```

- [ ] **Step 4: Type-check**

Run: `cd frontend && npx tsc --noEmit`

Expected: no errors.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/RecentEvents.tsx
git commit -m "feat(frontend): add Review column to RecentEvents grid"
```

---

### Task 11: SignalReviewStats card

**Files:**
- Create: `frontend/src/components/SignalReviewStats.tsx`
- Modify: `frontend/src/pages/Scanner.tsx`

- [ ] **Step 1: Create the stats component**

Create `frontend/src/components/SignalReviewStats.tsx`:

```tsx
import React from 'react';
import { useQuery } from '@tanstack/react-query';
import { BarChart3 } from 'lucide-react';
import Card from './ui/Card';
import { fetchReviewStats } from '../api/scanner';

const SignalReviewStats: React.FC = () => {
  const { data: stats, isLoading } = useQuery({
    queryKey: ['reviewStats'],
    queryFn: () => fetchReviewStats(),
    refetchInterval: 60_000,
  });

  if (isLoading || !stats) {
    return null;
  }

  if (stats.total_events === 0) {
    return null;
  }

  const coveragePct = stats.total_events > 0
    ? Math.round((stats.reviewed_count / stats.total_events) * 100)
    : 0;

  return (
    <Card title="Signal Quality" icon={BarChart3 as any}>
      {/* Coverage */}
      <div className="mb-4">
        <div className="flex justify-between text-xs text-gray-400 mb-1">
          <span>Review Coverage</span>
          <span>{stats.reviewed_count} / {stats.total_events} ({coveragePct}%)</span>
        </div>
        <div className="w-full bg-gray-800 rounded-full h-2">
          <div
            className="bg-financial-blue h-2 rounded-full transition-all"
            style={{ width: `${coveragePct}%` }}
          />
        </div>
      </div>

      {/* Acceptance Rate */}
      <div className="mb-4 p-3 bg-gray-800/40 border border-gray-700/50 rounded-lg text-center">
        <div className="text-2xl font-bold text-financial-light">
          {stats.reviewed_count > 0 ? `${Math.round(stats.acceptance_rate * 100)}%` : '—'}
        </div>
        <div className="text-[10px] text-gray-500 uppercase tracking-wider font-semibold">Acceptance Rate</div>
      </div>

      {/* By Scanner Type */}
      {stats.by_scanner_type.length > 0 && (
        <div className="mb-4">
          <div className="text-[10px] font-bold text-gray-500 uppercase tracking-wider mb-2">By Scanner Type</div>
          <div className="space-y-1">
            {stats.by_scanner_type.map((row) => (
              <div key={row.scanner_type} className="flex items-center justify-between text-xs py-1 border-b border-gray-800/60">
                <span className="text-gray-400 truncate">{row.scanner_type.replace(/_/g, ' ')}</span>
                <div className="flex gap-2 text-[10px] font-mono">
                  <span className="text-green-400" title="Confirmed">{row.confirmed}</span>
                  <span className="text-red-400" title="Rejected">{row.rejected}</span>
                  <span className="text-gray-400" title="Uncertain">{row.uncertain}</span>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Top Rejection Reasons */}
      {stats.top_rejection_reasons.length > 0 && (
        <div>
          <div className="text-[10px] font-bold text-gray-500 uppercase tracking-wider mb-2">Top Rejection Reasons</div>
          <div className="space-y-1">
            {stats.top_rejection_reasons.map((item) => (
              <div key={item.reason} className="flex items-center justify-between text-xs py-1">
                <span className="text-gray-400">{item.reason.replace(/_/g, ' ')}</span>
                <span className="text-red-400 font-mono">{item.count}</span>
              </div>
            ))}
          </div>
        </div>
      )}
    </Card>
  );
};

export default SignalReviewStats;
```

- [ ] **Step 2: Add SignalReviewStats to Scanner page**

In `frontend/src/pages/Scanner.tsx`, add the import at the top with the other component imports:

```typescript
import SignalReviewStats from '../components/SignalReviewStats';
```

Then add the stats card **after** the "Recent Scan History" `</Card>` closing tag (around line 707), before the closing `</div>` of the page:

```tsx
      <SignalReviewStats />
```

- [ ] **Step 3: Type-check**

Run: `cd frontend && npx tsc --noEmit`

Expected: no errors.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/components/SignalReviewStats.tsx frontend/src/pages/Scanner.tsx
git commit -m "feat(frontend): add SignalReviewStats card to Scanner page"
```

---

### Task 12: Verify in browser

**Files:** none (verification only)

- [ ] **Step 1: Restart backend**

Run: `docker compose restart backend`

Check logs: `docker compose logs backend --tail=20`

Expected: no import errors, server starts successfully.

- [ ] **Step 2: Verify backend endpoints**

```bash
curl -s http://localhost:8000/api/scanner/reviews/stats | python -m json.tool
```

Expected: JSON with `total_events`, `reviewed_count`, `acceptance_rate`, etc.

```bash
curl -s "http://localhost:8000/api/scanner/results?limit=3" | python -m json.tool
```

Expected: each event has a `latest_review` field (null if unreviewed).

- [ ] **Step 3: Verify old endpoint is gone**

```bash
curl -s http://localhost:8000/api/signal-reviews
```

Expected: 404 (endpoint no longer exists).

- [ ] **Step 4: Verify frontend**

Open `http://localhost:3333` in the browser. Navigate to the Scanner page. Run a scan or view existing results.

Check:
- Each row in ScannerResults has a Review column with three icon buttons
- Clicking thumbs-up submits a "confirmed" verdict and shows a green check badge
- Clicking thumbs-down opens the reject popover with reason dropdown and notes
- Clicking the verdict badge allows re-review
- SignalReviewStats card appears below scan history with coverage and stats
- RecentEvents on Dashboard also shows review controls

- [ ] **Step 5: Final commit (if any fixes needed)**

```bash
git add -A
git commit -m "fix(signal-review): address browser verification findings"
```
