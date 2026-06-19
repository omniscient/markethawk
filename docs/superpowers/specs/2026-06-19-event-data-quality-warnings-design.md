# Event-Scoped Data Quality Warnings — Design

**Date:** 2026-06-19
**Issue:** #454
**Parent epic:** #448 (Explainability Foundation)
**Status:** Pending review

## Overview

Scanner explanation generation needs to know *how trustworthy* the data behind a
specific event was.  The existing `DataReadinessService` and `DataQualityService`
answer universe-level questions ("is this ticker ready for outcome tracking?",
"what is the overall data grade for this universe?").  They do not answer the
event-scoped question: "given ticker X fired on date D under scanner type S, what
data-quality warnings should appear in its `scanner_explanation.v1` payload?"

This spec defines enhancements to both services to support explanation generation
without changing any existing call sites.

## Requirements

1. `DataReadinessService` gains a new method `check_for_event(db, ticker,
   scanner_type, event_date)` that checks data presence against the event date
   instead of today.
2. `DataQualityService` gains a new method `check_event_window(db, ticker,
   scanner_type, event_date)` that runs coverage/integrity/continuity checks
   scoped to the event window and returns structured warnings.
3. Six shared warning codes exist: `MISSING_REQUIRED_TIMESPAN`, `LOW_COVERAGE`,
   `INTEGRITY_VIOLATION`, `CONTINUITY_GAP`, `STALE_DATA`, `INSUFFICIENT_LOOKBACK`.
4. Each warning carries `code`, `severity`, `message`, and `affected_inputs` — the
   same shape as `data_quality_warnings` entries in `scanner_explanation.v1`.
5. `affected_inputs` is populated from a static per-scanner registry for known
   scanners; unknown scanners fall back to `[]`.
6. All existing `DataReadinessService.check()` and `DataQualityService.analyze_universe()`
   call sites are byte-for-byte unaffected.

## Architecture

### New file: `backend/app/services/data_warnings.py`

Central home for the shared warning vocabulary and the `DataWarning` dataclass.

```python
from dataclasses import dataclass, field
from typing import List

# Warning codes
MISSING_REQUIRED_TIMESPAN = "missing_required_timespan"
LOW_COVERAGE             = "low_coverage"
INTEGRITY_VIOLATION      = "integrity_violation"
CONTINUITY_GAP           = "continuity_gap"
STALE_DATA               = "stale_data"
INSUFFICIENT_LOOKBACK    = "insufficient_lookback"

@dataclass
class DataWarning:
    code: str
    severity: str           # "low" | "medium" | "high"
    message: str
    affected_inputs: List[str] = field(default_factory=list)

# Static registry: scanner_type → timespan key → affected explanation inputs.
# Timespan key format: "{multiplier}{timespan}", e.g. "1minute", "1day".
# Input names match the criterion IDs used in scanner_explanation.v1.
SCANNER_INPUT_REGISTRY: dict[str, dict[str, list[str]]] = {
    "pre_market_volume_spike": {
        "1minute": ["vwap", "pre_market_volume", "relative_volume", "pre_market_high",
                    "pre_market_low"],
        "1day":    ["avg_daily_volume", "price_gap_pct"],
    },
    "oversold_bounce": {
        "1minute": ["rsi", "session_volume"],
        "1day":    ["avg_daily_volume", "prev_close"],
    },
    "pocket_pivot": {
        "1day":    ["avg_daily_volume", "pocket_pivot_volume_ratio"],
    },
    "trend_pullback": {
        "1day":    ["sma_20", "sma_50", "sma_200", "rsi_5", "avg_dollar_volume"],
    },
}

def _affected_inputs(scanner_type: str, timespan: str, multiplier: int) -> list[str]:
    key = f"{multiplier}{timespan}"
    return SCANNER_INPUT_REGISTRY.get(scanner_type, {}).get(key, [])
```

The registry is intentionally static; it should be updated when a new scanner
registers new criterion IDs, not via DB config (see Alternatives).

### Enhanced `DataReadinessService` (`backend/app/services/data_readiness.py`)

Add a new method alongside the untouched `check()`:

```python
@staticmethod
def check_for_event(
    db: Session,
    ticker: str,
    scanner_type: str,
    event_date: date,
) -> ReadinessReport:
    """
    Event-date-aware readiness check.  Identical to check() but uses
    event_date as the reference instead of date.today().
    """
```

Implementation changes relative to `check()`:
- Replace `today = date.today()` with `reference = event_date`.
- `req_to = reference`, `req_from = reference - timedelta(days=lookback)`.
- After computing `ready` for each timespan, emit `DataWarning` objects:
  - `avail_from is None` → `MISSING_REQUIRED_TIMESPAN` (high)
  - `avail_from > req_from` → `INSUFFICIENT_LOOKBACK` (medium; message includes how
    many days of lookback are missing)
