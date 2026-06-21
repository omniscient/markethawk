# Implementation Plan: Data Quality Gate Contract and Service
## Issue #492 — Add reusable data quality gate contract and service

**Date**: 2026-06-21
**Spec**: [docs/superpowers/specs/2026-06-19-data-quality-gate-contract-design.md](../specs/2026-06-19-data-quality-gate-contract-design.md)
**Branch**: `refine/issue-492-add-reusable-data-quality-gate-contract-`

---

## Goal

Add the `quality_gate.v1` Pydantic contract and backend service that converts existing
`UniverseQualityReport.report_data` (plus optional `ScannerConfig.data_requirements`) into a
versioned, machine-readable verdict. All consumers (scanner, auto-trading, Scorecard, UI,
backtesting) call this gate rather than parsing `report_data` directly.

---

## Architecture

Three new files only — no model or migration changes, no new containers:

| File | Role |
|---|---|
| `backend/app/schemas/quality_gate.py` | Pydantic contract (`QualityGateAssessment` and supporting types) |
| `backend/app/services/quality_gate_service.py` | Pure builder `_build_assessment` + thin DB wrapper `QualityGateService.assess()` |
| `backend/tests/services/test_quality_gate_service.py` | 15 unit tests — 12 against pure builder, 3 wrapper smoke tests |

`backend/app/schemas/__init__.py` gets one new export block.

---

## Tech Stack

FastAPI + SQLAlchemy 2.0 (sync) + Pydantic v2 + pytest

---

## File Structure

```
backend/
  app/
    schemas/
      __init__.py              (modified — new exports)
      quality_gate.py          (new)
    services/
      quality_gate_service.py  (new)
  tests/
    services/
      test_quality_gate_service.py  (new)
```

---

## Tasks

### Task 1 — Quality Gate Schema

**Files**: `backend/app/schemas/quality_gate.py`, `backend/app/schemas/__init__.py`

#### 1a. Write a failing import test

Create `backend/tests/services/test_quality_gate_service.py` with a shape test that will fail
until the schema file exists:

```python
"""
Unit tests for quality_gate_service._build_assessment.
No DB fixture required — all tests use plain dict inputs.
"""

from datetime import date, timedelta

from app.schemas.quality_gate import (
    QualityGatePolicy,
    QualityGateScope,
    QualityGateVerdict,
    QualityIssueCode,
)
from app.services.quality_gate_service import _build_assessment


def _scope() -> QualityGateScope:
    return QualityGateScope(universe_id=1)


def _report(overall_score=90.0, overall_grade="A", tickers=None):
    if tickers is None:
        tickers = [
            {
                "ticker": "AAPL",
                "gap_count": 0,
                "continuity_score": 100.0,
                "first_bar": "2025-01-01T00:00:00",
                "last_bar": "2026-06-19T00:00:00",
                "coverage_pct": overall_score,
            }
        ]
    return {
        "overall_score": overall_score,
        "overall_grade": overall_grade,
        "tickers": tickers,
    }


def _data_requirements(lookback_days: int = 30) -> dict:
    return {
        "timespans": [
            {"timespan": "minute", "multiplier": 5, "lookback_days": lookback_days}
        ]
    }


def test_assessment_shape():
    result = _build_assessment(_report(), None, _scope(), QualityGatePolicy.strict)
    assert result.schema_version == "quality_gate.v1"
    assert result.policy is not None
    assert result.verdict is not None
    assert isinstance(result.trusted, bool)
    assert result.scope is not None
    assert result.generated_at is not None
    assert result.trusted == (result.verdict == QualityGateVerdict.trusted)
```

#### 1b. Verify the test fails

```bash
docker-compose exec backend python -m pytest backend/tests/services/test_quality_gate_service.py::test_assessment_shape -x 2>&1 | tail -10
```

Expected: `ModuleNotFoundError: No module named 'app.schemas.quality_gate'`

#### 1c. Create the schema file

Create `backend/app/schemas/quality_gate.py`:

