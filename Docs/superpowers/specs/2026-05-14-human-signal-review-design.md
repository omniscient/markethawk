# Human Signal Review and Quality Feedback Loop — Design Spec

**Issue**: [#6 — Human signal review and quality feedback loop](https://github.com/omniscient/markethawk/issues/6)
**Date**: 2026-05-14
**Status**: Pending Review

## Overview

Scanner events can be technically correct (all criteria pass) but qualitatively poor — e.g. a liquidity hunt signal that fired after the move had already happened. This feature adds a lightweight human review layer: a user can accept, reject, or mark any scanner event as uncertain directly from the results UI. Verdicts are persisted in a new `SignalReview` table that doubles as a labeled training dataset for future automated quality improvements.

## Requirements

- User can accept / reject / mark-uncertain any scanner event from `ScannerResults` or `RecentEvents`
- Rejection requires selecting a reason category from a fixed set
- Optional free-text notes on any verdict
- Submitting a review for an already-reviewed event updates the existing record (upsert — no history retained)
- Verdict badges are visible on revisit (survives page reload)
- A `SignalReviewStats` card on the Scanner page shows: reviewed/total ratio, acceptance rate by scanner type, most common rejection reasons
- No changes to scanner logic — purely a feedback collection layer
- Schema designed for future single-table AI queries (no joins needed to get indicators + verdict + reason)

## Backend

### New Model: `SignalReview`

**File**: `backend/app/models/signal_review.py`

```python
class SignalReview(Base):
    __tablename__ = "signal_reviews"

    id = Column(Integer, primary_key=True, index=True)
    scanner_event_id = Column(Integer, ForeignKey("scanner_events.id", ondelete="CASCADE"), nullable=False, unique=True, index=True)

    verdict = Column(String(10), nullable=False)         # "accepted" | "rejected" | "uncertain"
    rejection_reason = Column(String(20), nullable=True) # required when verdict="rejected"
    notes = Column(Text, nullable=True)

    # Denormalized snapshot — captured at write time for future AI queries (no join needed)
    scanner_type = Column(String(50), nullable=False)
    ticker = Column(String(10), nullable=False, index=True)
    indicators_snapshot = Column(JSONB, nullable=False, default=dict)
    criteria_met_snapshot = Column(JSONB, nullable=False, default=dict)

    reviewed_at = Column(DateTime, nullable=False, default=lambda: datetime.now(timezone.utc).replace(tzinfo=None), onupdate=lambda: datetime.now(timezone.utc).replace(tzinfo=None))
```

**Verdict values**: `accepted`, `rejected`, `uncertain`

**Rejection reason values**: `too_late`, `noise`, `stale_data`, `split_artifact`
- Required (non-null) when `verdict = "rejected"`, must be NULL otherwise
- Enforced at the Pydantic layer; a DB CHECK constraint is optional but recommended

**Cascade**: `ondelete="CASCADE"` — if the parent `ScannerEvent` is deleted, its review is deleted too

**Registration**: Import and add to `backend/app/models/__init__.py`

### New Pydantic Schemas

**File**: `backend/app/schemas/signal_review.py`

```python
from enum import Enum

class Verdict(str, Enum):
    accepted = "accepted"
    rejected = "rejected"
    uncertain = "uncertain"

class RejectionReason(str, Enum):
    too_late = "too_late"
    noise = "noise"
    stale_data = "stale_data"
    split_artifact = "split_artifact"

class SignalReviewRequest(BaseModel):
    verdict: Verdict
    rejection_reason: Optional[RejectionReason] = None
    notes: Optional[str] = None

    @validator("rejection_reason")
    def reason_required_when_rejected(cls, v, values):
        if values.get("verdict") == Verdict.rejected and v is None:
            raise ValueError("rejection_reason is required when verdict is 'rejected'")
        if values.get("verdict") != Verdict.rejected and v is not None:
            raise ValueError("rejection_reason must be null unless verdict is 'rejected'")
        return v

class SignalReviewResponse(BaseModel):
    id: int
    scanner_event_id: int
    verdict: str
    rejection_reason: Optional[str]
    notes: Optional[str]
    scanner_type: str
    ticker: str
    reviewed_at: datetime

    class Config:
        from_attributes = True

class SignalReviewStatsResponse(BaseModel):
    total_events: int
    reviewed_count: int
    acceptance_rate: float                       # 0.0–1.0; None if reviewed_count == 0
    by_scanner_type: List[dict]                  # [{scanner_type, total, accepted, rejected, uncertain}]
    top_rejection_reasons: List[dict]            # [{reason, count}] sorted desc, top 5
```

**Registration**: Import in `backend/app/schemas/__init__.py`

### New Endpoints

**Router**: `backend/app/routers/scanner.py`

#### POST `/api/scanner/events/{event_uuid}/review`

Upsert a review for the event identified by `event_uuid`. If a `SignalReview` already exists for this event, update it in-place; otherwise insert a new row. Snapshot fields are always refreshed from the current `ScannerEvent` state on every write.

```
POST /api/scanner/events/{event_uuid}/review
Body: SignalReviewRequest
Response: SignalReviewResponse (200 on update, 201 on create)
404 if event_uuid does not match any ScannerEvent
400 if rejection_reason validation fails
```

**Logic**:
1. Look up `ScannerEvent` by `uuid` field — 404 if not found
2. Validate body (Pydantic handles rejection_reason rule)
3. Query `SignalReview` by `scanner_event_id`
4. If exists: update `verdict`, `rejection_reason`, `notes`, snapshot fields, `reviewed_at`
5. If not exists: insert with snapshot fields populated from the event
6. Commit and return

#### GET `/api/scanner/events/reviews`

List reviewed events with optional filters.

```
GET /api/scanner/events/reviews?verdict=rejected&scanner_type=liquidity_hunt_pre&from_date=2026-05-01&to_date=2026-05-14&limit=100&offset=0
Response: List[SignalReviewResponse]
```

#### GET `/api/scanner/reviews/stats`

Aggregate stats for the `SignalReviewStats` card.

```
GET /api/scanner/reviews/stats
Response: SignalReviewStatsResponse
```

**Logic** (all in a single DB round-trip using `func.count` + `GROUP BY`):
1. Total `ScannerEvent` count → `total_events`
2. Total `SignalReview` count → `reviewed_count`
3. GROUP BY `scanner_type` → `by_scanner_type`
4. GROUP BY `rejection_reason` WHERE `verdict = 'rejected'` → `top_rejection_reasons` (top 5)

## Frontend

### Inline Review Controls

**Components**: `ScannerResults.tsx` and `RecentEvents.tsx`

Add a "Review" column to each event row. The column contains three icon buttons:
- `ThumbsUp` (lucide-react) — accept. Fills green when active verdict = accepted.
- `ThumbsDown` (lucide-react) — reject. Fills red when active verdict = rejected. Clicking opens the rejection popover.
- `HelpCircle` (lucide-react) — uncertain. Fills gray when active verdict = uncertain.

**Verdict badge**: When a review exists, show a small badge replacing/overlapping the button group:
- Accepted: green check `✓ accepted`
- Rejected: red ✗ with reason: `✗ too_late`
- Uncertain: gray `? uncertain`

Clicking the badge re-opens the review controls so the user can change their verdict.

**Rejection popover**: A small inline popover (or dropdown panel) that appears below the thumbs-down button. Contains:
- A `<select>` with the four reason options (too_late, noise, stale_data, split_artifact) — displayed as human-readable labels ("Too late", "Noise", "Stale data", "Split artifact")
- An optional `<textarea>` for notes (placeholder: "Optional notes…")
- A "Submit" button

**State management**:
- `useQuery` for existing review: `GET /api/scanner/events/reviews?event_id=<id>` or include `review` field in the `ScannerEventResponse` (see below)
- `useMutation` (React Query) for `POST /api/scanner/events/{uuid}/review`
- On mutation success: invalidate the reviews query and the stats query

**Preferred approach — include review in event response**: Extend `ScannerEventResponse` schema with an optional `review: SignalReviewResponse | null` field. Populate it in the `GET /api/scanner/results` endpoint via a left join. This avoids a second round-trip per event and keeps the existing query patterns intact.

### `SignalReviewStats` Card

**File**: `frontend/src/components/SignalReviewStats.tsx`

**Placement**: Scanner page (`frontend/src/pages/Scanner.tsx`), right-column sidebar below the existing "Quick Actions" section.

**Data**: `useQuery(['reviewStats'], fetchReviewStats)` — calls `GET /api/scanner/reviews/stats`. Refetch interval: 30 seconds.

**Layout** (inside existing `Card` wrapper):
1. Headline row: "X / Y reviewed" with a progress bar showing coverage
2. Acceptance rate: large percentage figure with a green/red tint
3. By scanner type: compact table (scanner_type | reviewed | rate%)
4. Top rejection reasons: a short ranked list with counts

**API client addition** (`frontend/src/api/scanner.ts`):

```typescript
export const submitReview = async (
  eventUuid: string,
  body: { verdict: string; rejection_reason?: string; notes?: string }
): Promise<SignalReview> => {
  const response = await apiClient.post(`/scanner/events/${eventUuid}/review`, body);
  return response.data;
};

export const fetchReviewStats = async (): Promise<SignalReviewStatsResponse> => {
  const response = await apiClient.get('/scanner/reviews/stats');
  return response.data;
};
```

### TypeScript Types

Add to `frontend/src/api/scanner.ts`:

```typescript
export interface SignalReview {
  id: number;
  scanner_event_id: number;
  verdict: 'accepted' | 'rejected' | 'uncertain';
  rejection_reason?: string;
  notes?: string;
  scanner_type: string;
  ticker: string;
  reviewed_at: string;
}

export interface SignalReviewStatsResponse {
  total_events: number;
  reviewed_count: number;
  acceptance_rate: number;
  by_scanner_type: Array<{ scanner_type: string; total: number; accepted: number; rejected: number; uncertain: number }>;
  top_rejection_reasons: Array<{ reason: string; count: number }>;
}
```

Extend `ScannerEvent` with:
```typescript
review?: SignalReview | null;
```

## Database Migration

After adding `signal_reviews` model:

```bash
python -m alembic revision --autogenerate -m "add_signal_reviews"
python -m alembic upgrade head
```

## Alternatives Considered

### Append review history vs. update in-place

Append-only (keeping every verdict change) was considered. Rejected because: (1) the AI training use case needs the final authoritative judgment, not deliberation history; (2) every read would need a `ROW_NUMBER() OVER (PARTITION BY scanner_event_id ORDER BY reviewed_at DESC)` window to find the current verdict; (3) the issue's "verdicts persist and are visible on revisit" acceptance criterion is satisfied by durability, not by history. Upsert is simpler and correct.

### Stats card on Dashboard page vs Scanner page

Dashboard placement was considered (the issue says "Dashboard view"). Rejected because: the Dashboard is already at capacity with four metric cards, a chart, alerts, events, market overview, news feed, and settings. Review stats are only actionable when the user is actively triaging signals — which happens on the Scanner page. The right-column sidebar of the Scanner page is the natural home alongside the Scan Status card.

### FK-only vs. denormalized snapshot

Relying purely on a JOIN to `ScannerEvent` was considered. Rejected because: scanner events can be deleted via the admin endpoint, and `indicators`/`criteria_met` could be mutated by future scanner iterations. The snapshot captures what the reviewer saw at decision time, which is the semantically correct ground truth for a training dataset. The overhead is small (one extra JSONB write per review).

## Open Questions

- Should `split_artifact` be renamed `data_artifact` to cover a broader class of data quality issues? Non-blocking — the enum can be extended in a later migration.
- Should the review controls appear on `RecentEvents` (Dashboard page) in addition to the Scanner page, given the stats card is Scanner-only? Suggested answer: yes — ReviewEvents is also shown from other pages (e.g. stock detail); controls should work wherever the component appears.

## Assumptions

- **Single user**: No multi-user attribution needed for v1 — no `reviewed_by` field. The table records one authoritative verdict.
- **Rejection reason as VARCHAR + Pydantic enum**: Not a native Postgres ENUM type. This avoids the `ALTER TYPE` complexity when adding new categories. A CHECK constraint (`rejection_reason IN (...)`) can be added optionally.
- **Review in ScannerEventResponse**: Extending the existing `/api/scanner/results` response to include an embedded `review` field is the cleanest approach. The alternative (separate GET per event) would cause N+1 requests.
- **No pagination on stats**: The stats endpoint returns aggregates, not rows — pagination is not applicable.

## Out of Scope

- Future AI / LLM integration (schema is designed for it; implementation deferred)
- Multi-user reviews or review attribution
- Undo / soft-delete of reviews
- Automated test coverage (tracked separately)
- Exporting the labeled dataset to external systems
