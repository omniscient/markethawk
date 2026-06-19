# Data Quality Gate Contract and Service — Design (issue #492)

**Date**: 2026-06-19
**Issue**: [#492](https://github.com/omniscient/markethawk/issues/492) — Add reusable data quality gate contract and service
**Epic**: [#491](https://github.com/omniscient/markethawk/issues/491) — Data Quality Trust Gate

## Problem

Multiple MarketHawk subsystems (scanner runs, auto-trading, Scorecard, UI, backtesting) need to reason about data quality before treating results as trusted. Today each path either skips this check entirely or parses `UniverseQualityReport.report_data` directly — a fragile, non-reusable pattern. The gate contract provides a single, versioned verdict (`quality_gate.v1`) that all consumers can call without duplicating report-parsing logic.

## Requirements

Distilled from the issue acceptance criteria and Q&A:

1. A `QualityGateAssessment` Pydantic model exists in `backend/app/schemas/quality_gate.py` with fields: `schema_version`, `policy`, `verdict`, `trusted`, `scope`, `score`, `grade`, `issues`, `warnings`, `generated_at`.
2. Schema version is pinned to `Literal["quality_gate.v1"]`.
3. Policy enum (`strict` / `advisory` / `off`); verdict enum (`trusted` / `warning` / `blocked` / `skipped`).
4. All seven primary issue codes exist as `QualityIssueCode(str, Enum)`; three are emittable in this slice, four are deferred to later sub-issues.
5. Missing or incomplete `UniverseQualityReport` → `blocked` under `strict`, `warning` under `advisory`.
6. `QualityGateService` in `backend/app/services/quality_gate_service.py` provides:
   - a pure `_build_assessment(report_data, data_requirements, scope, policy)` with no DB dependency
   - a DB-aware wrapper `assess(db, universe_id, policy, scope=None)` that fetches the report and optionally reads scanner data requirements
7. `score` and `grade` pass through from `report_data["overall_score"]` / `report_data["overall_grade"]`; the gate adds issues/warnings/verdict on top.
8. Unit tests use `_build_assessment` directly with plain dicts — no DB mock required.

## Architecture

### New files

```
backend/app/schemas/quality_gate.py     ← Pydantic contract
backend/app/services/quality_gate_service.py  ← gate logic
backend/tests/services/test_quality_gate_service.py  ← unit tests
```

### Schema (`backend/app/schemas/quality_gate.py`)

```python
from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, ConfigDict


class QualityIssueCode(str, Enum):
    missing_bars          = "missing_bars"
    split_dividend_anomaly = "split_dividend_anomaly"  # deferred (#9)
    stale_quote           = "stale_quote"              # deferred (#8)
    provider_gap          = "provider_gap"
    session_mismatch      = "session_mismatch"         # deferred (#9)
    survivorship_bias     = "survivorship_bias"        # deferred (#10)
    insufficient_lookback = "insufficient_lookback"


class QualityGatePolicy(str, Enum):
    strict   = "strict"
    advisory = "advisory"
    off      = "off"


class QualityGateVerdict(str, Enum):
    trusted  = "trusted"
    warning  = "warning"
    blocked  = "blocked"
    skipped  = "skipped"


class QualityGateScope(BaseModel):
    model_config = ConfigDict(extra="forbid")
    universe_id:  Optional[int] = None
    ticker:       Optional[str] = None
    scanner_type: Optional[str] = None
    timespan:     Optional[str] = None


class QualityGateIssue(BaseModel):
    model_config = ConfigDict(extra="forbid")
    code:     QualityIssueCode
    severity: Literal["blocker", "warning"]
    message:  str
    detail:   Dict[str, Any] = {}


class QualityGateAssessment(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schema_version: Literal["quality_gate.v1"] = "quality_gate.v1"
    policy:         QualityGatePolicy
    verdict:        QualityGateVerdict
    trusted:        bool
    scope:          QualityGateScope
    score:          Optional[float] = None   # passthrough from overall_score
    grade:          Optional[str]   = None   # passthrough from overall_grade
    issues:         List[QualityGateIssue] = []
    warnings:       List[QualityGateIssue] = []  # severity=="warning" subset; convenience alias
    generated_at:   datetime
```

`trusted = (verdict == QualityGateVerdict.trusted)` — computed by the service, stored redundantly for consumers that need a quick boolean.
`warnings` mirrors the `issues` list filtered to `severity=="warning"` for convenience; the canonical source is `issues`.

### Service (`backend/app/services/quality_gate_service.py`)

#### Pure builder (no DB)

```python
def _build_assessment(
    report_data: dict | None,
    data_requirements: dict | None,
    scope: QualityGateScope,
    policy: QualityGatePolicy,
) -> QualityGateAssessment:
```

**Policy = off**: return `verdict=skipped, trusted=False, issues=[], score/grade=None`.

**Missing or non-complete report** (`report_data is None`):
- `strict` → `verdict=blocked`, one issue: `missing_bars` (blocker), message: "No completed quality report found".
- `advisory` → `verdict=warning`, one issue: `missing_bars` (warning), same message.
- `score=None, grade=None`.

**Report present**: passthrough `score = report_data["overall_score"]`, `grade = report_data["overall_grade"]`.

Issue emission logic for the three derivable codes:

| Code | blocker threshold | warning threshold | source field(s) |
|---|---|---|---|
| `missing_bars` | `coverage_pct < 70` | `70 ≤ coverage_pct < 85` | `report_data["overall_score"]`, worst-ticker `coverage_pct` |
| `insufficient_lookback` | readiness `is_ready == False` | (none — binary) | `data_requirements` timespans vs. `report_data` ticker coverage |
| `provider_gap` | `continuity_score < 70` (>6 gaps) | `gap_count ≥ 1` | `report_data["tickers"][].gap_count`, `continuity_score` |

`insufficient_lookback` is evaluated when `data_requirements` is provided. The builder computes the minimum `first_bar` across all tickers in `report_data["tickers"]` and checks it against `lookback_days` for each required timespan. If no `data_requirements` is passed, the code is skipped.

**Verdict derivation** (after collecting issues):
- Any `severity == "blocker"` → `blocked` under `strict`; `warning` under `advisory`.
- Only `severity == "warning"` issues → `warning` under both strict and advisory.
- No issues → `trusted`.

`trusted = (verdict == QualityGateVerdict.trusted)`.

#### DB wrapper

```python
class QualityGateService:
    @staticmethod
    def assess(
        db: Session,
        universe_id: int,
        policy: QualityGatePolicy,
        scope: QualityGateScope | None = None,
    ) -> QualityGateAssessment:
        from app.models.universe_quality_report import UniverseQualityReport
        from app.models.scanner_config import ScannerConfig

        scope = scope or QualityGateScope(universe_id=universe_id)

        report = (
            db.query(UniverseQualityReport)
            .filter(UniverseQualityReport.universe_id == universe_id)
            .first()
        )
        report_data = (
            report.report_data
            if report and report.status == "complete"
            else None
        )

        data_requirements = None
        if scope.scanner_type:
            config = (
                db.query(ScannerConfig)
                .filter(ScannerConfig.scanner_type == scope.scanner_type)
                .first()
            )
            if config:
                data_requirements = config.data_requirements

        return _build_assessment(report_data, data_requirements, scope, policy)
```

### Unit tests (`backend/tests/services/test_quality_gate_service.py`)

Tests call `_build_assessment` directly with plain `dict | None` — no `Session` or DB fixture needed.

Required test scenarios (acceptance criteria):

1. **Policy=off** → verdict `skipped`, trusted `False`, issues `[]` regardless of report content.
2. **Missing report + strict** → verdict `blocked`, issues contains `missing_bars` blocker.
3. **Missing report + advisory** → verdict `warning`, issues contains `missing_bars` warning.
4. **Report with coverage_pct < 70** → `missing_bars` blocker present → `blocked` (strict), `warning` (advisory).
5. **Report with 70 ≤ coverage_pct < 85** → `missing_bars` warning present → verdict `warning`.
6. **Report with coverage_pct ≥ 85 and no gaps** → no issues → verdict `trusted`, `trusted=True`.
7. **Report with gap_count ≥ 1** → `provider_gap` warning → verdict `warning`.
8. **Report with continuity_score < 70** → `provider_gap` blocker → `blocked` (strict).
9. **data_requirements provided with lookback not satisfied** → `insufficient_lookback` blocker.
10. **Assessment shape** → `schema_version == "quality_gate.v1"`, all required fields present, `trusted == (verdict == "trusted")`.

## Alternatives considered

### A: Extend `data_quality.py` in-place

Add gate logic to the existing `DataQualityService`. Rejected: `data_quality.py` is already 547 lines and single-responsibility (produce report_data). Adding consumer logic inverts the dependency direction (gate imports from data_quality; not vice versa). Keeping them separate matches the existing `data_readiness.py` split.

### B: Dataclass instead of Pydantic

Use `@dataclass` consistent with `ReadinessReport` / `TimespanCoverage` in `data_readiness.py`. Rejected: `QualityGateAssessment` is a versioned, machine-readable contract (`schema_version`, stable enum codes) that future sub-issues (preflight API #493, UI display #495, backtesting #502) will serialize over HTTP. Pydantic provides schema validation, `ConfigDict(extra="forbid")` for drift detection, and is the existing API-schema convention throughout `backend/app/schemas/`.

### C: DB-coupled assess() only (no pure builder)

Expose only `QualityGateService.assess(db, universe_id, ...)` with all logic inline. Rejected: unit tests would require DB mocks, making them slower and more fragile. The pure `_build_assessment` function is the correct unit-testable core; the DB wrapper is thin I/O only. This split is critical for the acceptance criterion "unit tests cover policy behavior, missing report behavior, issue severity behavior."

## Deferred codes

These four `QualityIssueCode` enum members are defined now (for API stability) but never emitted in this slice:

| Code | Deferred to | Reason |
|---|---|---|
| `stale_quote` | #8 — Stale quote and provider evidence | No quote-freshness timestamps in `report_data` |
| `split_dividend_anomaly` | #9 — Split/dividend and session evidence | `integrity_pct` only checks OHLC sanity, not corporate-action detection |
| `session_mismatch` | #9 — Split/dividend and session evidence | No session-classification evidence captured |
| `survivorship_bias` | #10 — Survivorship-bias policy | Requires delisted-ticker / universe-membership history not in report |

## Open questions (non-blocking)

- **`warnings` field redundancy**: The spec includes both `issues` (all) and `warnings` (warning-severity subset) for consumer convenience. If this feels redundant, drop `warnings` and let consumers filter `issues` by severity. Either is consistent.
- **`missing_bars` worst-ticker vs. universe average**: The spec currently gates on `report_data["overall_score"]` for the coverage threshold. An alternative is to gate on the *worst* ticker's `coverage_pct`, which is stricter. Deferred — either works for the initial slice.
- **Advisory verdict with blocker**: Under `advisory` policy, a blocker issue still produces `verdict=warning` (not `blocked`). This is intentional — "advisory" means "warn but don't stop." Confirm this is correct before the preflight API sub-issue (#493) is implemented.

## Assumptions

- [ASSUMPTION] The `data_requirements` structure from `ScannerConfig.data_requirements["timespans"]` remains stable (each entry has `timespan`, `multiplier`, `lookback_days`) — this format is used by `DataReadinessService` today.
- [ASSUMPTION] `UniverseQualityReport.status == "complete"` is the correct sentinel for a usable report. Reports in `pending`, `running`, or `error` state are treated as absent.
- [ASSUMPTION] The `warnings` field in `QualityGateAssessment` is a convenience alias for `issues` filtered to `severity=="warning"`. The canonical list for all issues (both blockers and warnings) is `issues`.
- [ASSUMPTION] `trusted=False` when `verdict="skipped"` (policy=off). The gate being disabled does not make the data trusted — the caller is simply opting out of enforcement.