```python
from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, ConfigDict


class QualityIssueCode(str, Enum):
    missing_bars = "missing_bars"
    split_dividend_anomaly = "split_dividend_anomaly"  # deferred (#9)
    stale_quote = "stale_quote"                        # deferred (#8)
    provider_gap = "provider_gap"
    session_mismatch = "session_mismatch"              # deferred (#9)
    survivorship_bias = "survivorship_bias"            # deferred (#10)
    insufficient_lookback = "insufficient_lookback"


class QualityGatePolicy(str, Enum):
    strict = "strict"
    advisory = "advisory"
    off = "off"


class QualityGateVerdict(str, Enum):
    trusted = "trusted"
    warning = "warning"
    blocked = "blocked"
    skipped = "skipped"


class QualityGateScope(BaseModel):
    model_config = ConfigDict(extra="forbid")
    universe_id: Optional[int] = None
    ticker: Optional[str] = None
    scanner_type: Optional[str] = None
    timespan: Optional[str] = None


class QualityGateIssue(BaseModel):
    model_config = ConfigDict(extra="forbid")
    code: QualityIssueCode
    severity: Literal["blocker", "warning"]
    message: str
    detail: Dict[str, Any] = {}


class QualityGateAssessment(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schema_version: Literal["quality_gate.v1"] = "quality_gate.v1"
    policy: QualityGatePolicy
    verdict: QualityGateVerdict
    trusted: bool
    scope: QualityGateScope
    score: Optional[float] = None
    grade: Optional[str] = None
    issues: List[QualityGateIssue] = []
    warnings: List[QualityGateIssue] = []
    generated_at: datetime
```

#### 1d. Export from `backend/app/schemas/__init__.py`

Add the following block after the existing imports, before `__all__`:

```python
from app.schemas.quality_gate import (
    QualityGateAssessment,
    QualityGateIssue,
    QualityGatePolicy,
    QualityGateScope,
    QualityGateVerdict,
    QualityIssueCode,
)
```

Add to the `__all__` list:
```python
    "QualityGateAssessment",
    "QualityGateIssue",
    "QualityGatePolicy",
    "QualityGateScope",
    "QualityGateVerdict",
    "QualityIssueCode",
```

#### 1e. Verify the shape test still fails (for the right reason)

```bash
docker-compose exec backend python -m pytest backend/tests/services/test_quality_gate_service.py::test_assessment_shape -x 2>&1 | tail -15
```

Expected: `FAILED` — still fails because `app.services.quality_gate_service` does not exist yet.

#### 1f. Commit

```bash
git add backend/app/schemas/quality_gate.py backend/app/schemas/__init__.py backend/tests/services/test_quality_gate_service.py
git commit -m "feat(schemas): QualityGateAssessment contract — quality_gate.v1 (#492)"
```

---

### Task 2 — Pure Builder `_build_assessment`

**Files**: `backend/app/services/quality_gate_service.py`, `backend/tests/services/test_quality_gate_service.py`

#### 2a. Add all 12 behavioral unit tests

Replace the test file contents with the full 12-scenario suite (10 required spec scenarios + 2 advisory variants):

