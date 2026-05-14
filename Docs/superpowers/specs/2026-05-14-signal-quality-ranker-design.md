# Signal Quality Ranker — Design Spec

**Date**: 2026-05-14
**Status**: Pending Review
**Issue**: #23 — feat(phase-2c): Signal quality ranker

## Problem

MarketHawk fires scanner events but gives users no mechanism to prioritize which signals are most likely to lead to favorable price action. The existing "Score" column shows a `criteria_met` ratio (e.g. "5/5"), which only indicates whether a signal passed its own thresholds — not whether it is statistically stronger than others in the same run. With dozens of signals per scan, users must manually evaluate each one rather than focusing on the highest-conviction opportunities.

## Solution

Attach a `signal_quality_score` (Float, 0.0–1.0) to every `ScannerEvent` at creation time. The score is a lightweight weighted sum of normalized indicator values, with weights stored in `SystemConfig` so they can be updated from Phase 2b analysis without a code deploy. The scanner results UI sorts by score descending by default, and EdgeExplorer gains a "Signal Quality Validation" chart to confirm the score correlates with actual post-signal returns.

## Requirements

### Core Scoring
- `signal_quality_score` (Float, nullable) added as a dedicated column on `ScannerEvent` so it can be indexed and sorted at the database level.
- Score is computed synchronously inside `ScannerService._save_event()` at event creation time — all inputs (indicators dict + SystemConfig weights) are in-memory at that point and the computation is trivially fast (<1 ms).
- Score is recomputed and updated when `_save_event()` upserts an existing event row (same day, same ticker, same scanner type).
- The live scanner's event creation path (`live_scanner/`) must also invoke the scoring function to score `live_volume_spike` and `live_price_move` events.
- When `signal_ranker_enabled` SystemConfig key is `'false'`, `signal_quality_score` is left `NULL` for new events; existing scored events are unaffected.

### Scoring Function
```python
def compute_signal_quality_score(indicators: dict, weights: dict) -> float:
    """
    Weighted sum of normalized feature values.
    Handles null features by re-normalizing over present features only.
    Returns a float in [0.0, 1.0], rounded to 3 decimal places.
    """
    NORMALIZATION_CAPS = {
        "volume_spike_ratio":   20.0,
        "gap_pct":              20.0,   # absolute value; gaps beyond 20% are all treated as max
        "relative_volume":      20.0,
        "volume_anomaly_score": 5.0,    # TimesFM z-score; ≥5 is extreme
        "float_rotation_pct":   50.0,
    }
    total_weight = 0.0
    score = 0.0
    for feature, weight in weights.items():
        value = indicators.get(feature)
        if value is None:
            continue
        cap = NORMALIZATION_CAPS.get(feature, 1.0)
        normalized = min(abs(float(value)) / cap, 1.0)
        score += weight * normalized
        total_weight += weight
    if total_weight == 0.0:
        return 0.0
    return round(score / total_weight, 3)  # re-normalize so score stays 0.0–1.0
```

`gap_pct` uses `abs()` because a large negative gap (gap-down) is equally meaningful as a gap-up; only the magnitude matters for signal strength.

### Config (SystemConfig Keys)

| Key | Type | Default value |
|-----|------|---------------|
| `signal_ranker_enabled` | string `'true'`/`'false'` | `'true'` |
| `signal_ranker_weights` | JSON string | See baseline weights below |
| `signal_ranker_version` | string | `'0.1.0-baseline'` |

**Baseline weights** (seeded by migration when keys are absent):
```json
{
  "volume_spike_ratio": 0.35,
  "gap_pct": 0.25,
  "relative_volume": 0.20,
  "volume_anomaly_score": 0.15,
  "float_rotation_pct": 0.05
}
```

Rationale: `volume_spike_ratio` is the primary criterion the scanner was built around; `gap_pct` is the strongest secondary pre-market signal; `relative_volume` overlaps with `volume_spike_ratio` but is recorded independently; `volume_anomaly_score` (TimesFM output) is meaningful but nullable; `float_rotation_pct` is useful but sparse.

