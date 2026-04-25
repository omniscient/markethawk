# Liquidity Hunt Scanner — Redesign

**Date:** 2026-04-25
**Status:** Design — pending implementation
**Author:** brainstorming session with Frank Germain

## Problem

The existing `liquidity_hunt` scanner in `backend/app/services/scanner.py:248-436` does not produce valid signals. Concrete defects:

1. **Wrong volume baseline.** The "20-day average volume" is computed from the last 20 *minute* bars before the event date (`scanner.py:321-326`), not 20 *daily* averages. This yields an essentially meaningless number on the order of one minute of trading.
2. **Pre-market vs. regular session conflation.** `is_significant_volume` compares pre-market volume to a 2-day average of regular-session minute bars (`scanner.py:339-341`). Pre-market and regular-session activity have fundamentally different normal ranges and cannot be compared apples-to-apples this way.
3. **Pre + post lumped together.** Candidate selection ORs `is_pre_market` and `is_after_market` into one bucket (`scanner.py:269-272`), losing the distinction between two structurally different anomalies.
4. **Wrong day-shape criterion.** The current scanner looks for *spike + retrace* during the day. The intended pattern is *off-hours volume anomaly + a quiet, normal day session* — a fund moving size off-hours that produces no day-session footprint.
5. **Volume floor too low.** A 50K extended-hours volume threshold passes nearly every active ticker.

The user's intent: identify days where a fund accumulated size during pre-market or after-market off-hours, leaving a heavy off-hours volume anomaly behind, but where the regular session that day was quiet — no volume blow-out, no big intraday range. The "hunt" was conducted while nobody was watching.

## Goal

Replace the broken scanner with one that fires only on the actual pattern, with measurable, tunable criteria, and store enough information in the event for a reviewer to validate it visually.

## Scanner output: two event variants

Each variant is a distinct `ScannerEvent.scanner_type`. Both can fire on the same ticker on the same day; they are independent observations.

| `scanner_type` | Off-hours window | Pattern |
|---|---|---|
| `liquidity_hunt_pre` | 4:00–9:30 AM ET (pre-market) | Heavy pre-market vol + UP move ≥ 10%, then quiet regular session |
| `liquidity_hunt_post` | 4:00–8:00 PM ET (after-market) | That day's regular session was quiet, then heavy after-market vol + UP move ≥ 10% |

**Reference close for the up-spike check (criterion 3):**
- `liquidity_hunt_pre`: the regular close of the *previous* trading day (i.e., a gap-up at pre-market high).
- `liquidity_hunt_post`: the regular close of the *same calendar day* (i.e., a push-up after the regular session ended).

**"Quiet day" reference session:** in both variants, the regular session evaluated for criteria 4 and 5 is the regular session of `event_date` — the same calendar day as the off-hours window. (For the pre variant, the off-hours preceded that day's regular session; for the post variant, the off-hours followed it. Either way, the regular session is `event_date`'s.)

## Criteria

All six checks must hold for an event to fire. Thresholds are stored in `ScannerConfig.parameters` and are tunable per-config.

| # | Check | Default threshold |
|---|---|---|
| 1 | Off-hours vol ≥ N × 20-day avg off-hours vol *(same session type)* | **N = 4** |
| 2 | Off-hours vol ≥ M × 20-day avg total daily vol | **M = 0.30** (30%) |
| 3 | Off-hours session high ≥ K × reference close (per variant, see above) | **K = 1.10** (10%) |
| 4 | Regular vol ≤ P × 20-day avg regular vol | **P = 1.20** |
| 5 | Regular `(high − low) / open` ≤ Q × 20-day avg of same metric | **Q = 1.50** |
| 6 | Off-hours vol ≥ absolute floor | **50,000 shares** |

**No 20-day-avg pre-market floor.** Tickers that normally have near-zero pre-market activity are deliberately not excluded — that is the most informative case. The absolute 50K floor and the 30%-of-daily-volume materiality check together prevent meaningless ratios from firing.

**Lookback window:** 20 trading days. Skipped if fewer than 10 prior trading days of data exist for the ticker (insufficient baseline → skip).

**Direction:** UP only. The off-hours session high must exceed the previous regular close by at least 10%. Down moves do not qualify.

**Universe:** none at scanner level. Scanner runs against whatever ticker list is passed in. Universe selection is the caller's responsibility (existing universe routing handles this).

## Schedule

Single Celery beat job:

```python
'run-liquidity-hunt-scan-evening': {
    'task': 'app.tasks.run_liquidity_hunt_scheduled',
    'schedule': crontab(minute='0', hour='21', day_of_week='1-5'),
}
```