```python
"""
Unit tests for quality_gate_service._build_assessment.
No DB fixture required — all tests use plain dict inputs.
"""

from datetime import date, timedelta

from app.schemas.quality_gate import (
    QualityGatePolicy,
    QualityGateScope,
    QualityGateVerdict,
    QualityIssueCode,
)
from app.services.quality_gate_service import _build_assessment


def _scope() -> QualityGateScope:
    return QualityGateScope(universe_id=1)


def _report(overall_score=90.0, overall_grade="A", tickers=None):
    if tickers is None:
        tickers = [
            {
                "ticker": "AAPL",
                "gap_count": 0,
                "continuity_score": 100.0,
                "first_bar": "2025-01-01T00:00:00",
                "last_bar": "2026-06-19T00:00:00",
                "coverage_pct": overall_score,
            }
        ]
    return {
        "overall_score": overall_score,
        "overall_grade": overall_grade,
        "tickers": tickers,
    }


def _data_requirements(lookback_days: int = 30) -> dict:
    return {
        "timespans": [
            {"timespan": "minute", "multiplier": 5, "lookback_days": lookback_days}
        ]
    }


# ── Test 1: policy=off ────────────────────────────────────────────────────────


def test_policy_off_returns_skipped():
    result = _build_assessment(None, None, _scope(), QualityGatePolicy.off)
    assert result.verdict == QualityGateVerdict.skipped
    assert result.trusted is False
    assert result.issues == []
    assert result.score is None
    assert result.grade is None


def test_policy_off_ignores_report_content():
    result = _build_assessment(_report(), None, _scope(), QualityGatePolicy.off)
    assert result.verdict == QualityGateVerdict.skipped
    assert result.issues == []


# ── Test 2: missing report + strict ──────────────────────────────────────────


def test_missing_report_strict_is_blocked():
    result = _build_assessment(None, None, _scope(), QualityGatePolicy.strict)
    assert result.verdict == QualityGateVerdict.blocked
    blocker_codes = [i.code for i in result.issues if i.severity == "blocker"]
    assert QualityIssueCode.missing_bars in blocker_codes


# ── Test 3: missing report + advisory ────────────────────────────────────────


def test_missing_report_advisory_is_warning():
    result = _build_assessment(None, None, _scope(), QualityGatePolicy.advisory)
    assert result.verdict == QualityGateVerdict.warning
    assert any(
        i.code == QualityIssueCode.missing_bars and i.severity == "warning"
        for i in result.issues
    )


# ── Test 4: coverage_pct < 70 ────────────────────────────────────────────────


def test_coverage_below_70_strict_is_blocked():
    result = _build_assessment(
        _report(overall_score=60.0), None, _scope(), QualityGatePolicy.strict
    )
    assert result.verdict == QualityGateVerdict.blocked
    assert any(
        i.code == QualityIssueCode.missing_bars and i.severity == "blocker"
        for i in result.issues
    )


def test_coverage_below_70_advisory_is_warning():
    result = _build_assessment(
        _report(overall_score=60.0), None, _scope(), QualityGatePolicy.advisory
    )
    assert result.verdict == QualityGateVerdict.warning
    assert any(i.code == QualityIssueCode.missing_bars for i in result.issues)


# ── Test 5: 70 ≤ coverage_pct < 85 ───────────────────────────────────────────


def test_coverage_70_to_85_emits_warning():
    result = _build_assessment(
        _report(overall_score=78.0), None, _scope(), QualityGatePolicy.strict
    )
    assert result.verdict == QualityGateVerdict.warning
    assert any(
        i.code == QualityIssueCode.missing_bars and i.severity == "warning"
        for i in result.issues
    )


# ── Test 6: coverage ≥ 85, no gaps → trusted ─────────────────────────────────


def test_clean_report_is_trusted():
    result = _build_assessment(
        _report(overall_score=92.0), None, _scope(), QualityGatePolicy.strict
    )
    assert result.verdict == QualityGateVerdict.trusted
    assert result.trusted is True
    assert result.issues == []
    assert result.score == 92.0


# ── Test 7: gap_count ≥ 1 → warning ─────────────────────────────────────────


def test_gap_count_one_emits_provider_gap_warning():
    report = _report(
        overall_score=90.0,
        tickers=[
            {
                "ticker": "AAPL",
                "gap_count": 1,
                "continuity_score": 95.0,
                "first_bar": "2025-01-01T00:00:00",
                "last_bar": "2026-06-19T00:00:00",
                "coverage_pct": 90.0,
            }
        ],
    )
    result = _build_assessment(report, None, _scope(), QualityGatePolicy.strict)
    assert result.verdict == QualityGateVerdict.warning
    assert any(
        i.code == QualityIssueCode.provider_gap and i.severity == "warning"
        for i in result.issues
    )


# ── Test 8: continuity_score < 70 → blocker ──────────────────────────────────


def test_continuity_below_70_strict_is_blocked():
    report = _report(
        overall_score=90.0,
        tickers=[
            {
                "ticker": "AAPL",
                "gap_count": 15,
                "continuity_score": 25.0,
                "first_bar": "2025-01-01T00:00:00",
                "last_bar": "2026-06-19T00:00:00",
                "coverage_pct": 90.0,
            }
        ],
    )
    result = _build_assessment(report, None, _scope(), QualityGatePolicy.strict)
    assert result.verdict == QualityGateVerdict.blocked
    assert any(
        i.code == QualityIssueCode.provider_gap and i.severity == "blocker"
        for i in result.issues
    )


# ── Test 9: insufficient_lookback ────────────────────────────────────────────


def test_insufficient_lookback_emits_blocker():
    first_bar = (date.today() - timedelta(days=10)).isoformat() + "T00:00:00"
    report = _report(
        overall_score=92.0,
        tickers=[
            {
                "ticker": "AAPL",
                "gap_count": 0,
                "continuity_score": 100.0,
                "first_bar": first_bar,
                "last_bar": "2026-06-19T00:00:00",
                "coverage_pct": 92.0,
            }
        ],
    )
    result = _build_assessment(
        report, _data_requirements(lookback_days=30), _scope(), QualityGatePolicy.strict
    )
    assert any(
        i.code == QualityIssueCode.insufficient_lookback and i.severity == "blocker"
        for i in result.issues
    )


# ── Test 10: assessment shape ─────────────────────────────────────────────────


def test_assessment_shape():
    result = _build_assessment(_report(), None, _scope(), QualityGatePolicy.strict)
    assert result.schema_version == "quality_gate.v1"
    assert result.policy is not None
    assert result.verdict is not None
    assert isinstance(result.trusted, bool)
    assert result.scope is not None
    assert result.generated_at is not None
    assert result.trusted == (result.verdict == QualityGateVerdict.trusted)


# ── Advisory variants (tests 11-12) ──────────────────────────────────────────


def test_coverage_below_70_advisory_blocker_becomes_warning():
    """Under advisory, a blocker-severity issue still yields verdict=warning not blocked."""
    result = _build_assessment(
        _report(overall_score=50.0), None, _scope(), QualityGatePolicy.advisory
    )
    assert result.verdict == QualityGateVerdict.warning
    assert result.trusted is False


def test_continuity_below_70_advisory_is_warning():
    """Under advisory, a provider_gap blocker still yields verdict=warning not blocked."""
    report = _report(
        overall_score=90.0,
        tickers=[
            {
                "ticker": "AAPL",
                "gap_count": 20,
                "continuity_score": 10.0,
                "first_bar": "2025-01-01T00:00:00",
                "last_bar": "2026-06-19T00:00:00",
                "coverage_pct": 90.0,
            }
        ],
    )
    result = _build_assessment(report, None, _scope(), QualityGatePolicy.advisory)
    assert result.verdict == QualityGateVerdict.warning
    assert result.trusted is False
```