Weights are read once per scan execution (not per event) to avoid repeated DB roundtrips. They are deserialized with `json.loads()` alongside the existing TimesFM config fetch pattern in `scanner.py`.

### Database
- New column: `signal_quality_score FLOAT` on `scanner_events`, nullable (existing rows have no score).
- New index: `idx_scanner_events_score ON scanner_events(signal_quality_score DESC NULLS LAST)`.
- Three new `system_config` rows seeded in the migration (INSERT ... ON CONFLICT DO NOTHING so existing rows aren't clobbered).

### API
- `GET /api/scanner/results` response: include `signal_quality_score` (float or null) in each `ScannerEvent` object.
- `GET /api/scanner/results` sort parameter: accept `sort_by=signal_quality_score` (new default), `sort_order=desc` (new default). Null-score events sort last.
- New endpoint: `GET /api/scanner/signal-quality-distribution` — for EdgeExplorer. Joins `ScannerEvent` with `ScannerOutcomeSummary` (where `is_complete = true`), groups by score decile, returns avg `eod_pct_change` and `follow_through` rate per decile. Query params: `scanner_type` (optional), `start_date`, `end_date`.

```json
{
  "deciles": [
    {"decile": "0.0–0.1", "count": 12, "avg_eod_pct": -0.3, "follow_through_rate": 0.25},
    {"decile": "0.7–0.8", "count": 31, "avg_eod_pct": 2.1,  "follow_through_rate": 0.68},
    ...
  ]
}
```

### Frontend — ScannerResults
- The existing "Score" column (currently shows `criteria_met` ratio) is repurposed: it now displays the `signal_quality_score` badge.
- Badge color: green if `score >= 0.7`, yellow if `0.4 <= score < 0.7`, grey if `score < 0.4`, dash (`—`) if null.
- The `criteria_met` ratio (e.g. "5/5") is demoted to a `title` tooltip on the badge element.
- The "Score" column header becomes a `SortableHeader` with `sortKey="signal_quality_score"`.
- Parent component default sort changes to `{ sortBy: "signal_quality_score", sortOrder: "desc" }`.
- Null scores sort last. Users revert to date order by clicking the Date column header (existing pattern).

### Frontend — EdgeExplorer
- New chart section: **"Signal Quality Validation"**, placed alongside the existing "Gapper Retention Correlation" chart.
- Calls `GET /api/scanner/signal-quality-distribution`.
- Renders a Recharts `ComposedChart`: bar series for avg `eod_pct_change` per decile (left Y-axis), line series for `follow_through_rate` (right Y-axis, 0–100%).
- X-axis: score decile labels (`0.0–0.1`, …, `0.9–1.0`).
- Shows a "No outcome data yet" empty state when `ScannerOutcomeSummary` has no complete rows.
- `signal_ranker_version` is fetched from `/api/system/config` (or embedded in the distribution response) and shown as a subtitle: `Weight set: 0.1.0-baseline`.
- EdgeExplorer filters (scanner_type, date range) apply to this chart.

## Architecture

### Scoring flow (batch scanner)
```
run_scanner Celery task
  └── ScannerService.run()
        ├── load SystemConfig keys: signal_ranker_enabled, signal_ranker_weights, signal_ranker_version
        └── per ticker: _save_event(db, ticker, ..., indicators, ...)
              ├── compute_signal_quality_score(indicators, weights)   ← new, synchronous
              ├── event.signal_quality_score = score
              └── db.flush()
```

### Scoring flow (live scanner)
```
live_scanner/conditions.py: check_conditions()
  └── write ScannerEvent to DB
        └── call load_ranker_config(db)  ← reads SystemConfig each time (live scanner is long-running, config may change)
        └── call compute_signal_quality_score(indicators, weights)   ← new
```

The live scanner is a long-running process (not a per-scan Celery task), so it re-reads ranker config from SystemConfig on each event rather than caching at startup — this ensures weight updates take effect without restarting the container.

The scoring function lives in `backend/app/services/signal_ranker.py` (new file) so both the batch scanner and live scanner can import it without creating a circular dependency.

### File changes
| File | Change |
|------|--------|
| `backend/app/models/scanner_event.py` | Add `signal_quality_score` Float column |
| `backend/app/services/signal_ranker.py` | New: `compute_signal_quality_score()`, `load_ranker_config()` |
| `backend/app/services/scanner.py` | Load ranker config once per scan; call scorer in `_save_event()` |
| `backend/app/services/event_helpers.py` | No change |
| `backend/live_scanner/conditions.py` | Import and call scorer on event creation |
| `backend/app/routers/scanner.py` | Update results schema, add sort params, add `/signal-quality-distribution` endpoint |
| `backend/app/schemas/scanner.py` | Add `signal_quality_score: float | None` to `ScannerEventResponse` |
| `alembic/versions/` | Migration: add column + index + seed SystemConfig rows |
| `frontend/src/api/scanner.ts` | Add `signal_quality_score?: number` to `ScannerEvent` interface |
| `frontend/src/components/ScannerResults.tsx` | Replace criteria_met badge with score badge; update default sort |
| `frontend/src/pages/EdgeExplorer.tsx` | Add Signal Quality Validation chart |
| `frontend/src/api/scanner.ts` | Add `getSignalQualityDistribution()` API function |

## Alternatives Considered

### A: Async scoring (Celery task, similar to `evaluate_scanner_alerts`)
Score computed in a background task after the event row is flushed. Consistent with the alert evaluation pattern. Rejected because: the computation is <1 ms with no I/O, adding async latency means the score is missing from the first API response the user sees (especially for on-demand scans where results appear immediately), and it requires tracking task state for a trivial operation.

### B: On-read computation (no column, no storage)
Score computed dynamically in the API handler or ORM property; never stored. No migration required. Rejected because: the score can't be efficiently indexed or sorted at the DB level (would require fetching all events and sorting in Python), score is unavailable to WebSocket push events and future downstream consumers, and SystemConfig weights would be fetched on every API request.

### C (chosen): Synchronous inline, stored column
Computed and stored at event creation. Indexed. Available immediately in API responses and WebSocket events. Weights fetched once per scan execution (not per event).

## Open Questions (non-blocking)

- Should Phase 2b weights be scanner-type-specific (separate weight sets for `pre_market_volume_spike` vs. `oversold_bounce`)? The current design uses a single weight set for all scanner types. When Phase 2b produces results, this can be extended by making `signal_ranker_weights` a dict keyed by scanner type.
- Should historical `ScannerEvent` rows be backfilled with scores after the migration? The column is nullable so old events without scores are valid. A one-off backfill script could be run later if needed.
- The normalization caps (`NORMALIZATION_CAPS`) are hardcoded constants. If Phase 2b analysis reveals that `volume_spike_ratio` commonly exceeds 20× for high-quality signals, the cap should be revisited.

## Assumptions

- **Phase 2b is not a blocker.** The baseline weights are sufficient to deliver value and generate EdgeExplorer validation data. Phase 2b weights can replace them via a `system_config` update.
- **`ScannerOutcomeSummary` rows exist.** The EdgeExplorer chart shows an empty state if no complete outcome rows are present. The existing scorecard pipeline (from the Phase 2 scanner scorecard spec) populates these rows.
- **Live scanner uses the same `ScannerEvent` model** and writes to the same table. The scorer is called before the DB INSERT in `live_scanner/conditions.py`.
- **Normalization caps are unit-specific constants**, not business-configurable. The weights are the tunable business decision; the caps are implementation constraints.
- **`gap_pct` is stored as a percentage float** (e.g. `5.2` = 5.2%), consistent with existing indicator storage in `scanner.py`.
