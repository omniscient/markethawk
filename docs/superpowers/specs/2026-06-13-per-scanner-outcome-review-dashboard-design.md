# Per-Scanner Outcome + Review Dashboard — Design

**Date:** 2026-06-13
**Issue:** [#303](https://github.com/omniscient/markethawk/issues/303) — Outcome dashboard: per-scanner ScannerOutcomeSummary aggregates in UI
**Status:** Spec

---

## Problem

Scanner quality is currently invisible at a glance. The platform accumulates
forward-outcome data in `ScannerOutcomeSummary` (price follow-through, MFE/MAE)
and human-verdict data in `SignalReview` (precision: confirmed vs. rejected),
but neither surface is exposed per-scanner in the UI in a way that makes the
"credibility loop" visible: outcomes say *did price follow*, reviews say *was
the signal right* — divergence between the two is itself a tuning signal (e.g.
high follow-through + low confirmation rate → `threshold_too_loose` rejects).

---

## Requirements

1. **Backend**: The existing `GET /api/v1/outcomes/scorecard/{scanner_type}`
   endpoint must return review-side aggregate fields alongside the current
   outcome-side fields. New fields are **optional / nullable** so existing
   consumers (ScorecardDetail, interval endpoints) remain unchanged.

2. **Review-side fields** (trailing 90d window, configurable via
   `review_window_days` query param, default `90`):
   - `precision_pct`: `confirmed / (confirmed + rejected)` × 100, `null` when
     no confirmed-or-rejected reviews exist.
   - `review_coverage_pct`: reviewed events / total signal events × 100.
   - `verdict_counts`: dict keyed by verdict (`confirmed`, `rejected`,
     `enhanced`), values are counts.
   - `top_reject_reasons`: list of up to 3 `{reason, count}` objects ordered
     by count descending; empty list when no rejections.
   - `review_sample_n`: total reviewed event count (denominator for precision).

3. **Both sides must be returned even when sparse.** `precision_pct = null`
   and `review_coverage_pct = 0` when zero reviews exist; no 404 for missing
   data.

4. **UI**: Extend `ScannerSummaryCard` with a precision badge and review stats.
   The badge shows `"62% confirmed · n=48 · 90d"`. The card continues to be
   driven by the existing `useScorecard` hook and `ScorecardOverview` page —
   no new route or page.

5. **Low-n gating**:
   - Precision badge is **muted** (grey text, lighter border) when
     `review_coverage_pct < 20`, with tooltip/hint "needs more reviews".
   - Outcome stats (follow-through, MFE/MAE at card level) are **greyed**
     when `complete_signals < 5`.
   - Per-interval stats in the interval breakdown are greyed when that
     interval's `sample_size < 5`.

6. **React Query** for all fetching, consistent with the existing `useScorecard`
   hook pattern (`['scorecard', scannerType, dates]` key family).

7. **No new endpoint**, **no new page**, **no new component files** beyond
   the five files in scope: `backend/app/services/stats.py`,
   `backend/app/schemas/outcome.py`, `backend/app/routers/outcomes.py`,
   `frontend/src/api/outcomes.ts`, and
   `frontend/src/components/scorecard/ScannerSummaryCard.tsx`.

---

## Architecture / Approach

### Backend — `StatsService.get_scorecard()` + `ScorecardResponse`

**File:** `backend/app/services/stats.py`

After computing the existing outcome-side aggregates, run a second query over
`SignalReview` joined to `ScannerEvent` filtered to the same `scanner_type`
and a trailing `review_window_days` window (independent of `start_date` /
`end_date`, which govern the outcome side):

```python
# Pseudo-SQL intent (use SQLAlchemy ORM)
SELECT sr.verdict, sr.reject_reason, COUNT(*) AS cnt
FROM signal_reviews sr
JOIN scanner_events se ON se.id = sr.scanner_event_id
WHERE se.scanner_type = :scanner_type
  AND sr.reviewed_at >= (NOW() - INTERVAL ':review_window_days days')
GROUP BY sr.verdict, sr.reject_reason
ORDER BY cnt DESC
```

Compute derived fields in Python:
```python
confirmed = verdict_counts.get("confirmed", 0)
rejected  = verdict_counts.get("rejected",  0)
precision_pct = (confirmed / (confirmed + rejected) * 100) if (confirmed + rejected) > 0 else None
review_coverage_pct = (total_reviewed / total_signals * 100) if total_signals > 0 else 0
```

`total_reviewed` = `confirmed + rejected + enhanced` count in the window.
`total_signals` = the already-computed `total_signals` from the outcome side.

**File:** `backend/app/schemas/outcome.py`

Extend `ScorecardResponse` with:
```python
class RejectReasonCount(BaseModel):
    reason: str
    count: int

class ScorecardResponse(BaseModel):
    # ... existing fields unchanged ...
    precision_pct: Optional[float] = None
    review_coverage_pct: Optional[float] = None
    verdict_counts: Dict[str, int] = {}
    top_reject_reasons: List[RejectReasonCount] = []
    review_sample_n: int = 0
```

**File:** `backend/app/routers/outcomes.py`

Add `review_window_days: int = 90` to `get_scorecard_by_type` (and its alias
`get_scorecard`); thread it into `StatsService.get_scorecard`.

### Frontend — `ScannerSummaryCard` + `Scorecard` type

**File:** `frontend/src/api/outcomes.ts`

Extend `Scorecard` interface with the new optional fields (mirroring
`ScorecardResponse`):
```ts
export interface RejectReasonCount { reason: string; count: number; }

export interface Scorecard {
  // ... existing fields unchanged ...
  precision_pct?: number | null;
  review_coverage_pct?: number | null;
  verdict_counts?: Record<string, number>;
  top_reject_reasons?: RejectReasonCount[];
  review_sample_n?: number;
}
```

**File:** `frontend/src/components/scorecard/ScannerSummaryCard.tsx`

Below the existing four-stat grid (`Win Rate / MFE:MAE / Expectancy /
Follow-thru`), add a precision badge row:

- If `review_sample_n === 0` or `review_sample_n` is absent → render nothing
  (no badge).
- If `review_coverage_pct < 20` → muted badge: grey text + dashed border +
  inline hint text "needs more reviews".
- Otherwise → active badge: `"62% confirmed · n=48 · 90d"` in green/amber
  color keyed to precision (≥60% green, 40–59% amber, <40% red).
- No period selector change; the 90d window is fixed on the backend side
  (`review_window_days=90` default). The existing 7D/30D/90D/ALL buttons
  continue to control outcome stats only.

Apply outcome stat greying: wrap each of the four stat cells in a conditional
`opacity-40` class when `complete_signals < 5`.

---

## Alternatives Considered

### A: New `/outcomes/combined-summary/{scanner_type}` endpoint
Rejected. Would require two fetches per scanner card (existing + new), plus a
merge step in the frontend. The existing `useScorecard` hook and
`ScorecardOverview` page drive each card from a single request; a second
endpoint doubles network round-trips for zero user-visible benefit on a size-M
ticket.

### B: Add panel to Scanner page (`/pages/Scanner/index.tsx`)
Rejected. The Scanner page is operationally focused (config/live-progress/
results). A stats panel there would show only the currently-selected scanner
and would not make the credibility loop visible across scanners. ScorecardOverview
already is the realized form of the "small Outcomes panel" the issue requested.

### C: Separate review window controlled by the period toggle
Rejected. The outcome side already uses `start_date`/`end_date` from the page
period selector. Tying the review window to the same toggle would make short
windows (7d) return near-zero reviews — reviews accumulate more slowly than
scanner events. A fixed 90d default for the review side is documented in the
triage comment and better serves the precision signal's statistical needs.

---

## Open Questions (non-blocking)

1. The issue mentions "median eod/1d/2d/5d/10d pct change" in the original ask.
   The `interval_breakdown` dict in the existing scorecard already provides
   per-interval `median_pct` when snapshots exist. The card currently does not
   display the interval breakdown table; this is deferred to `ScorecardDetail`
   where it already lives. If a sparkline of median interval returns is desired
   on the card, it can be a follow-on within this issue.

2. `enhanced` verdict type in `verdict_counts`: the triage spec counts only
   confirmed vs. rejected for precision. Enhanced signals are included in
   `verdict_counts` for informational display but are excluded from the
   precision denominator (matching `UNCERTAIN` avoidance — this interpretation
   is consistent with "precision = confirmed / (confirmed + rejected)").

---

## Assumptions

- **[ASSUMPTION]** `SignalReview.scanner_event_id` → `ScannerEvent.id` join is
  sufficient to filter by `scanner_type`; no intermediate table needed.
- **[ASSUMPTION]** The existing `ScannerEvent.reviews` ORM relationship
  (`signal_review.py:38`) is already wired so a subquery approach is
  straightforward, but the second-query pattern (separate aggregate query) is
  preferred over a complex LEFT JOIN on the primary scorecard query to keep
  `get_scorecard` readable.
- **[ASSUMPTION]** `total_signals` for coverage denominator uses the
  outcome-side `total_signals` (all events in the date window), not a separate
  count of events with at least one review. This is the most conservative
  measure of coverage.
- **[ASSUMPTION]** Backend uses synchronous SQLAlchemy (`Session` /
  `db.query()`) consistent with existing `stats.py` and `outcomes.py` — not
  AsyncSession. The `[INVALID]` memory entry confirms the app is sync.