#### 2b. Verify all tests fail (12 failures)

```bash
docker-compose exec backend python -m pytest backend/tests/services/test_quality_gate_service.py -x 2>&1 | tail -5
```

Expected: `ImportError` — `quality_gate_service` does not exist yet.

#### 2c. Create the service file

Create `backend/app/services/quality_gate_service.py`:

```python
"""
QualityGateService — converts UniverseQualityReport data into a versioned quality_gate.v1
assessment. Split into a pure builder (no DB) and a thin DB-aware wrapper.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import List, Optional

from sqlalchemy.orm import Session

from app.schemas.quality_gate import (
    QualityGateAssessment,
    QualityGateIssue,
    QualityGatePolicy,
    QualityGateScope,
    QualityGateVerdict,
    QualityIssueCode,
)
from app.utils.time import utc_now


def _derive_verdict(
    issues: List[QualityGateIssue],
    policy: QualityGatePolicy,
) -> QualityGateVerdict:
    has_blocker = any(i.severity == "blocker" for i in issues)
    has_warning = any(i.severity == "warning" for i in issues)
    if has_blocker:
        return (
            QualityGateVerdict.blocked
            if policy == QualityGatePolicy.strict
            else QualityGateVerdict.warning
        )
    if has_warning:
        return QualityGateVerdict.warning
    return QualityGateVerdict.trusted


def _build_assessment(
    report_data: Optional[dict],
    data_requirements: Optional[dict],
    scope: QualityGateScope,
    policy: QualityGatePolicy,
) -> QualityGateAssessment:
    now = utc_now()

    if policy == QualityGatePolicy.off:
        return QualityGateAssessment(
            policy=policy,
            verdict=QualityGateVerdict.skipped,
            trusted=False,
            scope=scope,
            score=None,
            grade=None,
            issues=[],
            warnings=[],
            generated_at=now,
        )

    issues: List[QualityGateIssue] = []

    if report_data is None:
        sev: str = "blocker" if policy == QualityGatePolicy.strict else "warning"
        issues.append(
            QualityGateIssue(
                code=QualityIssueCode.missing_bars,
                severity=sev,
                message="No completed quality report found",
            )
        )
        verdict = _derive_verdict(issues, policy)
        return QualityGateAssessment(
            policy=policy,
            verdict=verdict,
            trusted=(verdict == QualityGateVerdict.trusted),
            scope=scope,
            score=None,
            grade=None,
            issues=issues,
            warnings=[i for i in issues if i.severity == "warning"],
            generated_at=now,
        )

    score = float(report_data.get("overall_score", 0.0))
    grade: Optional[str] = report_data.get("overall_grade")
    tickers = report_data.get("tickers", [])

    # missing_bars: gate on overall_score
    if score < 70:
        issues.append(
            QualityGateIssue(
                code=QualityIssueCode.missing_bars,
                severity="blocker",
                message=f"Coverage {score:.1f}% is below the 70% minimum threshold",
                detail={"coverage_pct": score},
            )
        )
    elif score < 85:
        issues.append(
            QualityGateIssue(
                code=QualityIssueCode.missing_bars,
                severity="warning",
                message=f"Coverage {score:.1f}% is below the 85% target threshold",
                detail={"coverage_pct": score},
            )
        )

    # provider_gap: gate on worst ticker continuity_score and any gap_count
    has_gap = any(t.get("gap_count", 0) >= 1 for t in tickers)
    worst_continuity = min(
        (t.get("continuity_score", 100.0) for t in tickers), default=100.0
    )
    if worst_continuity < 70:
        issues.append(
            QualityGateIssue(
                code=QualityIssueCode.provider_gap,
                severity="blocker",
                message=(
                    f"Worst ticker continuity {worst_continuity:.1f}% is below"
                    " the 70% threshold (>6 gaps)"
                ),
                detail={"worst_continuity_score": worst_continuity},
            )
        )
    elif has_gap:
        issues.append(
            QualityGateIssue(
                code=QualityIssueCode.provider_gap,
                severity="warning",
                message="One or more tickers have provider data gaps",
                detail={"worst_continuity_score": worst_continuity},
            )
        )

    # insufficient_lookback: only when data_requirements provided
    if data_requirements:
        timespans = data_requirements.get("timespans", [])
        if timespans:
            first_bars: List[date] = []
            for t in tickers:
                fb = t.get("first_bar")
                if fb:
                    try:
                        first_bars.append(date.fromisoformat(str(fb)[:10]))
                    except (ValueError, TypeError):
                        pass

            if not first_bars:
                issues.append(
                    QualityGateIssue(
                        code=QualityIssueCode.insufficient_lookback,
                        severity="blocker",
                        message="No first_bar data available to verify lookback coverage",
                    )
                )
            else:
                earliest = min(first_bars)
                today = utc_now().date()
                max_lookback = max(
                    req.get("lookback_days", 0) for req in timespans
                )
                required_from = today - timedelta(days=max_lookback)
                if earliest > required_from:
                    issues.append(
                        QualityGateIssue(
                            code=QualityIssueCode.insufficient_lookback,
                            severity="blocker",
                            message=(
                                f"Earliest data ({earliest}) does not cover the"
                                f" {max_lookback}-day lookback window (need data"
                                f" from {required_from})"
                            ),
                            detail={
                                "earliest_first_bar": earliest.isoformat(),
                                "required_from": required_from.isoformat(),
                                "lookback_days": max_lookback,
                            },
                        )
                    )

    verdict = _derive_verdict(issues, policy)
    return QualityGateAssessment(
        policy=policy,
        verdict=verdict,
        trusted=(verdict == QualityGateVerdict.trusted),
        scope=scope,
        score=score,
        grade=grade,
        issues=issues,
        warnings=[i for i in issues if i.severity == "warning"],
        generated_at=now,
    )


class QualityGateService:
    @staticmethod
    def assess(
        db: Session,
        universe_id: int,
        policy: QualityGatePolicy,
        scope: Optional[QualityGateScope] = None,
    ) -> QualityGateAssessment:
        from app.models.scanner_config import ScannerConfig
        from app.models.universe_quality_report import UniverseQualityReport

        scope = scope or QualityGateScope(universe_id=universe_id)

        report = (
            db.query(UniverseQualityReport)
            .filter(UniverseQualityReport.universe_id == universe_id)
            .first()
        )
        report_data: Optional[dict] = (
            report.report_data
            if report and report.status == "complete"
            else None
        )

        data_requirements: Optional[dict] = None
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

#### 2d. Verify all 12 tests pass

```bash
docker-compose exec backend python -m pytest backend/tests/services/test_quality_gate_service.py -v 2>&1 | tail -20
```

Expected output (all green):
```
PASSED tests/services/test_quality_gate_service.py::test_policy_off_returns_skipped
PASSED tests/services/test_quality_gate_service.py::test_policy_off_ignores_report_content
PASSED tests/services/test_quality_gate_service.py::test_missing_report_strict_is_blocked
PASSED tests/services/test_quality_gate_service.py::test_missing_report_advisory_is_warning
PASSED tests/services/test_quality_gate_service.py::test_coverage_below_70_strict_is_blocked
PASSED tests/services/test_quality_gate_service.py::test_coverage_below_70_advisory_is_warning
PASSED tests/services/test_quality_gate_service.py::test_coverage_70_to_85_emits_warning
PASSED tests/services/test_quality_gate_service.py::test_clean_report_is_trusted
PASSED tests/services/test_quality_gate_service.py::test_gap_count_one_emits_provider_gap_warning
PASSED tests/services/test_quality_gate_service.py::test_continuity_below_70_strict_is_blocked
PASSED tests/services/test_quality_gate_service.py::test_insufficient_lookback_emits_blocker
PASSED tests/services/test_quality_gate_service.py::test_assessment_shape
PASSED tests/services/test_quality_gate_service.py::test_coverage_below_70_advisory_blocker_becomes_warning
PASSED tests/services/test_quality_gate_service.py::test_continuity_below_70_advisory_is_warning
14 passed in 0.XXs
```

If any test fails, diagnose and fix `_build_assessment` before committing.

#### 2e. Confirm the backend reloaded

```bash
docker-compose logs backend --tail=10
```

Expected: hot-reload line with no errors.

#### 2f. Commit

```bash
git add backend/app/services/quality_gate_service.py backend/tests/services/test_quality_gate_service.py
git commit -m "feat(services): QualityGateService pure builder with 12 unit tests (#492)"
```

---

### Task 3 — DB-Aware Wrapper Smoke Tests

**Files**: `backend/tests/services/test_quality_gate_service.py`

#### 3a. Add wrapper smoke tests

Append to `backend/tests/services/test_quality_gate_service.py`:

```python
# ── DB wrapper smoke tests ────────────────────────────────────────────────────


