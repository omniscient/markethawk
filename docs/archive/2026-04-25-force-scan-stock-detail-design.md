# Force Scan on Stock Detail Page — Design Spec

**Date:** 2026-04-25  
**Status:** Approved

---

## Overview

Add a "Run Scanner" button to the Stock Detail page that lets the user trigger a historical backfill scan for one or more scanner types over a chosen date range. The scan runs as a background Celery task, streams progress via Redis/WebSocket, and automatically refreshes the Scanner Event History card on completion.

---

## Scope

This feature has two parts that must be delivered together:

1. **Scanner refactor (prerequisite):** `pre_market_volume_spike` and `oversold_bounce` scanners are refactored to be fully DB-driven, matching how `liquidity_hunt` already works.
2. **Range scan feature:** New endpoint, Celery task, WebSocket channel, dialog UI, and status indicator.

---

## Part A — Scanner Refactor

### Problem

`run_pre_market_scan` and `run_oversold_bounce_scan` currently:
- Call `StockDataService.get_historical_data()` and `get_pre_market_data()` — live Polygon API calls per ticker
- Hardcode `event_date = get_market_today()` — cannot run against historical dates

`run_liquidity_hunt_scan` is the correct pattern: it queries `StockAggregate` directly and works across any date range.

### Changes

All three scanner methods are refactored. `run_pre_market_scan` and `run_oversold_bounce_scan` are rewritten to:
- Read daily OHLCV history from `StockAggregate` where `timespan='day'` (replaces `get_historical_data`)
- Read pre-market/session metrics from `StockAggregate` where `timespan='minute'` via the existing `calculate_day_metrics()` (replaces `get_pre_market_data`)
- Accept `event_date` as an explicit parameter (defaults to `get_market_today()` to keep the existing `/api/scanner/run` endpoint working unchanged)

The existing `POST /api/scanner/run` endpoint is not changed. The regular scheduled scanner flow continues to work — data freshness is handled by a separate fetch/sync step, not inline during scan execution.

### Data requirements (all three scanner types)

| Scanner type | DB data needed |
|---|---|
| `pre_market_volume_spike` | `timespan='day'` rows (20d/50d avg volume, previous close) + `timespan='minute'` rows (pre-market volume/high, session metrics) |
| `liquidity_hunt` | `timespan='minute'` rows (pre-market volume/high, previous close, session metrics) |
| `oversold_bounce` | `timespan='day'` rows (RSI-2, RSI-5, rolling volume, previous close) + `timespan='minute'` rows (session metrics) |

---

## Part B — Range Scan Feature

### Backend

**New endpoint:** `POST /api/scanner/run-range`

Request body:
```json
{
  "ticker": "AAPL",
  "scanner_types": ["pre_market_volume_spike", "liquidity_hunt"],
  "start_date": "2025-01-01",
  "end_date": "2025-04-25",
  "fetch_missing_data": true
}
```

Response (immediate):
```json
{ "task_id": "<uuid>", "status": "queued" }
```

**Celery task:** `run_range_scan(task_id, ticker, scanner_types, start_date, end_date, fetch_missing_data)`

Execution steps:
1. If `fetch_missing_data=true`: fetch and store both `timespan='day'` and `timespan='minute'` aggregates for the ticker across the full date range via Polygon. Uses the existing `StockDataService` fetch+store methods.
2. Compute list of trading days in the range (skip weekends; no holiday calendar for now).
3. For each day × each selected scanner type: call the refactored `run_*_scan_for_date(ticker, event_date, db)` method. Deduplication is already handled by `_save_event` via the `(ticker, event_date, scanner_type)` unique check — re-running overwrites existing events.
4. Publish progress to Redis channel `scan_task:{task_id}`:
   - Per day: `{"status": "progress", "day": "2025-01-03", "done": 12, "total": 80}`
   - On finish: `{"status": "completed", "events_detected": N}`
   - On error: `{"status": "failed", "error": "..."}`

**New WebSocket endpoint:** `GET /api/live/ws/scan-task/{task_id}`

Subscribes to Redis channel `scan_task:{task_id}` and streams JSON messages to the client. Identical structure to the existing `/api/live/ws/{ticker}/{resolution}` handler.

### Frontend

**Button:** "Run Scanner" added to the chart card header actions on `StockDetailPage`, next to the existing "Catch Up" button. Uses the `Zap` icon (already imported). Same styling as other header action buttons.

**Dialog component:** `ForceScanDialog` (new file: `frontend/src/components/ForceScanDialog.tsx`)

Fields:
| Field | Type | Default | localStorage key |
|---|---|---|---|
| Scanner types | Multi-checkbox | all three checked | `force_scan_types` |
| Start date | Date input | 30 days before today | `force_scan_start_date` |
| End date | Date input | Today | `force_scan_end_date` |
| Fetch missing data | Checkbox | `true` | `force_scan_fetch_data` |

- All values are loaded from `localStorage` on dialog open and saved on submit.
- Submit button labeled "Run Scan", disabled if no scanner type is selected.
- End date must be ≥ start date (client-side validation only).

**Hook:** `useScanTask(taskId: string | null)` (new file: `frontend/src/hooks/useScanTask.ts`)

Mirrors `useLiveStockData` pattern:
- Connects to `/api/live/ws/scan-task/{taskId}` when `taskId` is non-null
- Parses progress messages, exposes `{ status, done, total, eventsDetected, error }`
- On `status: "completed"`: calls `queryClient.invalidateQueries({ queryKey: ['scannerResults', { ticker }] })` to refresh Scanner Event History
- Reconnects on disconnect (same logic as `useLiveStockData`)
- Cleans up WebSocket on `taskId` change or unmount

**Status indicator:** Rendered inline near the "Run Scanner" button while `taskId` is active:
- In progress: spinner + `"Scanning… 12 / 80 days"`
- Completed: green checkmark + `"Done — N events found"` (clears after 5 seconds)
- Failed: red text with error message

---

## Files Changed

### Backend
- `backend/app/services/scanner.py` — refactor all three scan methods to be DB-driven with an explicit `event_date` parameter; `run_liquidity_hunt_scan` gains a date-range filter; add `run_*_scan_for_date` per-day entry points used by the Celery task
- `backend/app/routers/scanner.py` — add `POST /api/scanner/run-range` endpoint
- `backend/app/routers/live_data.py` — add `GET /api/live/ws/scan-task/{task_id}` endpoint
- `backend/app/tasks.py` — add `run_range_scan` Celery task
- `backend/app/schemas/scanner.py` — add `ScannerRangeRequest` schema

### Frontend
- `frontend/src/components/ForceScanDialog.tsx` — new dialog component
- `frontend/src/hooks/useScanTask.ts` — new WebSocket hook
- `frontend/src/api/scanner.ts` — add `runScannerRange()` API call
- `frontend/src/pages/StockDetailPage.tsx` — wire button, dialog, status indicator

---

## Out of Scope

- Holiday calendar for trading day computation (weekends only for now)
- Progress granularity below per-day (no per-scanner-type sub-progress)
- Cancelling an in-progress scan task
- Running range scans for multiple tickers at once