21:00 ET, Mon–Fri. After-market closes at 20:00 ET; the one-hour buffer accounts for delayed/end-of-session aggregate ingestion. Both variants run for *that day's* date over the active scanner-config universes.

The on-demand range-scan endpoint continues to work for historical backfills via the existing `tasks.py` `scanner_map` wiring.

> Open item to verify during implementation: confirm Celery is configured with `timezone='America/New_York'` (or whatever the project uses) so `hour='21'` is ET. If the project runs Celery in UTC, translate to UTC accordingly.

## Algorithm — per (ticker, event_date)

1. **Today's session metrics** — single SQL query against `stock_aggregates` for `event_date`, grouped by session flag, returning:
   - `pre_vol`, `pre_high`
   - `regular_vol`, `regular_high`, `regular_low`, `regular_open`, `regular_close`
   - `post_vol`, `post_high`
   - If no regular-session bars exist for `event_date` (halt, holiday early close, etc.), skip.
2. **Reference closes** — capture both:
   - `prior_day_close` = close of the most recent `timespan='day'` bar strictly before `event_date` (used by `liquidity_hunt_pre` for criterion 3).
   - `event_date_regular_close` = the closing print of the regular session on `event_date` itself (used by `liquidity_hunt_post` for criterion 3).
   Fallback for either: last regular-session minute close at the relevant boundary if no daily bar exists. Skip ticker if `prior_day_close` is missing. Skip the post variant only if `event_date_regular_close` is missing.
3. **20-day rolling baselines** — one batched query against `stock_aggregates` for the prior 20 trading days that have data, grouped by `date(timestamp)` and session flag. Computed in Python from the grouped rows:
   - `avg_pre_vol_20d` — mean of daily pre-market sums
   - `avg_post_vol_20d` — mean of daily post-market sums
   - `avg_regular_vol_20d` — mean of daily regular sums
   - `avg_total_daily_vol_20d` — mean of daily total sums
   - `avg_regular_range_pct_20d` — mean of `(daily_high − daily_low) / daily_open`
   - If fewer than 10 days of data, skip the ticker.
4. **Evaluate `liquidity_hunt_pre`** — apply the six criteria against pre-market values.
5. **Evaluate `liquidity_hunt_post`** — apply the six criteria against after-market values.
6. **Persist** via `ScannerService._save_event` for each variant that fires. Both can fire on the same day; they are separate event rows.

### Zero-baseline handling

If `avg_pre_vol_20d == 0` or `avg_post_vol_20d == 0`, criterion 1 (the 4× ratio) is treated as trivially satisfied. Criteria 2 (30% of daily vol) and 6 (50K absolute floor) carry the materiality load in this case.

## Indicators payload

Stored in `ScannerEvent.indicators`. Both variants share the same shape so frontend rendering is uniform; the `session` field disambiguates.

```json
{
  "session": "pre",
  "session_volume": 250000,
  "avg_session_volume_20d": 35000,
  "session_volume_ratio": 7.14,
  "session_volume_pct_of_daily": 0.42,
  "session_high": 12.50,
  "reference_close": 11.00,
  "session_spike_pct": 0.1364,
  "regular_volume": 980000,
  "avg_regular_volume_20d": 950000,
  "regular_volume_ratio": 1.03,
  "regular_range_pct": 0.018,
  "avg_regular_range_pct_20d": 0.024,
  "regular_range_ratio": 0.75,
  "opening_price": 11.05,
  "closing_price": 11.10,
  "split_in_lookback": false
}
```

`reference_close` holds the close used for criterion 3 — `prior_day_close` for the pre variant, `event_date_regular_close` for the post variant.