def test_assess_wrapper_with_complete_report():
    """
    Verify QualityGateService.assess() reaches _build_assessment correctly.
    Uses MagicMock to avoid a live DB session — the wrapper is pure I/O.
    """
    from unittest.mock import MagicMock

    from app.services.quality_gate_service import QualityGateService

    mock_report = MagicMock()
    mock_report.status = "complete"
    mock_report.report_data = {
        "overall_score": 92.0,
        "overall_grade": "A",
        "tickers": [
            {
                "ticker": "AAPL",
                "gap_count": 0,
                "continuity_score": 100.0,
                "first_bar": "2025-01-01T00:00:00",
                "last_bar": "2026-06-19T00:00:00",
                "coverage_pct": 92.0,
            }
        ],
    }

    mock_db = MagicMock()
    mock_db.query.return_value.filter.return_value.first.return_value = mock_report

    result = QualityGateService.assess(
        db=mock_db,
        universe_id=1,
        policy=QualityGatePolicy.strict,
    )
    assert result.verdict == QualityGateVerdict.trusted
    assert result.trusted is True
    assert result.score == 92.0


def test_assess_wrapper_missing_report_strict():
    """Missing row → blocked under strict policy via the DB wrapper."""
    from unittest.mock import MagicMock

    from app.services.quality_gate_service import QualityGateService

    mock_db = MagicMock()
    mock_db.query.return_value.filter.return_value.first.return_value = None

    result = QualityGateService.assess(
        db=mock_db,
        universe_id=99,
        policy=QualityGatePolicy.strict,
    )
    assert result.verdict == QualityGateVerdict.blocked


