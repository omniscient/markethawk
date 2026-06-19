# Missing Bars and Insufficient Lookback Gate Evidence — Design (issue #498)

**Date**: 2026-06-19  
**Issue**: [#498](https://github.com/omniscient/markethawk/issues/498) — Generate missing bars and insufficient lookback gate issues  
**Parent Epic**: [#491](https://github.com/omniscient/markethawk/issues/491) — Data Quality Trust Gate  
**Blocked by**: [#492](https://github.com/omniscient/markethawk/issues/492) — Add reusable data quality gate contract and service

## Problem

The data quality trust gate (epic #491) needs concrete evidence generators for two of its seven primary issue codes: `missing_bars` and `insufficient_lookback`. Without these generators:

- Scanners and backtests may silently operate on universes with gaps in required OHLCV coverage.
- Indicators that require N lookback bars (e.g. a 200-day moving average) run against fewer bars than needed without any warning or blocker.
- The gate contract defined in #492 has no evidence to evaluate — its verdicts remain empty.

The existing `DataQualityService.analyze_universe()` already computes `actual_bars`, `expected_bars`, and `coverage_pct` per ticker. `DataReadinessService.check()` already reads `ScannerConfig.data_requirements` timespans. This slice wires those two primitives into gate-issue emitters that produce typed payloads the #492 gate contract can evaluate.

## Requirements

From the acceptance criteria and Q&A:

1. A `generate_missing_bars_issues()` function emits gate issues with code `missing_bars` when a ticker's actual bar count falls below the expected count derived from `data_requirements.timespans[].lookback_days`.
2. A `generate_insufficient_lookback_issues()` function emits gate issues with code `insufficient_lookback` when a ticker's actual bar count falls below the `data_requirements.timespans[].min_bars` field.
3. Both functions accept `(db, universe_id, scanner_config, ticker=None)` — when `ticker` is passed, results are filtered to that ticker; when `None`, all tickers in the universe are evaluated.
4. Issue payloads include `observed` (actual bars available) and `required` (target count from config) on every emitted issue.
5. The `data_requirements` schema is standardized: each timespan entry must support `{"timespan": str, "multiplier": int, "lookback_days": int, "min_bars": int}`. The trend_pullback seed's flat `{"timespan": "day", "min_bars": 260}` outlier is migrated to the unified shape.
6. Strict mode emits `missing_bars` and `insufficient_lookback` issues as blockers; advisory mode emits them as warnings. The severity mapping lives in the #492 gate policy layer — #498 emits issues with the code and counts only; the caller (gate service) applies the policy.
7. Unit tests cover: per-ticker mode (ticker= filter), universe-wide mode (ticker=None), partial coverage (some tickers pass, some fail), no `min_bars` configured (no `insufficient_lookback` issue emitted), and missing/empty quality report (emits one issue for the whole universe).

## Architecture

### New module: `backend/app/services/quality_gate_evidence.py`

Two new static-method functions live here. Neither existing service owns both needed data sources: `DataQualityService` computes bar counts and `DataReadinessService` reads requirements — a third module that imports both keeps each service single-purpose.

```python
# backend/app/services/quality_gate_evidence.py

from dataclasses import dataclass, field
from typing import Optional
from sqlalchemy.orm import Session
from app.models.scanner_config import ScannerConfig
from app.models.universe_quality_report import UniverseQualityReport
from app.models.stock_aggregate import StockAggregate
from sqlalchemy import func


@dataclass
class GateIssue:
    """Minimal contract stub — replaced by the QualityGateAssessment from issue #492."""
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
    Returns [] when no timespans have min_bars configured.
    """
    ...
```

### Stub contract (`GateIssue`)

`GateIssue` is a minimal placeholder dataclass living in `quality_gate_evidence.py`. When #492 lands it defines the canonical `QualityIssue` shape; `quality_gate_evidence.py` will import that instead and the `GateIssue` alias is removed. The two fields `observed` and `required` are the concrete payloads #498's AC requires.

### Implementation detail: bar-count source

For efficiency, `generate_missing_bars_issues()` prefers the cached `UniverseQualityReport.report_data` (already stores per-ticker `actual_bars` / `expected_bars` per timespan combo) rather than re-running `DataQualityService.analyze_universe()`. If no report exists or is stale, it falls back to a direct `SELECT count(*) FROM stock_aggregates` query per ticker × timespan. `generate_insufficient_lookback_issues()` always queries `stock_aggregates` directly (count only) since `report_data` does not currently store the timespan-filtered bar count against `min_bars`.

### `data_requirements` schema — standardized form

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

### Migration: trend_pullback flat seed

The trend_pullback seed `f7e8d9c0b1a2_seed_trend_pullback_scanner_config.py` uses a non-standard flat shape `{"timespan": "day", "min_bars": 260}`. A new Alembic data migration (`UPDATE scanner_configs SET data_requirements = ... WHERE scanner_type = 'trend_pullback'`) converts it to the standardized `timespans[]` shape. The `DataReadinessService` already reads only the `timespans[]` form, so no other code changes are needed.

### Files changed

| File | Change |
|------|--------|
| `backend/app/services/quality_gate_evidence.py` | **New** — `generate_missing_bars_issues()`, `generate_insufficient_lookback_issues()`, `GateIssue` stub |
| `backend/alembic/versions/<hash>_normalize_data_requirements.py` | **New** — migrate trend_pullback flat seed to `timespans[]` form |
| `backend/tests/services/test_quality_gate_evidence.py` | **New** — unit tests (7 test functions minimum) |

## Alternatives Considered

### A. Extend `DataQualityService` with the two generators

Adding the generators as static methods on `DataQualityService` (in `data_quality.py`) would keep all quality logic in one place. Rejected because: (1) `data_quality.py` is already 547 lines and owns universe-level analysis, not gate-issue emission, which is a different responsibility; (2) the generators need to read `ScannerConfig.data_requirements`, which is not currently a `DataQualityService` concern — pulling it in would cross service-domain boundaries.

### B. Extend `DataReadinessService` with the two generators

`DataReadinessService` already reads `data_requirements`, so it's a plausible home for `generate_insufficient_lookback_issues()`. Rejected because: (1) `generate_missing_bars_issues()` needs the bar-count analysis that lives in `DataQualityService`; putting it in `DataReadinessService` forces an import from `DataQualityService`, while the reverse import is worse; (2) a new dedicated module cleanly represents the #492 integration boundary.

### C. Define the full gate contract in #498

If `GateIssue` were expanded to include verdict/policy in #498, it would duplicate what #492 is about to define. Rejected: #492 owns the seven issue codes and the strict/advisory policy types. #498 only emits the two codes with count payloads. The stub `GateIssue` is a thin placeholder, not a full contract.

## Open Questions (non-blocking)

1. Should `generate_missing_bars_issues()` emit one issue per ticker × timespan, or one aggregated issue per universe when the miss is universe-wide? Currently specced as per-ticker issues (the AC says "per-ticker and universe-wide" — universe-wide is the caller aggregating the per-ticker list). This could change when #492 defines how the gate aggregates issues.

2. Should the `observed` count in `missing_bars` be the raw `actual_bars`, or `coverage_pct × expected_bars`? Specced as `actual_bars` (raw integer) — simpler and more debuggable than a derived float.

## Assumptions

- **[A1]** `#492` will be implemented before `#498` reaches the implement stage. If not, the `GateIssue` stub in `quality_gate_evidence.py` is sufficient to make `#498` testable in isolation without forking policy logic.
- **[A2]** `UniverseQualityReport.report_data` is populated before the gate evidence generators are called. If it is absent, the generators fall back to direct DB queries — this fallback is heavier but correct.
- **[A3]** `data_requirements.timespans[].lookback_days` represents calendar days, not trading days. `expected_bars` is derived by multiplying `lookback_days × bars_per_day` for the given timespan/multiplier, using the same P90 logic already in `DataQualityService._estimate_expected_bars()`.
- **[A4]** The trend_pullback data migration is safe to run on an empty CI database (the seed row may not exist; `ON CONFLICT DO NOTHING` ensures idempotency).
- **[A5]** `FuturesAggregate` is out of scope for this slice; both generators operate on `StockAggregate` only. Futures support can be added in a follow-on.