- Extend `ReadinessReport` with `warnings: List[DataWarning] = field(default_factory=list)`.
- Populate `affected_inputs` via `_affected_inputs(scanner_type, ts, mult)`.

`check()` is not modified.

### Enhanced `DataQualityService` (`backend/app/services/data_quality.py`)

Add a new method alongside the untouched `analyze_universe()`:

```python
@staticmethod
def check_event_window(
    db: Session,
    ticker: str,
    scanner_type: str,
    event_date: date,
) -> List[DataWarning]:
    """
    Returns quality warnings for the data window relevant to the given event.
    """
```

**Session window scoping:**
Query `StockAggregate` filtered to `date(timestamp) = event_date`.  Use the
already-stored `is_pre_market` / `is_after_market` flags rather than hard-coding
time boundaries:

| Scanner type               | Filter applied          |
|---------------------------|------------------------|
| `pre_market_volume_spike`  | `is_pre_market = true`  |
| `oversold_bounce`          | `is_pre_market = false AND is_after_market = false` (regular session) |
| `pocket_pivot`, `trend_pullback` | `timespan='day'` daily aggregate for `event_date` |
| Unknown scanners           | all bars on `event_date` (no session filter) |

**Lookback window for coverage check:**
Query `StockAggregate` from `event_date - lookback_days` to `event_date` (where
`lookback_days` comes from `ScannerConfig.data_requirements.timespans[].lookback_days`,
default 30 if not configured).  Reuse `_analyze_ticker_timespan` helper from
`data_quality.py` but bound by date filter.

**Warning emission rules:**

| Condition | Code | Severity |
|-----------|------|----------|
| Session window has 0 bars on `event_date` | `STALE_DATA` | high |
| Session window has bars but last bar is ≥ 30 min before session end | `STALE_DATA` | medium |
| `coverage_pct < 70%` (lookback window) | `LOW_COVERAGE` | high |
| `70% ≤ coverage_pct < 85%` | `LOW_COVERAGE` | medium |
| `bad_bar_count > 0` in session window | `INTEGRITY_VIOLATION` | high |
| `gap_count ≥ 2` in session window | `CONTINUITY_GAP` | high |
| `gap_count == 1` in session window | `CONTINUITY_GAP` | medium |

`affected_inputs` is populated via `_affected_inputs(scanner_type, ts, mult)` for
the relevant timespan.

### Extended `ReadinessReport` dataclass

```python
@dataclass
class ReadinessReport:
    ticker: str
    scanner_type: str
    coverages: List[TimespanCoverage] = field(default_factory=list)
    is_ready: bool = False
    missing_summary: str = ""
    warnings: List[DataWarning] = field(default_factory=list)  # NEW — empty on check()
```

### How explanation generation uses these

The explanation builder (a later issue in #448) will call both new methods and
merge the results:

```python
readiness = DataReadinessService.check_for_event(db, ticker, scanner_type, event_date)
quality_warnings = DataQualityService.check_event_window(db, ticker, scanner_type, event_date)
all_warnings = readiness.warnings + quality_warnings
# → placed into scanner_explanation.v1 data_quality_warnings field
```

Both methods are pure read-only DB queries — no writes, no side effects.

## Alternatives considered

### Alt 1 — Single new method on one service only

The issue says "enhance existing DataReadinessService and DataQualityService"
(plural), and the two services answer genuinely different questions: presence
check (is the data here?) vs. quality check (how good is the data?). Collapsing
into one method entangles a fast presence check with an expensive per-bar scan.
Rejected.

### Alt 2 — Extend `ScannerConfig.data_requirements` to carry `affects` list

Would allow operators to configure the timespan→explanation-input mapping without
code changes, but `data_requirements` is an acquisition config (which timespans
to download and how far back), not a semantic mapping. Adding `affects` invites
drift between config and the criteria code, requires a DB migration to backfill
existing rows, and risks breaking existing callers. Static registry is cheaper
and more transparent. Rejected.

### Alt 3 — Leave `affected_inputs: []` for now

The issue's AC says "where possible." Pre-market and all four existing scanners
are understood today. Deferring to empty always satisfies the AC vacuously.
Rejected in favour of the static registry which satisfies it genuinely.

## Assumptions

- `ScannerConfig.data_requirements` is present for all scanner types before this
  code is exercised. If absent, `check_for_event` treats the ticker as ready
  (same behaviour as existing `check()`).
- `StockAggregate.is_pre_market` and `is_after_market` flags are correctly
  populated by the sync pipeline; the spec depends on these flags for session
  scoping of intraday scanners.
- Lookback default of 30 days is used when `data_requirements` is not configured
  for a scanner type.

## Open questions (non-blocking)

- Should `check_event_window` also support `FuturesAggregate`? The existing
  `analyze_universe` handles futures, but the explanation pipeline targets
  equity scanners first. Futures support can be added in a follow-on.
- Session-end boundary for `STALE_DATA` "medium" (30-min tolerance) is a
  placeholder — may need tuning after observing real pre-market data density.
