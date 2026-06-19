# Advisory Data Quality Gate for Scanner Runs — Design

**Date:** 2026-06-19
**Status:** Pending review
**Issue:** [#494](https://github.com/omniscient/markethawk/issues/494) — Apply advisory data quality gate to scanner runs
**Parent epic:** [#491](https://github.com/omniscient/markethawk/issues/491) — Data Quality Trust Gate
**Depends on:** [#492](https://github.com/omniscient/markethawk/issues/492) — Gate contract and service (defines `QualityGateService` / `QualityGateAssessment`)

---

## Overview

Scanner runs currently write `ScannerEvent` rows with no indication of whether the underlying universe data was complete and reliable at scan time. `stats.py` already reads `metadata_["quality_gate"]["tier"]` to filter scorecard and signal views by trust level — but nothing ever writes that field. This spec wires the first end-to-end consumer of the trust gate: universe scanner runs call the gate before processing begins, the run-level verdict is stored on `ScannerRun`, and each new event is stamped with a lightweight gate record so downstream views can surface caveats.

The gate always runs in **advisory** mode for interactive scanner runs — warnings are recorded, but execution continues. Users can still see and act on signals; the caveat layer is informational.

---

## Requirements

From Q&A:

1. The gate is evaluated **once at scan start**, before the day-walk loop in `_run_universe_scan_logic`, using `policy="advisory"`.
2. `ScannerConfig.data_requirements` (if present for the scanner type) is passed to the gate to check lookback adequacy; if absent, the gate returns a `trusted`/`skipped` verdict.
3. The full `QualityGateAssessment` is persisted in a new **nullable JSONB column `quality_gate`** on the `scanner_runs` table (Alembic migration required).
4. A minimal gate metadata dict `{"tier": ..., "warnings": [...], "schema_version": "v1"}` is threaded to `save_event()` via a new optional `gate_metadata` parameter.
5. Each new `ScannerEvent` produced by the run stores that dict in `metadata_["quality_gate"]`.
6. Advisory mode: verdict `warning` never prevents the scan from running or events from being saved.
7. No quality report for the universe (no row, or `status != "complete"`) → verdict `warning` with warning message `"No completed quality report found"`.
8. Scope is limited to **`run_universe_scan`** (the interactive Celery task) only. Nightly scheduled scans (`run_liquidity_hunt_scheduled`, `run_pocket_pivot_scheduled`, `run_trend_pullback_scheduled`) and the live scanner are out of scope.
9. Tests prove that scans complete and events are saved when the gate returns `warning`.

---

## Architecture

### Gate contract assumed from #492

The `QualityGateService` from #492 exposes a single static method:

```python
from app.services.quality_gate import QualityGateService, QualityGateAssessment

assessment: QualityGateAssessment = QualityGateService.assess(
    db=db,
    universe_id=universe_id,
    scanner_type=scanner_type,
    policy="advisory",          # always advisory for #494
    data_requirements=data_requirements,  # dict or None
)
```

`QualityGateAssessment` is a dataclass (or TypedDict) with:
```python
@dataclass
class QualityGateAssessment:
    schema_version: str          # "v1"
    policy: str                  # "advisory"
    verdict: str                 # "trusted" | "warning" | "blocked" | "skipped"
    trusted: bool
    scope: str                   # "universe:{universe_id}"
    score: float | None
    grade: str | None
    issues: list[dict]           # [{code, severity, message}, ...]
    warnings: list[str]
    generated_at: str            # ISO 8601
```

The tier value stamped on events maps directly from `verdict`: `trusted` → `"trusted"`, `warning` → `"warning"` (note: `blocked` and `skipped` should not occur under advisory policy, but if they do they pass through as-is).

### Database change: `scanner_runs.quality_gate`

Add a nullable JSONB column to `scanner_runs`:

```python
quality_gate = Column(JSONB, nullable=True)
```

Alembic migration: `ADD COLUMN quality_gate JSONB NULL` on `scanner_runs`. Existing rows stay NULL (legacy runs pre-gate).

### Call site: `_run_universe_scan_logic` in `tasks/scanning.py`

The gate is called immediately after the universe's `ScannerConfig` is resolved and before `scanner_run.status` is set to `"running"`. Pseudocode:

```python
# Resolve ScannerConfig for this scanner_type/universe
config = (
    db.query(ScannerConfig)
    .filter(
        ScannerConfig.scanner_type == scanner_type,
        ScannerConfig.universe_id == universe_id,
        ScannerConfig.is_active == True,
    )
    .first()
)
data_requirements = config.data_requirements if config else None

# Evaluate gate (advisory — never blocks)
try:
    from app.services.quality_gate import QualityGateService
    assessment = QualityGateService.assess(
        db=db,
        universe_id=universe_id,
        scanner_type=scanner_type,
        policy="advisory",
        data_requirements=data_requirements,
    )
    gate_metadata = {
        "tier": assessment.verdict,
        "warnings": assessment.warnings,
        "schema_version": assessment.schema_version,
    }
    gate_dict = dataclasses.asdict(assessment)
except Exception as exc:
    logger.warning("quality_gate assess failed for universe=%s: %s", universe_id, exc)
    gate_metadata = None
    gate_dict = None

# Persist on run
scanner_run.quality_gate = gate_dict
db.commit()
```

The `gate_metadata` dict (or `None` on error) is then passed into every `save_event()` call during this run.

### Event-level stamping: `save_event()` in `alert_service.py`

Add an optional `gate_metadata: dict | None = None` parameter to `save_event()`, mirroring the existing `ranker_config` optional param:

```python
def save_event(
    db, ticker, event_date, scanner_type,
    indicators, criteria_met, enrichment,
    previous_close=None, opening_price=None, closing_price=None,
    ranker_config=None,
    gate_metadata=None,          # ← new optional param
) -> dict:
```

When `gate_metadata` is not None, merge it into the enrichment dict under the `"quality_gate"` key before persisting:

```python
if gate_metadata is not None:
    enrichment = {**enrichment, "quality_gate": gate_metadata}
```

This ensures `metadata_["quality_gate"]["tier"]` is populated for every new event in the run, which is exactly what `stats.py` line 17 reads.

**Existing events** (upsert path — `if existing:`) are **not updated** with the new gate stamp — the quality gate represents the data state at the time of original detection, not a retroactive re-stamp. The upsert code already updates all fields from `event_dict`; to avoid overwriting a previously-stamped gate, the update should skip the `"quality_gate"` key inside `metadata_` rather than wholesale replacing `metadata_`.

Concretely, in the `if existing:` update block:
```python
if "metadata" in event_dict and gate_metadata is not None:
    # Don't overwrite a previously-stamped quality_gate on the existing event
    merged_meta = dict(existing.metadata_ or {})
    new_meta = dict(event_dict.get("metadata", {}))
    new_meta.pop("quality_gate", None)   # strip gate from the update payload
    merged_meta.update(new_meta)
    event_dict["metadata"] = merged_meta
```

### Threading `gate_metadata` through scan call sites

All paths that call `save_event()` inside `run_universe_scan` must pass `gate_metadata` through. The primary call chain is:

1. `_run_universe_scan_logic` → calls `scan_orchestrator.run(scanner_type, tickers, db, event_date, scanner_run)`
2. `scan_orchestrator.run()` → calls the registered `descriptor.run(...)` for each scanner
3. Each scanner (e.g., `pre_market_scan.py`, `oversold_bounce_scan.py`) calls `save_event()`

The cleanest threading approach is to add `gate_metadata` as an optional keyword argument to `scan_orchestrator.run()` and propagate it through to each registered scanner's run function. The registered scanners already receive `scanner_run` as a kwarg; add `gate_metadata` alongside it.

This requires updating:
- `scan_orchestrator.run()` signature: add `gate_metadata=None`
- Each registered scanner's async run function signature: add `gate_metadata=None`
- Each scanner's internal `save_event()` call: pass `gate_metadata=gate_metadata`

Five scanners self-register in the orchestrator (all callable from `run_universe_scan`): `pre_market_scan.py`, `oversold_bounce_scan.py`, `pocket_pivot.py`, `trend_pullback_scan.py`, `liquidity_hunt.py`. All five need the threading.

The live scanner (separate container, `live_scanner/conditions.py`) is unaffected — it writes events directly without going through the orchestrator. Its events will have no `metadata_["quality_gate"]` key (NULL-tier, treated as trusted by stats.py's existing filter).

---

## File changes summary

| File | Change |
|------|--------|
| `backend/app/models/scanner_run.py` | Add `quality_gate = Column(JSONB, nullable=True)` |
| `backend/app/alembic/versions/<new>.py` | `ADD COLUMN quality_gate JSONB NULL` on `scanner_runs` |
| `backend/app/tasks/scanning.py` | Evaluate gate in `_run_universe_scan_logic`; persist on run; thread `gate_metadata` |
| `backend/app/services/scan_orchestrator.py` | Add `gate_metadata=None` to `run()` signature, thread it |
| `backend/app/services/pre_market_scan.py` | Accept `gate_metadata=None`, pass to `save_event()` |
| `backend/app/services/oversold_bounce_scan.py` | Accept `gate_metadata=None`, pass to `save_event()` |
| `backend/app/services/pocket_pivot.py` | Accept `gate_metadata=None`, pass to `save_event()` |
| `backend/app/services/trend_pullback_scan.py` | Accept `gate_metadata=None`, pass to `save_event()` |
| `backend/app/services/liquidity_hunt.py` | Accept `gate_metadata=None`, pass to `save_event()` |
| `backend/app/services/alert_service.py` | Add `gate_metadata=None` to `save_event()`; merge into enrichment; guard upsert path |
| `backend/tests/tasks/test_scanning.py` | Tests: gate called, warning result continues scan, events stamped |

---

## Alternatives considered

### A. Gate in `enqueue_scan` (at dispatch time)

Call the gate in `scan_orchestrator.enqueue_scan()` when `ScannerRun` is first created. Pro: the gate result is available before the task even starts, enabling fast pre-flight feedback at the API level. Con: `enqueue_scan` is a thin dispatch function; adding DB-heavy quality analysis there mixes concerns. Also, the gate can only produce a meaningful assessment after the universe's data has been fetched and the quality report is current — not guaranteed at enqueue time. The issue's "before treating run output as clean" phrasing implies the gate runs alongside the scan, not before the task is even queued.

### B. Gate re-evaluated per event in `save_event()`

Call `QualityGateService.assess()` on every `save_event()` call. Rejected because (a) `save_event()` has no universe context and adding it would change its signature significantly, (b) the assessment is the same for every event in the run (it evaluates universe-level data quality, not per-ticker), so repeating it N times per scan is wasteful, and (c) the acceptance criteria describe a run-level gate that events derive from — not an event-by-event evaluation.

---

## Open questions

1. **`scan_orchestrator.run()` currently uses `**kwargs` to pass `scanner_run` to registered scanners.** If some registered scanners don't accept `gate_metadata`, they'll raise `TypeError`. Confirm that all scanners registered in the orchestrator have `**kwargs` or explicit `gate_metadata` handling. (Non-blocking — fixable at implementation time by verifying each descriptor's `run` callable.)

2. **Upsert behavior for existing events on date-range re-scans.** When a re-scan covers a date range where events already exist, the spec says not to overwrite `metadata_["quality_gate"]`. This is a conservative choice. If the team prefers re-stamping existing events with the current run's gate verdict, remove the guard in the upsert path.

---

## Assumptions

- `QualityGateService.assess()` exists after #492 merges, with the signature described above. If #492 uses a different API shape, this spec's call site must be updated.
- The gate call in `_run_universe_scan_logic` is inside a `try/except` so gate service errors degrade gracefully (`gate_metadata = None`) without blocking the scan — matching the advisory requirement.
- `DataReadinessService` (per-ticker, per-outcome check) is separate from `QualityGateService` (per-universe, per-scan check). They coexist without conflict.
- Nightly scheduled scans and the live scanner are out of scope; their events will have `metadata_["quality_gate"]` absent (NULL tier), treated as trusted by `stats.py`'s existing `_GATE_TIER IS NULL` filter.