def test_assess_wrapper_incomplete_report_strict():
    """Report row present but status != 'complete' → treated as absent → blocked (strict)."""
    from unittest.mock import MagicMock

    from app.services.quality_gate_service import QualityGateService

    mock_report = MagicMock()
    mock_report.status = "running"
    mock_report.report_data = {"overall_score": 95.0, "overall_grade": "A", "tickers": []}

    mock_db = MagicMock()
    mock_db.query.return_value.filter.return_value.first.return_value = mock_report

    result = QualityGateService.assess(
        db=mock_db,
        universe_id=5,
        policy=QualityGatePolicy.strict,
    )
    assert result.verdict == QualityGateVerdict.blocked
    assert any(i.code == QualityIssueCode.missing_bars for i in result.issues)
```

#### 3b. Run the full test suite

```bash
docker-compose exec backend python -m pytest backend/tests/services/test_quality_gate_service.py -v 2>&1 | tail -25
```

Expected: **15 passed**.

#### 3c. Run broader service tests for regressions

```bash
docker-compose exec backend python -m pytest backend/tests/services/ -q --tb=short 2>&1 | tail -15
```

Expected: all existing tests still pass.

#### 3d. Commit

```bash
git add backend/tests/services/test_quality_gate_service.py
git commit -m "test(services): DB wrapper smoke tests for QualityGateService (#492)"
```

---

## Commit Summary

| # | Commit message | Files |
|---|---|---|
| 1 | `feat(schemas): QualityGateAssessment contract — quality_gate.v1 (#492)` | `schemas/quality_gate.py`, `schemas/__init__.py`, `tests/…/test_quality_gate_service.py` |
| 2 | `feat(services): QualityGateService pure builder with 12 unit tests (#492)` | `services/quality_gate_service.py`, `tests/…/test_quality_gate_service.py` |
| 3 | `test(services): DB wrapper smoke tests for QualityGateService (#492)` | `tests/…/test_quality_gate_service.py` |

## Verification Checklist

- [ ] `backend/app/schemas/quality_gate.py` — all 7 `QualityIssueCode` members, 3 enum types, 3 model classes
- [ ] `backend/app/schemas/__init__.py` — 6 names exported
- [ ] `backend/app/services/quality_gate_service.py` — `_build_assessment`, `_derive_verdict`, `QualityGateService.assess`
- [ ] `backend/tests/services/test_quality_gate_service.py` — 15 tests total (12 builder + 3 wrapper), all green
- [ ] No new models, no migration, no router changes
- [ ] All 10 spec acceptance criteria satisfied by the test suite
