# Missing Bars and Insufficient Lookback Gate Evidence — Design (issue #498)

**Date**: 2026-06-19 (revised 2026-06-20)  
**Issue**: [#498](https://github.com/omniscient/markethawk/issues/498) — Generate missing bars and insufficient lookback gate issues  
**Parent Epic**: [#491](https://github.com/omniscient/markethawk/issues/491) — Data Quality Trust Gate  
**Blocked by**: [#492](https://github.com/omniscient/markethawk/issues/492) — Add reusable data quality gate contract and service

## Problem

The data quality trust gate (epic #491) needs concrete evidence generators for two of its seven primary issue codes: `missing_bars` and `insufficient_lookback`. Without these generators:

- Scanners and backtests may silently operate on universes with gaps in required OHLCV coverage.
- Indicators that require N lookback bars (e.g. a 200-day moving average) run against fewer bars than needed without any warning or blocker.
- The gate contract defined in #492 has no evidence to evaluate — its verdicts remain empty.

The existing `DataQualityService.analyze_universe()` already computes `actual_bars`, `expected_bars`, and `coverage_pct` per ticker. `DataReadinessService.check()` already reads `ScannerConfig.data_requirements` timespans. This slice wires those two primitives into gate-issue emitters that produce typed payloads the #492 gate contract can evaluate.

## Acceptance Criteria — Scope Split

This issue's acceptance criteria span two layers. The table below makes the ownership explicit:

| AC | Text | Owner |
|----|------|-------|
| 1 | Gate emits `missing_bars` when required OHLCV coverage is absent | **#498** |
| 2 | Gate emits `insufficient_lookback` when indicators need more bars than available | **#498** |
| 3 | Strict mode treats these issues as blockers | **#492** — the gate policy layer wires severity after #498's evidence is available |
| 4 | Advisory mode records them as warnings | **#492** — same as above |
| 5 | Issue payloads include observed and required counts | **#498** |
| 6 | Unit tests cover per-ticker and universe-wide cases | **#498** |

**#498 is complete and independently mergeable** once ACs 1, 2, 5, 6 are satisfied. ACs 3-4 are satisfied downstream when #492 consumes the `GateIssue` objects emitted here and applies the strict/advisory policy. This makes #498 testable in isolation before #492 lands, resolving the "aspirational spec language" concern raised by Epic Autopilot.

## Requirements

1. A `generate_missing_bars_issues()` function emits gate issues with code `missing_bars` when a ticker's actual bar count falls below the expected count derived from `data_requirements.timespans[].lookback_days`.
2. A `generate_insufficient_lookback_issues()` function emits gate issues with code `insufficient_lookback` when a ticker's actual bar count falls below the `data_requirements.timespans[].min_bars` field.
3. Both functions accept `(db, universe_id, scanner_config, ticker=None)` — when `ticker` is passed, results are filtered to that ticker; when `None`, all tickers in the universe are evaluated.
4. Issue payloads include `observed` (actual bars available) and `required` (target count from config) on every emitted issue.
5. Both generators read `data_requirements.get("timespans", [])` — configs with the flat shape (no `timespans` key) silently return `[]` (no issues), consistent with existing `DataReadinessService.check()` behavior.
6. Unit tests cover: per-ticker mode (`ticker=` filter), universe-wide mode (`ticker=None`), partial coverage (some tickers pass, some fail), no `min_bars` configured (no `insufficient_lookback` issue emitted), and missing/empty quality report (fallback to direct DB count query).

**Out of scope for #498**: The `data_requirements` schema migration converting the trend_pullback flat seed to `timespans[]` form is deferred to a follow-on ticket. The trend_pullback scanner is knowingly excluded from evidence coverage until that migration lands — this is a pre-existing gap, not a regression introduced by #498. See § Data Requirements Schema below.

## Architecture

### New module: `backend/app/services/quality_gate_evidence.py`

Two new functions live here. Neither existing service owns both needed data sources: `DataQualityService` computes bar counts and `DataReadinessService` reads requirements — a third module that imports both keeps each service single-purpose.

```python
# backend/app/services/quality_gate_evidence.py

from dataclasses import dataclass
from typing import Optional
from sqlalchemy.orm import Session
from app.models.scanner_config import ScannerConfig


@dataclass
class GateIssue:
    """Stable payload shape consumed by the #492 gate policy layer.

    When #492 lands it defines the canonical QualityIssue shape;
    quality_gate_evidence.py will import that instead and the GateIssue
    alias is removed. The two count fields are the concrete deliverable
    ACs 1/2/5 require.
    """
    issue_code: str          # "missing_bars" | "insufficient_lookback"
    ticker: Optional[str]    # None = universe-wide
    timespan: str
    multiplier: int
    observed: int            # actual bars available
    required: int            # target from config


def generate_missing_bars_issues(
    db: Session,
    universe_id: int,
    scanner_config: ScannerConfig,
    ticker: Optional[str] = None,
) -> list[GateIssue]:
    """
    Emit GateIssue(issue_code='missing_bars') for each ticker × timespan where
    actual bar count is below the coverage expected from lookback_days.

    Reads ScannerConfig.data_requirements.timespans[].lookback_days and
    compares against the aggregate count from stock_aggregates.
    Falls back to the stored UniverseQualityReport.report_data when available
    to avoid re-querying all bars.
    Returns [] for any scanner_config whose data_requirements lacks a timespans[] key.
    """
    ...


def generate_insufficient_lookback_issues(
    db: Session,
    universe_id: int,
    scanner_config: ScannerConfig,
    ticker: Optional[str] = None,
) -> list[GateIssue]:
    """
    Emit GateIssue(issue_code='insufficient_lookback') for each ticker × timespan
    where actual bar count is below min_bars from data_requirements.

    Only emits issues for timespans that carry a min_bars field.
    Returns [] when no timespans have min_bars configured, or when
    data_requirements lacks a timespans[] key.
    """
    ...
```

### Stable interface between #498 and #492

`GateIssue` is the seam. The six fields (`issue_code`, `ticker`, `timespan`, `multiplier`, `observed`, `required`) are the stable contract #492 will consume. #498's unit tests verify this shape is populated correctly. When #492 lands it replaces the `GateIssue` stub import with its own `QualityIssue` type; if the field names align, the change is mechanical.

### Implementation detail: bar-count source

`generate_missing_bars_issues()` prefers the cached `UniverseQualityReport.report_data` (already stores per-ticker `actual_bars` / `expected_bars` per timespan combo) rather than re-running `DataQualityService.analyze_universe()`. If no report exists or is stale, it falls back to a direct `SELECT count(*) FROM stock_aggregates` query per ticker × timespan. `generate_insufficient_lookback_issues()` always queries `stock_aggregates` directly (count only) since `report_data` does not currently store the timespan-filtered bar count against `min_bars`.

### Data Requirements Schema

The `timespans[]` form is the only supported shape for evidence generation:

```json
{
  "timespans": [
    {
      "timespan": "minute",
      "multiplier": 1,
      "lookback_days": 10
    },
    {
      "timespan": "day",
      "multiplier": 1,
      "lookback_days": 90,
      "min_bars": 260
    }
  ]
}
```

`min_bars` is optional per entry; its absence silently suppresses `insufficient_lookback` for that timespan.

**Flat shape handling**: The trend_pullback scanner currently stores `{"timespan": "day", "min_bars": 260}` (no `timespans` key). `DataReadinessService.check()` already handles this by calling `.get("timespans", [])` which returns `[]` — the flat shape is silently ignored. Both evidence generators use the same `.get("timespans", [])` pattern, so trend_pullback silently emits no issues. This is a pre-existing gap in coverage, not a regression. Converting the flat seed to `timespans[]` form is deferred to a separate ticket.

### Files changed

| File | Change |
|------|--------|
| `backend/app/services/quality_gate_evidence.py` | **New** — `generate_missing_bars_issues()`, `generate_insufficient_lookback_issues()`, `GateIssue` stub |
| `backend/tests/services/test_quality_gate_evidence.py` | **New** — unit tests (6 test functions minimum) |

No Alembic migration is required. The data_requirements schema is read-only from the perspective of #498; no column or seed changes are needed.

## Alternatives Considered

### A. Extend `DataQualityService` with the two generators

Adding the generators as static methods on `DataQualityService` (in `data_quality.py`) would keep all quality logic in one place. Rejected because: (1) `data_quality.py` is already 547 lines and owns universe-level analysis, not gate-issue emission, which is a different responsibility; (2) the generators need to read `ScannerConfig.data_requirements`, which is not currently a `DataQualityService` concern — pulling it in would cross service-domain boundaries.

### B. Extend `DataReadinessService` with the two generators

`DataReadinessService` already reads `data_requirements`, so it's a plausible home for `generate_insufficient_lookback_issues()`. Rejected because: (1) `generate_missing_bars_issues()` needs the bar-count analysis that lives in `DataQualityService`; putting it in `DataReadinessService` forces an import from `DataQualityService`, while the reverse import is worse; (2) a new dedicated module cleanly represents the #492 integration boundary.

### C. Include the data_requirements migration in #498

The previous spec revision included an Alembic migration converting the trend_pullback flat seed to `timespans[]` form. Removed in this revision because: (1) the flat shape is already silently ignored by all existing readers via `.get("timespans", [])`, so no existing behavior changes without the migration; (2) Epic Autopilot flagged it as "less-reversible" and outside the core evidence-generator scope; (3) trend_pullback migration involves a cross-module contract change that the #492 gate contract layer is better positioned to own. Deferred to a follow-on ticket.

### D. Define the full gate contract in #498

If `GateIssue` were expanded to include verdict/policy in #498, it would duplicate what #492 is about to define. Rejected: #492 owns the seven issue codes and the strict/advisory policy types. #498 only emits the two codes with count payloads. The stub `GateIssue` is a thin placeholder, not a full contract.

## Open Questions (non-blocking)

1. Should `generate_missing_bars_issues()` emit one issue per ticker × timespan, or one aggregated issue per universe when the miss is universe-wide? Currently specced as per-ticker issues (the AC says "per-ticker and universe-wide" — universe-wide is the caller aggregating the per-ticker list). This could change when #492 defines how the gate aggregates issues.

2. Should the `observed` count in `missing_bars` be the raw `actual_bars`, or `coverage_pct × expected_bars`? Specced as `actual_bars` (raw integer) — simpler and more debuggable than a derived float.

## Assumptions

- **[A1]** `#492` is a hard prerequisite for the strict/advisory gate policy (ACs 3-4), but NOT for the evidence generators (ACs 1, 2, 5, 6). #498 can be implemented and merged before #492; the `GateIssue` stub is the stable seam until #492 lands.
- **[A2]** `UniverseQualityReport.report_data` is populated before the gate evidence generators are called. If it is absent, the generators fall back to direct DB queries — this fallback is heavier but correct.
- **[A3]** `data_requirements.timespans[].lookback_days` represents calendar days, not trading days. `expected_bars` is derived by multiplying `lookback_days × bars_per_day` for the given timespan/multiplier, using the same P90 logic already in `DataQualityService._estimate_expected_bars()`.
- **[A4]** `FuturesAggregate` is out of scope for this slice; both generators operate on `StockAggregate` only. Futures support can be added in a follow-on.
- **[A5]** trend_pullback scanner configs are knowingly excluded from evidence coverage until a separate migration normalizes their `data_requirements` to `timespans[]` form. This is a pre-existing gap, not a #498 regression.
