# Scanner Nightly Replay-Diff Design

**Date:** 2026-06-21  
**Issue:** #392  
**Status:** Spec generated — pending review

---

## Overview

Every night, after the scheduled scanners complete, re-run the previous trading day's scans from stored `StockAggregate` data and diff the resulting signals against the live `ScannerEvent` rows that were written earlier in the day. The live run and the replay should agree. Divergence ("drift") signals data revision (Polygon correcting a bar), nondeterminism in the scanner logic, or a silent code regression. This feature makes that invisible class of bugs immediately visible.

---

## Problem Statement

The nightly scheduled scanners (liquidity_hunt, pocket_pivot, trend_pullback, and others) read live Polygon data at run time. If Polygon later revises a bar, or a code change subtly shifts detection semantics, the resulting `ScannerEvent` rows are silently wrong. There is no automated check that the scanner is deterministic against stored data. Drift is the symptom of data-quality issues (related: #387) and can also surface logic regressions at the moment they are introduced.

---

## Requirements (from Q&A)

1. **Scanner scope** — Cover all scanner types registered in the orchestrator where `ScannerDescriptor.supports_date_range=True`, gated to those with at least one active `ScannerConfig`. This includes the nightly scanners and `pre_market_volume_spike`. Do not hardcode a list; derive it from the orchestrator registry + active configs.

2. **Data-availability distinction** — A scanner that lacks stored bars for yesterday (e.g., `pre_market_volume_spike` if 1-minute bars were not retained) must record an explicit `status = "insufficient_data"` diff record rather than counting missing signals as drift.

3. **Replay logic** — Invoke the scanner's `supports_date_range` code path via `scan_orchestrator.run()` with `event_date = yesterday`. Run in dry-run mode: do not write `ScannerEvent` rows (those already exist from the live run). Collect the in-memory signal set and diff it against the DB.

4. **Diff keys** — Signals are keyed by `ticker` within a `(scanner_type, scan_date)` pair. Classify each ticker as: `matched`, `missing_in_replay` (live had it, replay didn't), or `new_in_replay` (replay found it, live didn't).

5. **Metric deltas** — For matched signals only, compare key indicator values from the live `ScannerEvent.indicators` JSONB against the replay's in-memory indicators. Report deltas exceeding tolerance (default: 5%) for `volume_ratio` and `gap_pct`.

6. **Persistence** — One `ScannerReplayDiff` row per `(scanner_type, scan_date)`, upserted on the unique constraint. Scalar indexed columns for query efficiency; JSONB for variable-length payload.

7. **Observability** — Emit a structured Seq log event per scanner per night. Increment `markethawk_replay_drift_signals_total{scanner_type, kind}` Prometheus counter where `kind ∈ {matched, missing_in_replay, new_in_replay, metric_delta}`.

8. **Alert delivery** — When drift exceeds threshold (any `missing_in_replay` ticker, or any `metric_delta` above 5%), call `system_notifier.notify_system()` with `severity="warning"`, a dedupe key of `replay_drift:{scanner_type}:{scan_date}`, and a cooldown of 86400 s (one alert per scanner per day).

9. **API** — `GET /api/v1/scanner/replay-diffs` with optional `scanner_type` and `days` (default 30, max 90) query params. Returns records ordered by `scan_date DESC`.

10. **Scheduling** — New beat task at **04:00 UTC weekdays** (after the 02:00 UTC nightly scanners complete and any late data revisions settle). Named `run_replay_diff_nightly`.

---

## Architecture / Approach

### New model: `ScannerReplayDiff`

```python
# backend/app/models/scanner_replay_diff.py
class ScannerReplayDiff(Base):
    __tablename__ = "scanner_replay_diffs"

    id          = Column(Integer, primary_key=True)
    scanner_type = Column(String(50), nullable=False, index=True)
    scan_date   = Column(Date, nullable=False, index=True)
    status      = Column(String(20), nullable=False)  # "clean" | "drift" | "insufficient_data" | "no_live_events"
    has_drift   = Column(Boolean, nullable=False, index=True)
    live_count  = Column(Integer, nullable=False)
    replay_count = Column(Integer, nullable=False)
    matched_count = Column(Integer, nullable=False)
    missing_in_replay = Column(JSONB, nullable=False, default=list)  # [ticker, ...]
    new_in_replay     = Column(JSONB, nullable=False, default=list)  # [ticker, ...]
    metric_deltas     = Column(JSONB, nullable=False, default=dict)  # {ticker: {field: delta_pct}}
    drift_kinds       = Column(JSONB, nullable=False, default=list)  # ["missing_signal","metric_delta","new_signal"]
    created_at  = Column(DateTime, default=utc_now)
    updated_at  = Column(DateTime, default=utc_now, onupdate=utc_now)

    __table_args__ = (
        UniqueConstraint("scanner_type", "scan_date", name="uq_scanner_replay_diff"),
    )
```

Follows the `ScannerRun` + `SignalAnalysisRun` convention: scalar columns for the queryable boolean/count fields; JSONB for the variable-length payload lists.

### New service: `replay_diff_service.py`

```
backend/app/services/replay_diff_service.py
```

Three stages (mirrors the scanner pipeline decomposition pattern from `pre_market_scan.py`):

1. **`_collect_live_signals(scanner_type, scan_date, db) -> dict[str, dict]`** — Query `ScannerEvent` for `(scanner_type, scan_date)`. Return `{ticker: indicators_dict}`. If empty, return empty dict (caller records `no_live_events`).

2. **`_run_replay(scanner_type, tickers, scan_date, db) -> dict[str, dict] | None`** — Import and invoke `scan_orchestrator.run()` with a no-persist wrapper (monkey-patch or argument flag to suppress `_save_event` calls). Returns `{ticker: indicators_dict}` for signals found, or `None` if insufficient data (no relevant `StockAggregate` rows for the date).

3. **`_compute_diff(live, replay, delta_tolerance) -> dict`** — Pure function. Returns the full diff payload dict used to populate `ScannerReplayDiff` columns.

Main entry point:

```python
def run_replay_diff_for_scanner(scanner_type: str, scan_date: date, db: Session) -> ScannerReplayDiff:
    ...
```

Called once per active scanner config type. Upserts the diff record, emits Seq log, increments Prometheus counters, calls `notify_system()` on drift.

### No-persist replay execution

The existing scanner functions persist signals via `alert_service.save_event()`. For replay, we need to run the detection and enrichment logic without persisting. Two approaches:

**Chosen approach**: Patch `app.services.alert_service.save_event` to a no-op for the duration of the replay call. This is the same pattern used in `backtest_service.py` which explicitly avoids writing to `scanner_events` (see `[AVOID]` memory entry). Capture signals from the in-memory `RawSignal`/`EnrichedSignal` dataclasses before the persist stage.

**Alternative**: Add a `dry_run: bool = False` parameter to `scan_orchestrator.run()`. Rejected because it threads through every scanner function and the noop-patch is cleaner for a read-only caller with no UI surface.

### Prometheus metrics

Add to `backend/app/core/metrics.py`:

```python
replay_drift_signals_total = Counter(
    "markethawk_replay_drift_signals_total",
    "Scanner replay-diff signal counts by kind",
    ["scanner_type", "kind"],
)
```

Labels match the issue spec: `kind ∈ {matched, missing_in_replay, new_in_replay, metric_delta}`.

### Celery task

```python
# backend/app/tasks/scanning.py — append
@celery_app.task(bind=True, max_retries=1, name="app.tasks.run_replay_diff_nightly")
def run_replay_diff_nightly(self):
    ...
```

Beat schedule entry at 04:00 UTC weekdays. Iterates active scanner configs, resolves yesterday's trading date, calls `run_replay_diff_for_scanner()` per unique scanner type with an active config.

### API endpoint

```python
# backend/app/routers/scanner.py — append
@router.get("/replay-diffs", response_model=list[ScannerReplayDiffSchema])
def list_replay_diffs(
    scanner_type: Optional[str] = None,
    days: int = Query(default=30, ge=1, le=90),
    db: Session = Depends(get_db),
):
    ...
```

Returns up to `days` days of records, ordered by `scan_date DESC`.

### Pydantic schema

```
backend/app/schemas/scanner_replay_diff.py
```

`ScannerReplayDiffSchema` — matches model columns. Exported from `schemas/__init__.py`.

### Alembic migration

One migration: create `scanner_replay_diffs` table with the unique constraint.

---

## Alternatives Considered

### A. Store diff as JSONB blob in a simple `ReplayDiffRecord` model

Rejected. A single opaque JSONB column can't support indexed queries on `has_drift` or `scanner_type` without expression indexes or full-row scans. The "queryable all-green record" acceptance criterion requires `WHERE has_drift = false AND scanner_type = X` — which needs indexed boolean columns.

### B. Extend `ScannerRun` with nullable replay-specific columns

Rejected. `ScannerRun` semantics are "one live scan execution." Mixing replay metadata muddies `events_detected`/`stocks_scanned` semantics and breaks existing dashboard queries and history endpoints that aggregate over `scanner_runs`.

### C. Seq + Prometheus only, rely on Grafana for alerts

Rejected. The acceptance criterion explicitly requires "injected fixture drift fires alert path in a test." Grafana alerting rules are not unit-testable in pytest. `notify_system()` is directly assertable in tests.

### D. Synthetic `ScannerEvent` of scanner_type `replay_drift`

Rejected. Pollutes the signal table and outcome dashboards (scorecard, backtest, signal reviews) with non-market rows. The `UniqueConstraint(ticker, event_date, scanner_type)` would also cause IntegrityErrors on re-runs for the same drift day.

---

## Data Flow

```
04:00 UTC (beat)
  └── run_replay_diff_nightly task
        └── for each active scanner_type with active ScannerConfig:
              1. _collect_live_signals(scanner_type, yesterday, db)
              2. _run_replay(scanner_type, tickers, yesterday, db)
                   ├── no StockAggregate rows → status="insufficient_data"
                   └── replay run (no-persist patch) → in-memory signal dict
              3. _compute_diff(live, replay, delta_tolerance=0.05)
              4. Upsert ScannerReplayDiff row
              5. Emit Seq structured log event
              6. Increment markethawk_replay_drift_signals_total counters
              7. If has_drift: notify_system("warning", dedupe_key, cooldown=86400)
```

---

## Open Questions (non-blocking)

1. **Grafana dashboard panel** — Should a Grafana panel be added to the Scanner Performance dashboard showing `markethawk_replay_drift_signals_total` over time? Not required for the acceptance criteria; can be a follow-up.

2. **Replay for pre_market_volume_spike** — 1-minute bars for pre-market are retained in `StockAggregate` but this should be verified against the universe sync cadence. If bars are routinely missing, the `insufficient_data` status will fire nightly for this scanner type. A follow-up ticket can track this separately.

3. **Tolerance configuration** — The 5% metric delta threshold is hardcoded in this spec. A future iteration could surface it as a `SystemConfig` key (`replay_diff_metric_tolerance`) for runtime adjustment without redeploy.

---

## Assumptions

- **[ASSUMPTION]** `StockAggregate` retains 1-minute bars long enough (at least 24 hours) for `pre_market_volume_spike` replay on the following night. If not, the feature degrades gracefully to `insufficient_data` status for that scanner type.
- **[ASSUMPTION]** The nightly scheduled scanners (liquidity_hunt, pocket_pivot, trend_pullback) consistently complete before 04:00 UTC so the live `ScannerEvent` rows are present when replay runs. If a nightly scan is delayed or fails, the replay will see `no_live_events` and skip drift detection for that scanner-day.
- **[ASSUMPTION]** `system_notifier.notify_system()` is already functional (merged in #570). The spec depends on it being available in the service layer.
- **[ASSUMPTION]** The replay no-persist patch (patching `save_event` to a no-op for the replay call duration) is safe in a Celery worker context (single-threaded per task). No shared-state concerns within a single task invocation.

---

## Runbook Note

**Interpreting replay drift:**

- **`missing_in_replay`** (live fired, replay didn't): Polygon likely revised the bar downward after the live scan ran. Check `StockAggregate` for the affected ticker and date, and compare with the live `ScannerEvent.indicators`. Also see data-quality ticket #387.
- **`new_in_replay`** (replay fired, live didn't): Unusual. Possible causes: live scan was cancelled or hit an error for that ticker, or the aggregate data was revised upward. Check `ScannerRun.failed_tickers` for the live run.
- **`metric_delta`** (same signal, different indicator values): Data revision or floating-point nondeterminism. Usually low severity unless delta is large (>20%).
- **`clean`**: No drift. The `ScannerReplayDiff` row with `has_drift=false` is the expected steady state.
- **`insufficient_data`**: No `StockAggregate` rows were found for this scanner+date. Check the universe sync status for the affected universe.
- **`no_live_events`**: The live nightly scan produced no events for this scanner type on this day. Replay runs but there is nothing to diff against; this is not a drift condition.
