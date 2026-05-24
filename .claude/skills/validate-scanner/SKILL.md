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
  docker compose exec backend python -c "
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
  {key}: {value}   (for each key, value in event["indicators"].items())

Criteria met:
  {key}: ✓ / ✗    (for each key, value in event["criteria_met"].items())
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
| `c` | Write `verdict=confirmed` to DB (POST /api/scanner/events/{event_uuid}/review). Advance index. |
| `r noise` / `r too_late` / `r stale_data` / `r split_artifact` / `r threshold_too_loose` / `r other` | Write `verdict=rejected, reject_reason=<reason>`. Advance. |
| `r` (no reason) | Prompt: `Reason [noise/too_late/stale_data/split_artifact/threshold_too_loose/other]: ` then proceed as above. |
| `e` | Run enhance flow (see §3c). Advance. |
| `s` | Skip — do NOT write to DB. Advance index. |
| `q` | Save cursor, print session summary so far, exit. |

**After each verdict (except skip/quit), POST to DB:**
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
   curl -s "http://localhost:8000/api/scanner/events/reviews?scanner_type={scanner_type}&start_date={start_date}&end_date={end_date}" | python3 -m json.tool
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

- If the backend is unreachable: print `Backend not responding. Is docker compose up?` and exit.
- If an event has no `indicators` key: treat as empty dict; print `(no indicators)`.
- If outcome fetch returns 404: treat as `Outcome: not yet tracked`.
- If `Docs/scanner-validation/` directory doesn't exist: create it with `mkdir -p Docs/scanner-validation`.