`split_in_lookback` is set to `true` when `recent_split_date` falls within the 20-day baseline window. The event still fires (we don't auto-skip), but reviewers know baselines may be distorted.

Existing enrichment (`market_cap`, `outstanding_shares`, `recent_split_date`, `catalyst_tags`, `catalyst_summary`, `float_rotation_pct`) is unchanged and stored in `ScannerEvent.metadata_`.

## Code organization

**New module:** `backend/app/services/liquidity_hunt.py`

Reasons:
- `scanner.py` is 687 lines and houses four scanner algorithms. A focused module per scanner is easier to read, test, and modify.
- The new logic introduces helper functions (rolling-baseline builder, session-metrics extractor) that are specific to this scanner.

**Public API of `liquidity_hunt.py`:**

```python
async def run_liquidity_hunt_scan(
    tickers: list[str],
    db: Session,
    start_date: date | None = None,
    end_date: date | None = None,
    config: dict | None = None,
) -> list[dict]: ...

async def run_liquidity_hunt_scan_for_date(
    ticker: str,
    event_date: date,
    db: Session,
) -> list[dict]: ...
```

These signatures match the existing static methods on `ScannerService`, so every existing call site (`tasks.py:1221`, the on-demand routers, etc.) is updated to import from `liquidity_hunt.py` instead of `ScannerService`. The old methods on `ScannerService` are deleted — no shim, no re-export.

`config` is the `ScannerConfig.parameters` dict; if `None`, defaults from a module-level constant are used. This lets ad-hoc / test calls work without a config row.

## Wiring changes

| File | Change |
|---|---|
| `backend/app/services/liquidity_hunt.py` | NEW — algorithm and helpers |
| `backend/app/services/scanner.py` | Delete `run_liquidity_hunt_scan` and `run_liquidity_hunt_scan_for_date` |
| `backend/app/tasks.py` | Update `scanner_map` (line 1221) to point at the new functions; add new Celery task `run_liquidity_hunt_scheduled` |
| `backend/app/core/celery_app.py` | Add `run-liquidity-hunt-scan-evening` to `beat_schedule`. Verify Celery TZ. |
| Alembic migration | Seed a default `ScannerConfig` row with `scanner_type='liquidity_hunt'` and `parameters` matching the defaults table above. Idempotent insert. (The config's `scanner_type` is the *trigger* type; emitted events use the variant types `liquidity_hunt_pre` / `liquidity_hunt_post`.) |
| Any other import sites | grep for `run_liquidity_hunt_scan` / `liquidity_hunt` and update imports |

## Edge cases

| Case | Handling |
|---|---|
| Fewer than 10 prior trading days of data | Skip ticker |
| Missing previous regular close | Skip ticker |
| `avg_pre_vol_20d == 0` (or post) | Treat ratio criterion as trivially satisfied; rely on 50K + 30% checks |
| No regular-session bars on `event_date` (halt / closure) | Skip ticker |
| Stock split inside 20-day lookback window | Set `split_in_lookback: true` in indicators; do not skip |
| Both pre and post variants qualify | Two separate `ScannerEvent` rows |
| `event_date` is today, market still open | Caller's responsibility — scheduled job runs at 21:00 ET, after close. On-demand callers passing `event_date == today` mid-day will get incomplete data and unreliable results; documented but not blocked |

## Testing

**Unit tests** in `backend/tests/services/test_liquidity_hunt.py`:

| # | Scenario | Expected |
|---|---|---|
| 1 | Clean pre-market hunt — heavy pre-market vol, 12% UP spike, normal regular vol, small range | `liquidity_hunt_pre` fires |
| 2 | Same as #1 but regular vol = 2× avg | Does not fire (criterion 4 fails) |
| 3 | Same as #1 but pre-market spike = 6% | Does not fire (criterion 3 fails) |
| 4 | Post-market mirror of #1 | `liquidity_hunt_post` fires |
| 5 | Both pre and post anomalies on same day | Two distinct events |
| 6 | Only 8 prior trading days of data | Skipped, no events |
| 7 | `avg_pre_vol_20d == 0` but session vol = 75K and = 35% of avg daily | Fires (zero-baseline handling) |
| 8 | Pre-market vol = 40K (below 50K floor) but ratio + materiality both pass | Does not fire (criterion 6 fails) |
| 9 | Recent split 5 days before event_date | Event fires; `split_in_lookback == true` in indicators |

Fixtures: in-memory `StockAggregate` rows spanning 25 trading days for synthetic tickers, parameterized to cover each scenario.

**Integration validation** (per `CLAUDE.md`):
- After implementation, hit the on-demand scan endpoint via `curl` for a known historical date and ticker.
- Confirm the returned indicators payload matches expected shape and values.
- Inspect at least one real-world event manually against a chart to validate the pattern visually.

## Out of scope

- Refactoring the other three scanners (`pre_market_volume_spike`, `oversold_bounce`, etc.) — they have their own issues but are not part of this work.
- Building a pre-aggregated daily session-rollup table. If query-time aggregation becomes a performance issue across the scanner suite, that is a separate initiative.
- Frontend changes for displaying the new event type — assumes existing event-list UI already renders unknown `scanner_type` values acceptably; if not, a minimal label/badge update will be folded into implementation.
- Stealth-accumulation variant (heavy pre-market volume with < 3% price move). Considered and explicitly removed during design.
- Down-move variant (distribution hunts). Considered and explicitly removed during design — UP only.
