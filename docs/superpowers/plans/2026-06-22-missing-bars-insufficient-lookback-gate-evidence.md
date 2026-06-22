# Plan: Generate Missing Bars and Insufficient Lookback Gate Issues

**Issue**: [#498](https://github.com/omniscient/markethawk/issues/498) — Generate missing bars and insufficient lookback gate issues  
**Spec**: `docs/superpowers/specs/2026-06-19-missing-bars-insufficient-lookback-gate-evidence-design.md`  
**Date**: 2026-06-22  
**Branch**: `refine/issue-498-generate-missing-bars-and-insufficient-l`

---

## Goal

Add a new `quality_gate_evidence.py` service module with two evidence generator functions:
- `generate_missing_bars_issues()` — emits `missing_bars` gate issues when actual bar count falls below the expected count derived from `lookback_days`
- `generate_insufficient_lookback_issues()` — emits `insufficient_lookback` gate issues when actual bar count falls below `min_bars`

Both emit typed `GateIssue` dataclass payloads (the stable seam for the #492 gate policy layer).

No Alembic migration required. No frontend changes.

---

## Architecture

The new module imports from:
- `UniverseQualityReport` model — for the cached `report_data` (preferred path for `generate_missing_bars_issues`)
- `StockAggregate` model — for direct `SELECT count(*)` queries (fallback / `generate_insufficient_lookback_issues`)
- `StockUniverseTicker` model — for universe-wide ticker lists
- `ScannerConfig` model — already imported where called; passed as a parameter

The `GateIssue` stub is a minimal `@dataclass` with 6 fields (`issue_code`, `ticker`, `timespan`, `multiplier`, `observed`, `required`). When #492 lands and defines its `QualityIssue` type, this stub is replaced with a one-line import change.

---

## File Structure

| File | Change |
|------|--------|
| `backend/app/services/quality_gate_evidence.py` | **New** — `GateIssue` stub, `generate_missing_bars_issues()`, `generate_insufficient_lookback_issues()` |
| `backend/tests/services/test_quality_gate_evidence.py` | **New** — 9 unit tests covering all AC-6 scenarios |

---

## Tasks

### Task 1: Scaffold stub module and write all failing unit tests

**Files:**
- `backend/app/services/quality_gate_evidence.py` (stub — raise `NotImplementedError`)
- `backend/tests/services/test_quality_gate_evidence.py` (all tests)

**Step 1 — Create the stub module:**

```python
# backend/app/services/quality_gate_evidence.py
"""
Gate evidence generators for missing_bars and insufficient_lookback gate issues.

Stub module — functions raise NotImplementedError until Task 2/3 implement them.
GateIssue is the stable seam between #498 (evidence) and #492 (policy layer).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from sqlalchemy.orm import Session

from app.models.scanner_config import ScannerConfig


@dataclass
class GateIssue:
    """Stable payload shape consumed by the #492 gate policy layer.

    Replace this stub with #492's canonical QualityIssue import when that
    ticket lands and the field names align.
    """
    issue_code: str        # "missing_bars" | "insufficient_lookback"
    ticker: Optional[str]  # None reserved for future universe-level aggregation
    timespan: str
    multiplier: int
    observed: int          # actual bars available
    required: int          # target bar count from config


def generate_missing_bars_issues(
    db: Session,
    universe_id: int,
    scanner_config: ScannerConfig,
    ticker: Optional[str] = None,
) -> list[GateIssue]:
    raise NotImplementedError


def generate_insufficient_lookback_issues(
    db: Session,
    universe_id: int,
    scanner_config: ScannerConfig,
    ticker: Optional[str] = None,
) -> list[GateIssue]:
    raise NotImplementedError
```

**Step 2 — Write all unit tests:**

```python
# backend/tests/services/test_quality_gate_evidence.py
"""
Unit tests for quality_gate_evidence — generate_missing_bars_issues and
generate_insufficient_lookback_issues.

Uses MagicMock for the DB session (service-layer unit tests, not full-pipeline
regression tests). Each test exercises one scenario from AC-6.
"""
from unittest.mock import MagicMock

import pytest

from app.services.quality_gate_evidence import (
    GateIssue,
    generate_insufficient_lookback_issues,
    generate_missing_bars_issues,
)


# ─── helpers ────────────────────────────────────────────────────────────────


def _cfg(timespans: list) -> MagicMock:
    cfg = MagicMock()
    cfg.data_requirements = {"timespans": timespans}
    return cfg


def _flat_cfg() -> MagicMock:
    """Flat data_requirements shape — no timespans key."""
    cfg = MagicMock()
    cfg.data_requirements = {"timespan": "day", "min_bars": 260}
    return cfg


def _db_with_report(report_data, ticker_rows=None, scalar_side_effect=None) -> MagicMock:
    """Build a MagicMock db that returns a cached report and optional bar counts."""
    report_mock = MagicMock()
    report_mock.report_data = report_data

    filter_mock = MagicMock()
    filter_mock.first.return_value = report_mock
    if ticker_rows is not None:
        filter_mock.all.return_value = ticker_rows
    if scalar_side_effect is not None:
        filter_mock.scalar.side_effect = scalar_side_effect
    else:
        filter_mock.scalar.return_value = 0

    db = MagicMock()
    db.query.return_value.filter.return_value = filter_mock
    return db


# ─── GateIssue dataclass ────────────────────────────────────────────────────


def test_gate_issue_fields_are_populated():
    issue = GateIssue(
        issue_code="missing_bars",
        ticker="AAPL",
        timespan="minute",
        multiplier=1,
        observed=100,
        required=500,
    )
    assert issue.issue_code == "missing_bars"
    assert issue.ticker == "AAPL"
    assert issue.observed == 100
    assert issue.required == 500


# ─── generate_missing_bars_issues ────────────────────────────────────────────


def test_missing_bars_flat_shape_returns_empty():
    """Flat data_requirements (no timespans key) → [] with no DB calls."""
    db = MagicMock()
    issues = generate_missing_bars_issues(db, 1, _flat_cfg(), ticker="AAPL")
    assert issues == []


def test_missing_bars_per_ticker_uses_report_cache():
    """Per-ticker mode: uses report_data cache, emits issue when actual < expected."""
    report_data = {
        "tickers": [
            {
                "ticker": "AAPL",
                "timespan": "minute",
                "multiplier": 1,
                "actual_bars": 200,
                "expected_bars": 500,
            }
        ]
    }
    cfg = _cfg([{"timespan": "minute", "multiplier": 1, "lookback_days": 10}])
    db = _db_with_report(report_data)

    issues = generate_missing_bars_issues(db, 1, cfg, ticker="AAPL")

    assert len(issues) == 1
    assert issues[0].issue_code == "missing_bars"
    assert issues[0].ticker == "AAPL"
    assert issues[0].observed == 200
    assert issues[0].required == 500


def test_missing_bars_no_issue_when_actual_meets_expected():
    """No issue when actual_bars >= expected_bars in cache."""
    report_data = {
        "tickers": [
            {
                "ticker": "AAPL",
                "timespan": "minute",
                "multiplier": 1,
                "actual_bars": 600,
                "expected_bars": 500,
            }
        ]
    }
    cfg = _cfg([{"timespan": "minute", "multiplier": 1, "lookback_days": 10}])
    db = _db_with_report(report_data)

    issues = generate_missing_bars_issues(db, 1, cfg, ticker="AAPL")
    assert issues == []


def test_missing_bars_universe_wide_partial_coverage():
    """Universe-wide (ticker=None): emits issue only for AAPL (below threshold), not MSFT."""
    report_data = {
        "tickers": [
            {
                "ticker": "AAPL",
                "timespan": "minute",
                "multiplier": 1,
                "actual_bars": 200,
                "expected_bars": 500,
            },
            {
                "ticker": "MSFT",
                "timespan": "minute",
                "multiplier": 1,
                "actual_bars": 600,
                "expected_bars": 500,
            },
        ]
    }
    cfg = _cfg([{"timespan": "minute", "multiplier": 1, "lookback_days": 10}])
    ticker_rows = [MagicMock(ticker="AAPL"), MagicMock(ticker="MSFT")]
    db = _db_with_report(report_data, ticker_rows=ticker_rows)

    issues = generate_missing_bars_issues(db, 1, cfg, ticker=None)

    assert len(issues) == 1
    assert issues[0].ticker == "AAPL"


def test_missing_bars_fallback_direct_db_when_no_report():
    """When report_data is absent, falls back to direct SELECT count(*) for actual_bars."""
    cfg = _cfg([{"timespan": "day", "multiplier": 1, "lookback_days": 90}])
    db = _db_with_report(report_data=None, scalar_side_effect=[10])

    issues = generate_missing_bars_issues(db, 1, cfg, ticker="AAPL")

    # expected_bars = 90 * 1 bar/day = 90; actual = 10 → issue emitted
    assert len(issues) == 1
    assert issues[0].observed == 10
    assert issues[0].required == 90


# ─── generate_insufficient_lookback_issues ───────────────────────────────────


def test_insufficient_lookback_flat_shape_returns_empty():
    """Flat data_requirements (no timespans key) → []."""
    db = MagicMock()
    assert generate_insufficient_lookback_issues(db, 1, _flat_cfg(), ticker="AAPL") == []


def test_insufficient_lookback_no_min_bars_returns_empty():
    """Timespan with no min_bars field → no issue emitted, regardless of bar count."""
    cfg = _cfg([{"timespan": "minute", "multiplier": 1, "lookback_days": 10}])
    db = MagicMock()
    db.query.return_value.filter.return_value.scalar.return_value = 0

    issues = generate_insufficient_lookback_issues(db, 1, cfg, ticker="AAPL")
    assert issues == []


def test_insufficient_lookback_per_ticker_emits_when_below_min_bars():
    """Per-ticker: emits issue when actual bar count < min_bars."""
    cfg = _cfg([{"timespan": "day", "multiplier": 1, "lookback_days": 90, "min_bars": 260}])
    db = MagicMock()
    db.query.return_value.filter.return_value.scalar.return_value = 50  # actual bars

    issues = generate_insufficient_lookback_issues(db, 1, cfg, ticker="AAPL")

    assert len(issues) == 1
    assert issues[0].issue_code == "insufficient_lookback"
    assert issues[0].ticker == "AAPL"
    assert issues[0].observed == 50
    assert issues[0].required == 260


def test_insufficient_lookback_universe_wide_partial_coverage():
    """Universe-wide (ticker=None): AAPL fails (50 < 260), MSFT passes (300 >= 260)."""
    cfg = _cfg([{"timespan": "day", "multiplier": 1, "lookback_days": 90, "min_bars": 260}])
    ticker_rows = [MagicMock(ticker="AAPL"), MagicMock(ticker="MSFT")]

    filter_mock = MagicMock()
    filter_mock.all.return_value = ticker_rows
    filter_mock.scalar.side_effect = [50, 300]  # AAPL → 50, MSFT → 300

    db = MagicMock()
    db.query.return_value.filter.return_value = filter_mock

    issues = generate_insufficient_lookback_issues(db, 1, cfg, ticker=None)

    assert len(issues) == 1
    assert issues[0].ticker == "AAPL"
    assert issues[0].observed == 50
    assert issues[0].required == 260
```

**Step 3 — Run tests, expect all to fail with `NotImplementedError` (or `ImportError` if stub is missing):**

```bash
# From backend/ directory inside the container:
cd /workspace/markethawk
docker-compose exec backend python -m pytest backend/tests/services/test_quality_gate_evidence.py -v 2>&1 | tail -20
# Expected: 9 FAILED (NotImplementedError for generate_* calls)
```

**Commit:**
```bash
git add backend/app/services/quality_gate_evidence.py backend/tests/services/test_quality_gate_evidence.py
git commit -m "test: add failing tests for quality_gate_evidence (#498)"
```

---

### Task 2: Implement `generate_missing_bars_issues()`

**Files:**
- `backend/app/services/quality_gate_evidence.py`

Replace the stub with the full implementation. The function prefers the `UniverseQualityReport.report_data` cache and falls back to a direct `SELECT count(*)` query.

**Full module replacement:**

```python
# backend/app/services/quality_gate_evidence.py
"""
Gate evidence generators for missing_bars and insufficient_lookback gate issues.

Wires DataQualityService bar-count analysis and ScannerConfig.data_requirements
into typed GateIssue payloads for the #492 gate policy layer.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.scanner_config import ScannerConfig
from app.models.stock_aggregate import StockAggregate
from app.models.stock_universe_ticker import StockUniverseTicker
from app.models.universe_quality_report import UniverseQualityReport

# Approximate bars per trading day for each timespan unit (multiplier=1).
# Used only in the fallback path when no cached report_data is available.
_BARS_PER_TRADING_DAY: dict[str, int] = {
    "minute": 390,
    "hour": 7,
    "day": 1,
    "week": 1,
    "month": 1,
}


@dataclass
class GateIssue:
    """Stable payload shape consumed by the #492 gate policy layer.

    Replace this stub with #492's canonical QualityIssue import when that
    ticket lands and the field names align.
    """
    issue_code: str        # "missing_bars" | "insufficient_lookback"
    ticker: Optional[str]  # None reserved for future universe-level aggregation
    timespan: str
    multiplier: int
    observed: int          # actual bars available
    required: int          # target bar count from config


def _get_tickers(db: Session, universe_id: int, ticker: Optional[str]) -> list[str]:
    if ticker is not None:
        return [ticker]
    rows = (
        db.query(StockUniverseTicker)
        .filter(StockUniverseTicker.universe_id == universe_id)
        .all()
    )
    return [r.ticker for r in rows]


def _load_report_cache(
    db: Session, universe_id: int
) -> dict[tuple[str, str, int], tuple[int, int]]:
    """Return {(ticker, timespan, multiplier): (actual_bars, expected_bars)} from cache."""
    report = (
        db.query(UniverseQualityReport)
        .filter(UniverseQualityReport.universe_id == universe_id)
        .first()
    )
    if not report or not report.report_data:
        return {}
    cache: dict[tuple[str, str, int], tuple[int, int]] = {}
    for entry in report.report_data.get("tickers", []):
        t = entry.get("ticker")
        ts = entry.get("timespan")
        mult = entry.get("multiplier")
        if t and ts and mult is not None:
            cache[(t, ts, int(mult))] = (
                int(entry.get("actual_bars", 0)),
                int(entry.get("expected_bars", 0)),
            )
    return cache


def _count_bars(db: Session, ticker: str, timespan: str, multiplier: int) -> int:
    return (
        db.query(func.count(StockAggregate.id))
        .filter(
            StockAggregate.ticker == ticker,
            StockAggregate.timespan == timespan,
            StockAggregate.multiplier == multiplier,
        )
        .scalar()
        or 0
    )


def generate_missing_bars_issues(
    db: Session,
    universe_id: int,
    scanner_config: ScannerConfig,
    ticker: Optional[str] = None,
) -> list[GateIssue]:
    """Emit GateIssue(issue_code='missing_bars') for each ticker × timespan where
    actual bar count is below the expected count derived from lookback_days.

    Prefers UniverseQualityReport.report_data cache; falls back to a direct
    SELECT count(*) FROM stock_aggregates when no report exists or is absent.
    Returns [] when data_requirements has no timespans[] key.
    """
    timespans = (scanner_config.data_requirements or {}).get("timespans", [])
    if not timespans:
        return []

    tickers_to_check = _get_tickers(db, universe_id, ticker)
    cache = _load_report_cache(db, universe_id)

    issues: list[GateIssue] = []
    for t in tickers_to_check:
        for ts_cfg in timespans:
            ts = ts_cfg.get("timespan", "minute")
            mult = int(ts_cfg.get("multiplier", 1))
            lookback_days = ts_cfg.get("lookback_days")
            if not lookback_days:
                continue

            cache_key = (t, ts, mult)
            if cache_key in cache:
                actual_bars, expected_bars = cache[cache_key]
            else:
                actual_bars = _count_bars(db, t, ts, mult)
                # Simplified estimate for fallback: lookback_days × bars per trading day.
                # The cache path uses the P90-based expected_bars from DataQualityService.
                bars_per_day = max(1, _BARS_PER_TRADING_DAY.get(ts, 60) // mult)
                expected_bars = lookback_days * bars_per_day

            if actual_bars < expected_bars:
                issues.append(
                    GateIssue(
                        issue_code="missing_bars",
                        ticker=t,
                        timespan=ts,
                        multiplier=mult,
                        observed=actual_bars,
                        required=expected_bars,
                    )
                )

    return issues


def generate_insufficient_lookback_issues(
    db: Session,
    universe_id: int,
    scanner_config: ScannerConfig,
    ticker: Optional[str] = None,
) -> list[GateIssue]:
    raise NotImplementedError
```

**Step — Run missing_bars tests only, expect pass:**

```bash
docker-compose exec backend python -m pytest backend/tests/services/test_quality_gate_evidence.py -v -k "not insufficient" 2>&1 | tail -20
# Expected: 6 passed (test_gate_issue_fields_are_populated + 5 missing_bars tests)
```

**Commit:**
```bash
git add backend/app/services/quality_gate_evidence.py
git commit -m "feat: add GateIssue stub and generate_missing_bars_issues (#498)"
```

---

### Task 3: Implement `generate_insufficient_lookback_issues()` and verify all tests pass

**Files:**
- `backend/app/services/quality_gate_evidence.py`

Replace the `raise NotImplementedError` stub with the full implementation. This generator always queries `stock_aggregates` directly (count only) — `report_data` does not store the timespan-filtered bar count against `min_bars`.

**Replace the `generate_insufficient_lookback_issues` function body:**

```python
def generate_insufficient_lookback_issues(
    db: Session,
    universe_id: int,
    scanner_config: ScannerConfig,
    ticker: Optional[str] = None,
) -> list[GateIssue]:
    """Emit GateIssue(issue_code='insufficient_lookback') for each ticker × timespan
    where actual bar count is below min_bars from data_requirements.

    Only emits issues for timespans that carry a min_bars field.
    Always queries stock_aggregates directly — report_data does not store
    the timespan-filtered count against min_bars.
    Returns [] when data_requirements has no timespans[] key, or when no
    timespans have min_bars configured.
    """
    timespans = (scanner_config.data_requirements or {}).get("timespans", [])
    if not timespans:
        return []

    tickers_to_check = _get_tickers(db, universe_id, ticker)

    issues: list[GateIssue] = []
    for t in tickers_to_check:
        for ts_cfg in timespans:
            min_bars = ts_cfg.get("min_bars")
            if min_bars is None:
                continue
            ts = ts_cfg.get("timespan", "minute")
            mult = int(ts_cfg.get("multiplier", 1))

            actual_bars = _count_bars(db, t, ts, mult)

            if actual_bars < int(min_bars):
                issues.append(
                    GateIssue(
                        issue_code="insufficient_lookback",
                        ticker=t,
                        timespan=ts,
                        multiplier=mult,
                        observed=actual_bars,
                        required=int(min_bars),
                    )
                )

    return issues
```

**Step — Run full test suite, expect all 9 pass:**

```bash
docker-compose exec backend python -m pytest backend/tests/services/test_quality_gate_evidence.py -v 2>&1 | tail -20
# Expected: 9 passed
```

**Step — Also run the broader backend test suite to check for regressions:**

```bash
docker-compose exec backend python -m pytest backend/tests/services/ -v 2>&1 | tail -30
# Expected: no regressions
```

**Commit:**
```bash
git add backend/app/services/quality_gate_evidence.py
git commit -m "feat: implement generate_insufficient_lookback_issues (#498)"
```

---

## Implementation Notes

### Data flow: `generate_missing_bars_issues()`

```
ScannerConfig.data_requirements.timespans[]
    ↓ for each timespan entry with lookback_days
UniverseQualityReport.report_data["tickers"]  ← preferred (P90-based expected_bars)
    ↓ cache miss
SELECT count(*) FROM stock_aggregates WHERE ticker=? AND timespan=? AND multiplier=?
    + lookback_days × _BARS_PER_TRADING_DAY[timespan] // multiplier  ← simplified estimate
    ↓ if actual_bars < expected_bars
GateIssue(issue_code="missing_bars", ticker=t, observed=actual, required=expected)
```

### Data flow: `generate_insufficient_lookback_issues()`

```
ScannerConfig.data_requirements.timespans[]
    ↓ only entries with min_bars field
SELECT count(*) FROM stock_aggregates WHERE ticker=? AND timespan=? AND multiplier=?
    ↓ if actual_bars < min_bars
GateIssue(issue_code="insufficient_lookback", ticker=t, observed=actual, required=min_bars)
```

### Flat shape handling

Both generators call `.get("timespans", [])` on `data_requirements`. The trend_pullback scanner stores `{"timespan": "day", "min_bars": 260}` (no `timespans` key) — this returns `[]` and both generators return `[]` silently, consistent with `DataReadinessService.check()`. This is a pre-existing gap documented in spec assumption [A5].

### `GateIssue` stub lifetime

`GateIssue` is intentionally thin — 6 fields, no policy logic. When #492 lands with its `QualityIssue` canonical type, the replacement is a one-line import change (if field names align). The `#498` tests verify the payload shape so the alignment check is mechanical.
