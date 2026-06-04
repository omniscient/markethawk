# Human Signal Review and Quality Feedback Loop — Design Spec (v2)

**Issue**: [#6 — Human signal review and quality feedback loop](https://github.com/omniscient/markethawk/issues/6)
**Date**: 2026-05-23
**Status**: Pending Review
**Supersedes**: `2026-05-14-human-signal-review-design.md` (on refine branch, never merged)

## Overview

This is a revised spec that accounts for the `signal_reviews` table and CRUD endpoints already built for issue #5's `/validate-scanner` skill. The original spec assumed a greenfield implementation; this revision evolves the existing code.

Scanner events can be technically correct but qualitatively poor. This feature adds a human review layer: a user can confirm, reject, or mark any scanner event as uncertain directly from the Scanner page UI. Verdicts are persisted in the existing `signal_reviews` table. A stats card shows review coverage and rejection patterns.

## What Already Exists (from Issue #5)

- **Model**: `SignalReview` in `backend/app/models/signal_review.py` — fields: `scanner_event_id` (FK, CASCADE), `verdict` (confirmed/rejected/enhanced), `reject_reason`, `notes`, `enhance_suggestion` (JSONB), `reviewed_at`, `reviewed_by`
- **Relationship**: one-to-many (`ScannerEvent.reviews` → list of `SignalReview`)
- **Router**: `backend/app/routers/signal_reviews.py` — `POST /api/signal-reviews`, `GET /api/signal-reviews?scanner_type=...`
- **Schemas**: `SignalReviewCreate`, `SignalReviewResponse` in `backend/app/schemas/signal_review.py`
- **Tests**: `backend/tests/api/test_signal_reviews.py`
- **Migration**: `b3e8f2a1c9d7_add_signal_reviews.py`

## Design Decisions

### Verdict vocabulary

Keep the existing set and add one value: `confirmed | rejected | enhanced | uncertain`.

- `confirmed` = signal was timely and actionable (frontend: thumbs-up)
- `rejected` = signal was poor quality (frontend: thumbs-down, requires reason)
- `uncertain` = can't tell yet (frontend: question-mark) — **new value**
- `enhanced` = signal led to a threshold suggestion (validate-scanner skill only)

No data migration needed.

### Relationship cardinality

Keep one-to-many. The validate-scanner skill can re-review the same event across sessions. The frontend displays the **latest** review (by `reviewed_at`) as the verdict badge.

### Endpoint consolidation

Remove the standalone `signal_reviews` router. Move all review endpoints under the scanner router at `/api/scanner/`. The validate-scanner skill will be updated to use the new paths.

### No denormalization

No snapshot columns (`scanner_type`, `ticker`, `indicators_snapshot`). The FK join to `ScannerEvent` is one hop on an integer PK; `ScannerEvent` rows are permanent.

## Backend Changes

### 1. Schema update

**File**: `backend/app/schemas/signal_review.py`

Add `uncertain` to `VALID_VERDICTS`:

```python
VALID_VERDICTS = {"confirmed", "rejected", "enhanced", "uncertain"}
```

No other schema changes. `SignalReviewCreate` and `SignalReviewResponse` remain as-is.

### 2. Endpoint consolidation

**Remove**: `backend/app/routers/signal_reviews.py` and its registration in `main.py`.

**Add to** `backend/app/routers/scanner.py`:

#### `POST /api/scanner/events/{event_uuid}/review`

Create a new review for the event identified by UUID. Looks up the event by UUID, validates it exists, creates a `SignalReview` row. Returns 201.

Request body: same as current `SignalReviewCreate` but without `scanner_event_id` (derived from the URL parameter).

```python
class SignalReviewRequest(BaseModel):
    verdict: str  # confirmed | rejected | enhanced | uncertain
    reject_reason: Optional[str] = None
    notes: Optional[str] = None
    enhance_suggestion: Optional[Dict[str, Any]] = None
```

#### `GET /api/scanner/events/reviews`

List reviews with filters. Query parameters:
- `scanner_type` (required) — with `liquidity_hunt` alias expansion
- `start_date` (optional)
- `end_date` (optional)
- `verdict` (optional) — filter by specific verdict

Returns `List[SignalReviewResponse]` with joined `ticker`, `event_date`, `scanner_type` from the parent event.

#### `GET /api/scanner/reviews/stats`

Aggregate stats. Query parameters:
- `scanner_type` (optional) — if omitted, stats across all types
- `start_date` (optional)
- `end_date` (optional)

Response:
```python
class SignalReviewStatsResponse(BaseModel):
    total_events: int          # total scanner events in range
    reviewed_count: int        # events with at least one review
    acceptance_rate: float     # confirmed / (confirmed + rejected), 0.0 if none
    by_scanner_type: list      # [{scanner_type, total, confirmed, rejected, uncertain, enhanced}]
    top_rejection_reasons: list  # [{reason, count}] sorted desc, top 5
```

### 3. Embed latest review in scanner results

**Router file**: `backend/app/routers/scanner.py` — the `get_scanner_results` endpoint (line ~342).

Add `joinedload(ScannerEvent.reviews)` to the query so reviews are fetched without N+1.

**Schema file**: `backend/app/schemas/event.py` — `ScannerEventResponse`.

Add an optional `latest_review` field of type `Optional[SignalReviewResponse]`. This requires a `@computed_field` or a custom serializer that picks the most recent review from the `reviews` list (max by `reviewed_at`), since the ORM relationship is one-to-many.

Alternatively, add a `@property` on the `ScannerEvent` model that returns the latest review, and let `from_attributes=True` pick it up.

### 4. Update validate-scanner skill

**File**: `.claude/skills/validate-scanner/SKILL.md`

Update the API calls from:
- `POST /api/signal-reviews` → `POST /api/scanner/events/{uuid}/review`
- `GET /api/signal-reviews?scanner_type=...` → `GET /api/scanner/events/reviews?scanner_type=...`

### 5. Update tests

**File**: `backend/tests/api/test_signal_reviews.py`

Update all test URLs to the new paths. Add tests for:
- `POST /api/scanner/events/{uuid}/review` with `uncertain` verdict
- `GET /api/scanner/reviews/stats` returning correct aggregates
- Rejection without reason returns 422
- Invalid UUID returns 404

## Frontend Changes

### 6. TypeScript types and API client

**File**: `frontend/src/api/scanner.ts`

Add types:
```typescript
interface SignalReview {
  id: number;
  scanner_event_id: number;
  verdict: 'confirmed' | 'rejected' | 'enhanced' | 'uncertain';
  reject_reason: string | null;
  notes: string | null;
  enhance_suggestion: Record<string, unknown> | null;
  reviewed_at: string;
  reviewed_by: string | null;
}

interface SignalReviewStats {
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

Extend `ScannerEvent` type with `latest_review: SignalReview | null`.

Add API functions:
- `submitReview(eventUuid: string, payload: SignalReviewRequest): Promise<SignalReview>`
- `fetchReviewStats(params?: { scanner_type?: string; start_date?: string; end_date?: string }): Promise<SignalReviewStats>`

### 7. ReviewControls component

**File**: `frontend/src/components/ReviewControls.tsx`

Props: `eventUuid: string`, `latestReview: SignalReview | null`

Two modes:
- **Unreviewed** (no `latestReview`): three icon buttons — ThumbsUp (confirmed), ThumbsDown (rejected), HelpCircle (uncertain)
- **Reviewed** (`latestReview` exists): verdict badge (green check = confirmed, red X = rejected, gray ? = uncertain, blue wrench = enhanced). Clicking the badge switches back to button mode for re-review.

On ThumbsDown click: show a small popover with:
- Reason dropdown: `too_late`, `noise`, `stale_data`, `split_artifact` (required)
- Notes textarea (optional)
- Submit button

Uses `useMutation` from React Query. Optimistically updates the local cache. Invalidates `scannerResults` query key on settlement. Click events use `stopPropagation` to prevent row click from firing.

### 8. Wire ReviewControls into ScannerResults

**File**: `frontend/src/components/ScannerResults.tsx`

Add an 8th "Review" column (narrow, ~70px). Render `<ReviewControls>` in each row, passing `event.uuid` and `event.latest_review`.

### 9. Wire ReviewControls into RecentEvents

**File**: `frontend/src/components/RecentEvents.tsx`

Adjust grid from 12-column layout: reduce Summary from col-span-5 to col-span-4, add a new col-span-1 for `<ReviewControls>`.

### 10. SignalReviewStats card

**File**: `frontend/src/components/SignalReviewStats.tsx`

Placed on the Scanner page below the scan history section.

Contents:
- Coverage progress bar (reviewed / total events) with percentage label
- Acceptance rate as a large number with up/down trend indicator
- Per-scanner-type breakdown: small table with columns for each verdict count
- Top rejection reasons: horizontal bar chart or simple list with counts

Uses `useQuery` with key `['reviewStats']`, refetches when scanner results change.

## Acceptance Criteria

- [x] ~~SignalReview model and migration exist~~ (already done)
- [ ] `uncertain` verdict is accepted by the API
- [ ] Endpoints consolidated under `/api/scanner/`
- [ ] `POST /api/scanner/events/{uuid}/review` creates a review
- [ ] `GET /api/scanner/reviews/stats` returns aggregate stats
- [ ] Latest review is embedded in scanner results response
- [ ] User can confirm/reject/mark-uncertain any event from ScannerResults
- [ ] Rejection requires a reason category
- [ ] Verdict badge visible on revisit (persists across page reloads)
- [ ] Stats card shows coverage and rejection patterns on Scanner page
- [ ] Validate-scanner skill updated to use new endpoints
- [ ] No changes to scanner logic

## Out of Scope

- Revision/audit log for verdict changes
- `reviewed_by` field population (no auth system)
- Indicator denormalization / snapshot columns
- AI-powered pattern detection from review data
- Dedicated "Signal Quality" page (stats live on Scanner page)
