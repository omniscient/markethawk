# Scanner Validation Skill — Design Spec

**Date:** 2026-05-14  
**Issue:** [#5 — Scanner validation skill: guided day-by-day QA walkthrough](https://github.com/omniscient/markethawk/issues/5)  
**Status:** Pending Review

## Overview

The scanner produces high volumes of signals across many tickers and dates. Without a structured QA process, verifying correctness, catching false positives, and tuning thresholds requires manually browsing the UI — which is slow, inconsistent, and loses institutional knowledge. This feature adds a `/validate-scanner` Claude Code skill that drives a systematic, day-by-day review of scanner output against real market data, persists verdicts to the database, and surfaces actionable threshold-tuning suggestions.

## Requirements

From the issue and Q&A refinement:

1. The skill accepts a scanner type and date range, then steps through one trading day at a time.
2. For each signal, it presents: ticker, scanner_type, key indicator values from `indicators` JSONB, which criteria were met/missed from `criteria_met` JSONB, prior close, opening price, and outcome data (MFE/MAE from `/api/outcomes/event/{id}`) when available.
3. For each signal, the skill prints a clickable chart URL pointing to `http://localhost:3333/stock/{ticker}?date=YYYY-MM-DD`.
4. The frontend StockDetailPage must accept a `?date=YYYY-MM-DD` query param and center the chart on that date.
5. The user can assign one verdict per signal:
   - **confirm** — signal was valid
   - **reject** — false positive, with a reason category (noise, too_late, stale_data, split_artifact, threshold_too_loose, other)
   - **enhance** — correct detection but criteria could be tightened. For `SystemConfig`-backed thresholds, the skill can patch the value immediately via `PATCH /api/system/config` and re-scan that day to show before/after impact. For hardcoded thresholds, it records a structured suggestion (threshold name, current value, proposed value, rationale) for offline review.
   - **skip** — pass without recording
   - **quit** — save cursor and exit cleanly
6. Progress is persisted in `Docs/scanner-validation/{scanner_type}_progress.json` (session cursor only: current day, signal index, in-progress day verdicts).
7. Completed verdicts are written to a new `signal_reviews` PostgreSQL table via a new API endpoint.
8. At session completion, the skill automatically generates and prints a summary report. The report is also available on demand via `/validate-scanner report` (reads from the progress JSON and DB).
9. The skill works for all scanner types: `pre_market_volume_spike`, `oversold_bounce`, `liquidity_hunt` (alias for `liquidity_hunt_pre` + `liquidity_hunt_post`), `live_volume_spike`, `live_price_move`. The live scanner types (`live_volume_spike`, `live_price_move`) produce events only during live sessions and will likely return no results for historical date ranges — the skill should warn the user if a live type is requested.
10. Invocation supports both positional args (`/validate-scanner pre_market_volume_spike 2025-01-01 2025-01-31`) and interactive prompting if args are omitted.
11. `/api/scanner/results` must accept `start_date` and `end_date` query parameters to enable per-day event fetching.

## Architecture

### Components

```
/validate-scanner skill
  │
  ├── Backend changes
  │     ├── GET /api/scanner/results — add start_date/end_date params
  │     ├── POST /api/signal-reviews — create verdict
  │     └── GET /api/signal-reviews  — list by scanner_type (for report)
  │
  ├── New model: SignalReview (signal_reviews table)
  │     └── Alembic migration required
  │
  ├── Frontend change
  │     └── StockDetailPage: read ?date=YYYY-MM-DD, center chart
  │
  └── Skill files
        ├── .claude/skills/validate-scanner/SKILL.md
        └── Docs/scanner-validation/{scanner_type}_progress.json  (runtime)
```

### Backend: Results Endpoint Date Filter

Add two optional query parameters to `GET /api/scanner/results`:

```python
start_date: date | None = Query(None)
end_date:   date | None = Query(None)
```

When present, append to the existing query:

```python
if start_date:
    query = query.where(ScannerEvent.event_date >= start_date)
if end_date:
    query = query.where(ScannerEvent.event_date <= end_date)
```

`event_date` is already an indexed column on `scanner_events`. No schema change needed.

### New Model: SignalReview

```python
class SignalReview(Base):
    __tablename__ = "signal_reviews"

    id: Mapped[int] = mapped_column(primary_key=True)
    scanner_event_id: Mapped[int] = mapped_column(
        ForeignKey("scanner_events.id", ondelete="CASCADE"), index=True
    )
    verdict: Mapped[str]           # "confirmed" | "rejected" | "enhanced"
    reject_reason: Mapped[str | None]   # nullable; e.g. "threshold_too_loose"
    notes: Mapped[str | None]           # nullable free text
    enhance_suggestion: Mapped[dict | None] = mapped_column(JSONB)
    # {threshold, current_value, proposed_value, rationale, file, line_hint}
    reviewed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    reviewed_by: Mapped[str | None]     # reserved for future multi-user

    event: Mapped["ScannerEvent"] = relationship(back_populates="reviews")
```

Add `reviews: Mapped[list["SignalReview"]] = relationship(...)` to `ScannerEvent`.

Alembic migration: `alembic revision --autogenerate -m "add_signal_reviews"`.

### New Router: /api/signal-reviews

```
POST /api/signal-reviews
  Body: { scanner_event_id, verdict, reject_reason?, notes?, enhance_suggestion? }
  Returns: created SignalReview

GET /api/signal-reviews
  Params: scanner_type (required), start_date?, end_date?
  Returns: list of SignalReview joined with ScannerEvent fields (ticker, event_date, scanner_type)
```

The POST endpoint validates that `scanner_event_id` references a real `ScannerEvent` row and that `verdict` is one of the three valid values. `reject_reason` is required when `verdict == "rejected"`.

### Frontend: StockDetailPage Date Parameter

`StockDetailPage` at `/stock/:ticker` should read `useSearchParams()` for a `date` parameter (ISO format `YYYY-MM-DD`). When present, the chart initial range should center on that date — specifically, the Lightweight Charts (TradingView) instance should scroll to that date on mount. The visible range should show ±5 trading days around the target date. If no date param is present, behavior is unchanged (default to recent data).

### Skill: Session Flow

```
/validate-scanner [scanner_type] [start_date] [end_date]
```

1. **Parse args / prompt** — if scanner_type omitted, show menu of known types; if dates omitted, prompt for them. Validate scanner_type against known values.

2. **Load or create cursor** from `Docs/scanner-validation/{scanner_type}_progress.json`:
   ```json
   {
     "scanner_type": "pre_market_volume_spike",
     "start_date": "2025-01-01",
     "end_date": "2025-01-31",
     "days_completed": ["2025-01-02"],
     "current_day": "2025-01-06",
     "current_signal_index": 0,
     "enhance_suggestions": []
   }
   ```
   If a cursor exists and the date range matches, resume from `current_day` / `current_signal_index`. If the date range differs, ask the user whether to start fresh or continue.

3. **Day loop** — for each trading day (Monday–Friday, skipping market holidays from `MarketHoliday` table):
   a. `GET /api/scanner/results?scanner_type={type}&start_date={day}&end_date={day}&limit=100`
   b. If no events: print "No signals for {day}" and advance.
   c. For each event (starting at `current_signal_index` if resuming):
      - Print signal summary block (see below)
      - Print chart URL: `http://localhost:3333/stock/{ticker}?date={event_date}`
      - Prompt: `[c]onfirm / [r]eject <reason> / [e]nhance / [s]kip / [q]uit`
      - Handle input; write verdict to DB via POST `/api/signal-reviews`; update cursor JSON
   d. Print day summary: N confirmed, N rejected (top reason), N enhanced, N skipped
   e. Mark day complete in cursor, advance to next day

4. **Signal summary block** (printed to terminal):
   ```
   ─────────────────────────────────────────
   AAPL  |  2025-01-15  |  pre_market_volume_spike  |  HIGH
   Prior close: $182.45   Open: $185.20   (+1.5%)

   Indicators:
     volume_spike_ratio:  6.8x  ✓ (threshold: 4x)
     pre_market_volume:   1.2M  ✓ (min: 100k)
     avg_volume_20d:      3.4M  ✓ (min: 500k)

   Criteria met: volume_spike ✓  liquidity ✓  gap ✓

   Outcome (if available):
     MFE: +3.2% at 45 min  |  MAE: -0.8%  |  EOD: +2.1%

   Chart: http://localhost:3333/stock/AAPL?date=2025-01-15
   ─────────────────────────────────────────
   ```

5. **Completion / report** — on final day completion (or `/validate-scanner report`):
   - Query `GET /api/signal-reviews?scanner_type={type}&start_date={start}&end_date={end}`
   - Print:
     - Days reviewed, total signals, confirm/reject/enhance/skip counts and rates
     - Most common rejection reasons (ranked)
     - All enhance suggestions grouped by threshold, with count of affected days
     - Any outcome data correlation (e.g., confirmed signals had higher avg MFE)

### Skill: Progress JSON as Source of Truth for Resumability

The local JSON stores the cursor only — it is not the canonical verdict record. The DB is canonical. If the JSON is deleted, verdicts are not lost (they remain in `signal_reviews`), but resumability requires the cursor. This is an acceptable trade-off: the JSON is cheap to recreate by asking the user which day to restart from.

The skill writes the cursor to disk after every verdict (not just at day boundaries) so a crash mid-day loses at most the current signal's interaction.

## Alternatives Considered

### A — Local JSON only, no DB table

Simple and requires no backend changes beyond the date filter. But verdicts are invisible to the API, the EdgeExplorer, and any future analytics. The established codebase pattern stores all signal-quality data in PostgreSQL (`ScannerOutcomeSummary`, `ScannerOutcomeSnapshot`). A local-only approach creates a maintenance island and breaks queryability. Rejected.

### B — DB only (no local JSON cursor)

Pure DB storage has no natural place for in-progress session state (which signal index within a day, which day are we on). Forcing this into the DB would require a `ValidationSession` table with partial/nullable rows — more complex than a tiny JSON cursor file. Rejected.

### C — "Enhance" as live code edits (as originally specified in the issue)

The issue proposed: propose a code change to `scanner.py`, apply it, re-run the day, show the diff. Making the skill edit `scanner.py` mid-session is high blast radius for a QA tool — a mistake corrupts production code. Rejected.

However, several thresholds ARE runtime-configurable via the `SystemConfig` table and the existing `PATCH /api/system/config` endpoint — no source edit needed:

| Config key | Default | Description |
|---|---|---|
| `timesfm_fallback_multiplier` | 4.0 | Volume multiplier when TimesFM is off |
| `timesfm_anomaly_threshold` | 2.0 | Score cutoff when TimesFM is enabled |
| `timesfm_min_history_bars` | 30 | Minimum history bars required |
| `timesfm_enabled` | false | Use ML model vs static multiplier |

**Chosen approach (hybrid)**: For `SystemConfig`-backed params, enhance can patch the value, re-scan the day via `POST /api/scanner/run`, and show before/after event counts. For hardcoded inline thresholds in `scanner.py` (e.g. `pre_market_volume > 100000`, `avg_volume_20d > 500000`, RSI bounds), the skill records a structured suggestion object only — the session summary prints a ranked change list that the user or an Archon workflow can act on deliberately. The cursor JSON captures both applied changes and pending suggestions.

## Open Questions

- **Market holiday detection**: The day loop needs to skip non-trading days. The `MarketHoliday` table exists but has no API endpoint. The skill should query it directly or the spec should add a `GET /api/system/market-holidays` endpoint. Non-blocking — the skill can start with weekday-only filtering and a TODO comment.
- **Pagination within a day**: If a single day has >100 signals (unusual but possible for broadly-configured universes), the current design fetches limit=100. The skill should handle pagination if needed, or the user can start with an assumption that days rarely exceed 100 events.
- **`/validate-scanner report` cross-session**: The report command without a date range generates a report for the most recently active scanner_type. With a date range, it scopes the DB query. Edge case: if the user ran two different scanner types, they need to specify which one. The skill should prompt if scanner_type is ambiguous.

## Assumptions

- **The frontend runs at `localhost:3333`** — the chart URL is hardcoded to this port. If the user runs the frontend on a different port, they can click and modify the URL. No dynamic detection needed.
- **Lightweight Charts (TradingView) supports scroll-to-date** — the `scrollToPosition` or `setVisibleRange` API is available. If the library version doesn't support this, a visible range parameter can approximate it. (To verify: check frontend/package.json for the `lightweight-charts` version.)
- **All scanner types share the `indicators` and `criteria_met` JSONB structure** — the signal summary block can render any key-value pairs without schema-specific logic. If a scanner type stores indicators under different keys, the summary will still display them correctly (generic rendering).
- **The user is authenticated** (no auth system exists in this codebase) — the `reviewed_by` field in `SignalReview` is nullable and reserved for future use.
- **`PATCH /api/system/config` exists and accepts arbitrary key-value payloads** — confirmed at `backend/app/routers/system.py:188`. Live-apply enhance for `SystemConfig`-backed params (TimesFM thresholds) works without fallback.
