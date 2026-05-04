# Clear Scanner Event History — Design Spec

**Issue**: [#3 — Clear scanner event history per stock](https://github.com/omniscient/markethawk/issues/3)
**Date**: 2026-05-03
**Status**: Approved

## Overview

Add a "Clear History" button on the Stock Detail page that deletes all scanner event history for a specific ticker, with a confirmation modal to prevent accidental deletion. Includes a seed script so the feature can be manually tested against realistic data.

## Backend

### New Endpoint

```
DELETE /api/scanner/events/{ticker}
```

**Router**: `backend/app/routers/scanner.py`

**Logic**:
1. Normalize ticker to uppercase
2. Query all `ScannerEvent` rows where `ticker` matches
3. Delete them and commit
4. Return the count

**Response schema** (new Pydantic model in `backend/app/schemas/event.py`):

```python
class ClearEventsResponse(BaseModel):
    ticker: str
    deleted_count: int
```

**Edge case**: If no events exist for the ticker, return `200` with `deleted_count: 0` (the intent is fulfilled — there's nothing to clear).

## Frontend

### Clear History Button

**Location**: `frontend/src/pages/StockDetailPage.tsx`, in the `actions` slot of the "Scanner Event History" card, next to the existing "Run Scanner" button.

**Styling**: Red-tinted destructive action — `bg-red-500/10 border-red-500/30 text-red-400 hover:bg-red-500 hover:text-white`. Uses `Trash2` icon from lucide-react.

**Disabled when**: A scan is currently running or connecting (same condition as Run Scanner button).

### Confirmation Modal

**Uses**: Existing `Modal` component from `frontend/src/components/ui/Modal.tsx` with `size="sm"`.

**State**: `const [clearDialogOpen, setClearDialogOpen] = useState(false)`

**Content**:
- Title: "Clear Scanner History"
- Body: "Are you sure you want to clear all scanner event history for **{ticker}**? This cannot be undone."
- Footer: Cancel button (gray) and Confirm button (red, "Clear History")

**On confirm**:
1. Call `DELETE /api/scanner/events/{ticker}`
2. Close the modal
3. Invalidate/refetch the scanner results query so `<RecentEvents>` list updates immediately

### API Client Addition

Add to `frontend/src/api/scanner.ts`:

```typescript
export const clearScannerEvents = async (ticker: string): Promise<{ ticker: string; deleted_count: number }> => {
  const response = await apiClient.delete(`/scanner/events/${ticker}`);
  return response.data;
};
```

## Seed Script

### File: `backend/app/scripts/seed_scanner_events.py`

**Runnable via**:
```bash
docker-compose exec backend python -m app.scripts.seed_scanner_events
```

**What it creates**:
1. A "Test" `StockUniverse` (if it doesn't already exist)
2. `StockUniverseTicker` entries for: AAPL, TSLA, NVDA
3. 4 `ScannerEvent` rows per ticker (12 total), spread across recent dates, using varied `scanner_type` values:
   - `pre_market_volume`
   - `oversold_bounce`
   - `liquidity_hunt`
4. Each event has plausible fake `indicators` (e.g. `{"volume_ratio": 5.2, "avg_volume": 1200000}`) and `criteria_met` (e.g. `{"volume_spike": true, "price_gap": true}`)

**Idempotency**: Uses `INSERT ... ON CONFLICT DO NOTHING` leveraging the `uq_scanner_event` unique constraint on `(ticker, event_date, scanner_type)`. Checks for existing "Test" universe before creating.

**Output**: Prints summary of what was created/skipped.

## Acceptance Criteria

- [ ] "Clear History" button visible next to "Run Scanner" on the Stock Detail page
- [ ] Confirmation modal prevents accidental deletion (must click Confirm)
- [ ] `DELETE /api/scanner/events/{ticker}` deletes all `scanner_events` for the given ticker and returns `{ ticker, deleted_count }`
- [ ] Event list (`<RecentEvents>`) refreshes immediately after clearing
- [ ] No effect on other stocks' events or on `scanner_runs` history
- [ ] Seed script creates a "Test" universe with AAPL/TSLA/NVDA and sample events
- [ ] Seed script is idempotent (safe to re-run)
- [ ] Running the seed script then navigating to a stock detail page shows events that can be cleared

## Out of Scope

- Automated integration tests (tracked in [#25](https://github.com/omniscient/markethawk/issues/25))
- Bulk clear across all tickers
- Undo/soft-delete functionality
