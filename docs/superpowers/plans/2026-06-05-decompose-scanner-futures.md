# Decompose scanner.py / futures_data.py God Modules — Implementation Plan

**Date:** 2026-06-05
**Issue:** [#199](https://github.com/omniscient/markethawk/issues/199)
**Spec:** [docs/superpowers/specs/2026-06-05-decompose-scanner-futures-design.md](../specs/2026-06-05-decompose-scanner-futures-design.md)
**Status:** Ready for implementation

---

## Goal

Reduce `backend/app/services/scanner.py` (1,033 lines) and `backend/app/services/futures_data.py` (1,086 lines) to focused sibling files via two sequential PRs. Zero callers, tests, or import sites change. Spec targets ≤400 lines for `scanner.py` and ≤300 lines for each extracted module; `futures_aggregates.py` (~525 lines) is a documented exception — the spec explicitly notes it as an open question and accepts it for v1.

## Architecture

Two sequential PRs using the **re-export facade** pattern: the original module keeps every public symbol importable by re-exporting from extracted modules. The original `ScannerService` and `FuturesDataService` classes are retained as thin facades that delegate to focused submodules.

All extracted files live as flat siblings in `backend/app/services/` — no subpackages. Scanner PR comes first (5 import sites, one public symbol, lower risk), futures PR second (9 import sites, three public symbols, higher blast radius).

**Circular import strategy (PR 1):** `scanner.py` uses lazy (function-body) imports for `pre_market_scan` and `oversold_bounce_scan` delegation, matching the pattern those registry files already use to call back into `ScannerService`. Top-level imports are used for `session_metrics` and `scan_enrichment` (no cycle risk).

## Tech Stack

- Backend only: FastAPI service layer, SQLAlchemy sync `Session`
- No model changes → no migrations
- No frontend changes
- Testing: pytest, existing test suite is the regression guard

---

## File Structure

| File | Action | Target Size |
|------|--------|-------------|
| `backend/app/services/session_metrics.py` | **Create** | ~135 lines |
| `backend/app/services/scan_enrichment.py` | **Create** | ~185 lines |
| `backend/app/services/pre_market_scan.py` | **Extend** (+~360 lines) | ~400 lines |
| `backend/app/services/oversold_bounce_scan.py` | **Extend** (+~210 lines) | ~235 lines |
| `backend/app/services/scanner.py` | **Reduce** | ~280 lines |
| `backend/tests/services/test_session_metrics.py` | **Create** | ~30 lines |
| `backend/tests/services/test_scan_enrichment.py` | **Create** | ~20 lines |
| `backend/app/services/futures_contracts.py` | **Create** | ~130 lines |
| `backend/app/services/futures_aggregates.py` | **Create** | ~525 lines |
| `backend/app/services/futures_rollovers.py` | **Create** | ~170 lines |
| `backend/app/services/futures_series.py` | **Create** | ~165 lines |
| `backend/app/services/futures_data.py` | **Reduce** | ~95 lines |
| `backend/tests/services/test_futures_decompose.py` | **Create** | ~35 lines |

---

## PR 1 — Decompose `scanner.py`

---

### Task 1 — Create `session_metrics.py`

**Files:** `backend/app/services/session_metrics.py` (new), `backend/tests/services/test_session_metrics.py` (new)

**1a. Write the failing test**

```python
# backend/tests/services/test_session_metrics.py
from app.services.session_metrics import (
    calculate_day_metrics_from_aggs,
    calculate_day_metrics,
)


def test_calculate_day_metrics_from_aggs_empty_list():
    result = calculate_day_metrics_from_aggs([])
    assert result["pre_market_high"] == 0.0
    assert result["total_volume"] == 0


def test_calculate_day_metrics_imported_directly():
    # Verifies the function is importable from the new module
    assert callable(calculate_day_metrics)
```

**1b. Verify it fails**
```bash
cd /workspace/markethawk && docker-compose exec backend python -m pytest backend/tests/services/test_session_metrics.py -x 2>&1 | tail -5
# Expected: ModuleNotFoundError: No module named 'app.services.session_metrics'
```

**1c. Create `session_metrics.py`**

Copy the two metric methods verbatim from `scanner.py` lines 54–187 into a new module-level functions (drop the `@staticmethod` decorator and `ScannerService.` prefix):

```python
# backend/app/services/session_metrics.py
"""Session and day metrics computation — extracted from ScannerService."""
from datetime import date, datetime, timezone
from typing import Any, Dict, List
from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session

from app.models.stock_aggregate import StockAggregate

_ET = ZoneInfo("America/New_York")


def calculate_day_metrics_from_aggs(aggs: List[StockAggregate]) -> Dict[str, Any]:
    """Calculate detailed price metrics from a list of minute aggregates."""
    # [PASTE verbatim body from scanner.py lines 56–108, unchanged]
    ...


def calculate_day_metrics(
    ticker: str, event_date: date, db: Session
) -> Dict[str, Any]:
    """Calculate detailed price metrics for different sessions of a given day."""
    # [PASTE verbatim body from scanner.py lines 114–187, unchanged]
    # Note: uses db.query() (sync Session) — this matches the existing pattern
    ...
```

**1d. Verify the test passes**
```bash
docker-compose exec backend python -m pytest backend/tests/services/test_session_metrics.py -x -q
# Expected: 2 passed
```

**1e. Confirm existing scanner tests still green (baseline check)**
```bash
docker-compose exec backend python -m pytest backend/tests/services/test_scanner_service_methods.py backend/tests/services/test_scanner_refactor.py backend/tests/services/test_feature_enrichment.py -q
# Expected: all passed (scanner.py is unchanged so far)
```

**1f. Commit**
```bash
git add backend/app/services/session_metrics.py backend/tests/services/test_session_metrics.py
git commit -m "refactor(scanner): extract session_metrics.py

Move calculate_day_metrics_from_aggs and calculate_day_metrics out of
ScannerService into a focused session_metrics module. ScannerService
delegation shims added in a later task.

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
```

---

### Task 2 — Create `scan_enrichment.py`

**Files:** `backend/app/services/scan_enrichment.py` (new), `backend/tests/services/test_scan_enrichment.py` (new)

**2a. Write the failing test**
```python
# backend/tests/services/test_scan_enrichment.py
from app.services.scan_enrichment import (
    _SECTOR_ETF_MAP,
    _SECTOR_ETF_SYMBOLS,
    _get_batch_enrichment_data,
    _get_batch_enrichment_data_impl,
)


def test_sector_etf_map_has_technology():
    assert _SECTOR_ETF_MAP["Technology"] == "XLK"


def test_sector_etf_symbols_is_list():
    assert isinstance(_SECTOR_ETF_SYMBOLS, list)
    assert "XLK" in _SECTOR_ETF_SYMBOLS


def test_enrichment_functions_are_callable():
    assert callable(_get_batch_enrichment_data)
    assert callable(_get_batch_enrichment_data_impl)
```

**2b. Verify it fails**
```bash
docker-compose exec backend python -m pytest backend/tests/services/test_scan_enrichment.py -x 2>&1 | tail -5
# Expected: ModuleNotFoundError: No module named 'app.services.scan_enrichment'
```

**2c. Create `scan_enrichment.py`**

Move the constants and both enrichment functions verbatim from `scanner.py` lines 31–49 and 246–433:

```python
# backend/app/services/scan_enrichment.py
"""Batch ticker enrichment for scanner runs — extracted from ScannerService."""
import logging
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple
from zoneinfo import ZoneInfo

from sqlalchemy import desc
from sqlalchemy.orm import Session

from app.exceptions import DataFetchError, ProviderError, ScanError
from app.models.futures_aggregate import FuturesAggregate
from app.models.monitored_stock import MonitoredStock
from app.models.stock_aggregate import StockAggregate
from app.models.stock_split import StockSplit
from app.models.ticker_reference import TickerReference
from app.services.catalyst_parser import CatalystParser

_ET = ZoneInfo("America/New_York")

_SECTOR_ETF_MAP: Dict[str, str] = {
    "Technology": "XLK",
    "Financials": "XLF",
    "Health Care": "XLV",
    "Consumer Discretionary": "XLY",
    "Consumer Staples": "XLP",
    "Energy": "XLE",
    "Industrials": "XLI",
    "Materials": "XLB",
    "Real Estate": "XLRE",
    "Utilities": "XLU",
    "Communication Services": "XLC",
}
_SECTOR_ETF_SYMBOLS = list(_SECTOR_ETF_MAP.values())


def _get_batch_enrichment_data(
    tickers: List[str], event_date: date, db: Session
) -> Tuple[Dict[str, Dict[str, Any]], Dict[str, Any], Dict[str, Optional[float]]]:
    """Fetch common enrichment data for a batch of tickers.
    Wraps _get_batch_enrichment_data_impl with an OpenTelemetry span.
    """
    from opentelemetry import trace as _otel_trace
    _tracer = _otel_trace.get_tracer(__name__)
    with _tracer.start_as_current_span("scanner.batch_enrichment") as _span:
        _span.set_attribute("ticker_count", len(tickers))
        return _get_batch_enrichment_data_impl(tickers, event_date, db)


def _get_batch_enrichment_data_impl(
    tickers: List[str], event_date: date, db: Session
) -> Tuple[Dict[str, Dict[str, Any]], Dict[str, Any], Dict[str, Optional[float]]]:
    # [PASTE verbatim body from scanner.py lines 264–433, unchanged]
    # References to _SECTOR_ETF_SYMBOLS are already module-level in this file.
    ...
```

**2d. Verify the test passes**
```bash
docker-compose exec backend python -m pytest backend/tests/services/test_scan_enrichment.py -x -q
# Expected: 3 passed
```

**2e. Commit**
```bash
git add backend/app/services/scan_enrichment.py backend/tests/services/test_scan_enrichment.py
git commit -m "refactor(scanner): extract scan_enrichment.py

Move _SECTOR_ETF_MAP/_SECTOR_ETF_SYMBOLS constants and both batch
enrichment functions from ScannerService into focused scan_enrichment
module. ScannerService delegation shims added in Task 5.

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
```

---

### Task 3 — Extend `pre_market_scan.py` with `run_pre_market_scan`

**Files:** `backend/app/services/pre_market_scan.py` (extend)

**3a. Write the failing test** (add to `test_scanner_service_methods.py` or new file)

Add a single import check confirming the function is callable from the registry module before we add it:

```python
# In a new file backend/tests/services/test_pre_market_scan_module.py
def test_run_pre_market_scan_importable_from_module():
    from app.services.pre_market_scan import run_pre_market_scan
    assert callable(run_pre_market_scan)
```

**3b. Verify it fails**
```bash
docker-compose exec backend python -m pytest backend/tests/services/test_pre_market_scan_module.py -x 2>&1 | tail -5
# Expected: ImportError: cannot import name 'run_pre_market_scan'
```

**3c. Add `run_pre_market_scan` to `pre_market_scan.py`**

Add required imports at the top of `pre_market_scan.py` (after the existing `scan_orchestrator` import), then add the function body:

```python
# backend/app/services/pre_market_scan.py  — additions
import asyncio
import logging
import time as _time
from datetime import date, datetime, time, timedelta, timezone
from typing import TYPE_CHECKING, Any, Dict, List, Optional
from zoneinfo import ZoneInfo

import pandas as pd
from sqlalchemy import desc, func
from sqlalchemy.orm import Session

from app.core.metrics import scan_duration_seconds, scanner_events_total
from app.exceptions import DataFetchError, ProviderError, ScanError
from app.models.stock_aggregate import StockAggregate
from app.models.stock_split import StockSplit
from app.models.system_config import SystemConfig
from app.services.scan_enrichment import _SECTOR_ETF_MAP
from app.services.timeseries_forecast import compute_anomaly_score
from app.utils.session import get_market_today

if TYPE_CHECKING:
    from app.models.scanner_run import ScannerRun
```

> **Why these imports and not `scan_enrichment` / `session_metrics` / `signal_ranker` / `get_volume_forecast`?**
> The body calls `ScannerService._get_batch_enrichment_data`, `ScannerService.calculate_day_metrics`, and `ScannerService._save_event` via the facade (see substitution table below) — those route through `ScannerService` class attributes so `patch.object(ScannerService, ...)` intercepts them. `load_ranker_config` and `get_volume_forecast` must be accessed through the `scanner` module object (not imported directly) so that `patch("app.services.scanner.load_ranker_config", ...)` / `patch("app.services.scanner.get_volume_forecast", ...)` intercept them. `compute_anomaly_score` has no test patch — import it directly. `desc` and `func` are used in the body queries.

```python
async def run_pre_market_scan(
    tickers: List[str],
    db: Session,
    event_date: date = None,
    scanner_run: Optional["ScannerRun"] = None,
) -> List[Dict[str, Any]]:
    """Run extended hours volume spike scanner using DB aggregates."""
    # [PASTE verbatim body from scanner.py lines 473–816]
    # At the very start of the function body, insert these two lazy imports:
    #   import app.services.scanner as _scanner_mod
    #   from app.services.scanner import ScannerService
    # (Lazy = inside the function body, not at module level. No circular import:
    #  scanner.py imports pre_market_scan.py lazily too, so no load-time cycle.)
    # Apply these substitutions throughout the body:
    #   load_ranker_config(db)    → _scanner_mod.load_ranker_config(db)
    #   get_volume_forecast(...)  → _scanner_mod.get_volume_forecast(...)
    # Keep unchanged — routing through ScannerService is required for patch.object seams:
    #   ScannerService._get_batch_enrichment_data(...)  — do NOT replace
    #   ScannerService.calculate_day_metrics(...)       — do NOT replace
    #   ScannerService._save_event(db=db, ...)          — do NOT replace
    # compute_anomaly_score is imported at module level above — call it directly (no change).
    ...
```

**Update the `_run` adapter** in the same file to call the local function directly instead of routing through `ScannerService`:

```python
# Replace the existing _run function in pre_market_scan.py
async def _run(
    tickers: list[str], db: Any, event_date: date, scanner_run: Optional[Any] = None
) -> list[dict]:
    return await run_pre_market_scan(
        tickers, db, event_date=event_date, scanner_run=scanner_run
    )
```

**3d. Verify the test passes**
```bash
docker-compose exec backend python -m pytest backend/tests/services/test_pre_market_scan_module.py -x -q
# Expected: 1 passed
```

**3e. Commit**
```bash
git add backend/app/services/pre_market_scan.py backend/tests/services/test_pre_market_scan_module.py
git commit -m "refactor(scanner): move run_pre_market_scan body into pre_market_scan.py

Function body now lives in the registry file. _run adapter calls the
local function directly. ScannerService.run_pre_market_scan will become
a lazy-import shim in Task 5.

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
```

---

### Task 4 — Extend `oversold_bounce_scan.py` with `run_oversold_bounce_scan`

**Files:** `backend/app/services/oversold_bounce_scan.py` (extend)

**4a. Write the failing test**
```python
# backend/tests/services/test_oversold_bounce_scan_module.py
def test_run_oversold_bounce_scan_importable_from_module():
    from app.services.oversold_bounce_scan import run_oversold_bounce_scan
    assert callable(run_oversold_bounce_scan)
```

**4b. Verify it fails**
```bash
docker-compose exec backend python -m pytest backend/tests/services/test_oversold_bounce_scan_module.py -x 2>&1 | tail -5
# Expected: ImportError: cannot import name 'run_oversold_bounce_scan'
```

**4c. Add `run_oversold_bounce_scan` to `oversold_bounce_scan.py`**

Add the same imports as Task 3 at the top of `oversold_bounce_scan.py`, then add the function:

```python
# backend/app/services/oversold_bounce_scan.py  — additions
# Use the same import block as pre_market_scan.py (Task 3), including:
#   from sqlalchemy import desc, func
#   from app.services.timeseries_forecast import compute_anomaly_score
# Omit scan_enrichment, session_metrics, signal_ranker, get_volume_forecast — same reasons as Task 3.

async def run_oversold_bounce_scan(
    tickers: List[str],
    db: Session,
    event_date: date = None,
    scanner_run: Optional["ScannerRun"] = None,
) -> List[Dict[str, Any]]:
    """Run the Oversold Bounce (Dual RSI) scan using DB daily aggregates."""
    # [PASTE verbatim body from scanner.py lines 826–1017]
    # Apply the same substitution pattern as Task 3.
    # At the very start of the function body, insert these two lazy imports:
    #   import app.services.scanner as _scanner_mod
    #   from app.services.scanner import ScannerService
    # Apply these substitutions throughout the body:
    #   load_ranker_config(db)    → _scanner_mod.load_ranker_config(db)
    # Keep unchanged — routing through ScannerService is required for patch.object seams:
    #   ScannerService._get_batch_enrichment_data(...)  — do NOT replace
    #   ScannerService.calculate_day_metrics(...)       — do NOT replace
    #   ScannerService._save_event(db=db, ...)          — do NOT replace
    # (Note: get_volume_forecast is not called in this scan body — no _scanner_mod.gvf needed here.)
    ...
```

**Update the `_run` adapter:**
```python
async def _run(
    tickers: list[str], db: Any, event_date: date, scanner_run: Optional[Any] = None
) -> list[dict]:
    return await run_oversold_bounce_scan(
        tickers, db, event_date=event_date, scanner_run=scanner_run
    )
```

**4d. Verify the test passes**
```bash
docker-compose exec backend python -m pytest backend/tests/services/test_oversold_bounce_scan_module.py -x -q
# Expected: 1 passed
```

**4e. Commit**
```bash
git add backend/app/services/oversold_bounce_scan.py backend/tests/services/test_oversold_bounce_scan_module.py
git commit -m "refactor(scanner): move run_oversold_bounce_scan body into oversold_bounce_scan.py

Matches the pre_market_scan.py pattern. _run adapter now calls the
local function directly.

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
```

---

### Task 5 — Reduce `scanner.py` to a thin delegation facade

**Files:** `backend/app/services/scanner.py` (reduce)

This is the final step for PR 1. Replace every extracted method body with a delegation call, slim the import block, and confirm the line count.

**5a. Confirm baseline green before editing**
```bash
docker-compose exec backend python -m pytest backend/tests/services/test_scanner_service_methods.py backend/tests/services/test_scanner_refactor.py backend/tests/services/test_feature_enrichment.py -q
# Expected: all passed (current scanner.py still has full bodies)
```

**5b. Replace `scanner.py` with the thin facade**

The new file keeps the same class name and every static method signature. Remove `_SECTOR_ETF_MAP`, `_SECTOR_ETF_SYMBOLS`, `_ET`, `pandas`, `desc`, `func`, `scan_duration_seconds`, `scanner_events_total`, `StockSplit`, `StockAggregate`, `SystemConfig`, `TickerReference`, `CatalystParser`, and `time as _time` from the import block.

**Keep** `load_ranker_config`, `compute_anomaly_score`, and `get_volume_forecast` — these are required as patch targets: `test_scanner_refactor.py` patches `"app.services.scanner.load_ranker_config"` and `"app.services.scanner.get_volume_forecast"` by module attribute name. Those names must remain in the `scanner.py` namespace even though the run bodies moved. The run bodies in `pre_market_scan.py`/`oversold_bounce_scan.py` access these via `_scanner_mod.load_ranker_config` etc. so the patches intercept them.

**New import block for `scanner.py`:**
```python
# backend/app/services/scanner.py  — reduced facade
"""
Scanner Service — public facade.

All heavy logic lives in focused sibling modules:
  session_metrics.py  — calculate_day_metrics_*
  scan_enrichment.py  — _get_batch_enrichment_data_*
  pre_market_scan.py  — run_pre_market_scan (body)
  oversold_bounce_scan.py — run_oversold_bounce_scan (body)
"""
from datetime import date, timedelta
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Tuple

from sqlalchemy.orm import Session

from app.models.monitored_stock import MonitoredStock
from app.services.session_metrics import (
    calculate_day_metrics as _calc_metrics,
    calculate_day_metrics_from_aggs as _calc_metrics_from_aggs,
)
from app.services.scan_enrichment import (
    _get_batch_enrichment_data as _enrich,
    _get_batch_enrichment_data_impl as _enrich_impl,
)
from app.services.signal_ranker import load_ranker_config  # noqa: F401 — test patch target
from app.services.timeseries_forecast import compute_anomaly_score, get_volume_forecast  # noqa: F401 — test patch target
from app.utils.session import get_market_today

if TYPE_CHECKING:
    from app.models.scanner_run import ScannerRun
```

> **Why keep `load_ranker_config` / `get_volume_forecast` / `compute_anomaly_score` on the facade?** `test_scanner_refactor.py` patches them as `patch("app.services.scanner.load_ranker_config", ...)` and `patch("app.services.scanner.get_volume_forecast", ...)`. Those patches replace the attribute on the `scanner` module object. The run bodies (in `pre_market_scan.py`) access them via `import app.services.scanner as _scanner_mod; _scanner_mod.load_ranker_config(...)` — which reads the (now-patched) attribute from the scanner module at call time. If these names were removed from scanner.py, the patch would set them on a module that nothing reads — the test would silently use the real implementation and fail.

**New `ScannerService` class body — delegation shims only:**
```python
class ScannerService:
    """Thin facade — delegates to focused submodules. Public API unchanged."""

    # ------------------------------------------------------------------ #
    #  Session metrics (→ session_metrics.py)                             #
    # ------------------------------------------------------------------ #

    @staticmethod
    def calculate_day_metrics_from_aggs(aggs: List) -> Dict[str, Any]:
        return _calc_metrics_from_aggs(aggs)

    @staticmethod
    def calculate_day_metrics(ticker: str, event_date: date, db: Session) -> Dict[str, Any]:
        return _calc_metrics(ticker, event_date, db)

    # ------------------------------------------------------------------ #
    #  Utility helpers (stay on facade — small, heavily referenced)       #
    # ------------------------------------------------------------------ #

    @staticmethod
    def default_scan_date() -> date:
        """Most recent completed trading weekday."""
        from datetime import timedelta as _td
        d = get_market_today() - _td(days=1)
        while d.weekday() >= 5:
            d -= _td(days=1)
        return d

    @staticmethod
    def check_concurrency(redis_url: str, universe_id: int, scanner_type: str) -> Optional[dict]:
        import json
        import redis as _redis
        r = _redis.Redis.from_url(redis_url, decode_responses=True)
        state_key = f"universe:{universe_id}:scan:{scanner_type}"
        existing = r.get(state_key)
        if existing:
            try:
                return json.loads(existing)
            except json.JSONDecodeError:
                r.delete(state_key)
        return None

    @staticmethod
    def resolve_date_range(
        start_date: Optional[date], end_date: Optional[date]
    ) -> tuple:
        resolved_start = start_date or ScannerService.default_scan_date()
        resolved_end = end_date or resolved_start
        if resolved_end < resolved_start:
            raise ValueError("end_date must not be before start_date")
        return resolved_start, resolved_end

    @staticmethod
    def count_active_tickers(db: Session, universe_id: int) -> int:
        return (
            db.query(MonitoredStock)
            .filter(
                MonitoredStock.universe_id == universe_id,
                MonitoredStock.is_active.is_(True),
            )
            .count()
        )

    # ------------------------------------------------------------------ #
    #  Batch enrichment (→ scan_enrichment.py)                            #
    # ------------------------------------------------------------------ #

    @staticmethod
    def _get_batch_enrichment_data(
        tickers: List[str], event_date: date, db: Session
    ) -> Tuple:
        return _enrich(tickers, event_date, db)

    @staticmethod
    def _get_batch_enrichment_data_impl(
        tickers: List[str], event_date: date, db: Session
    ) -> Tuple:
        return _enrich_impl(tickers, event_date, db)

    # ------------------------------------------------------------------ #
    #  _save_event stays here (thin wrapper, stay on facade)              #
    # ------------------------------------------------------------------ #

    @staticmethod
    def _save_event(
        db: Session,
        ticker: str,
        event_date: date,
        scanner_type: str,
        indicators: Dict[str, Any],
        criteria_met: Dict[str, Any],
        enrichment: Dict[str, Any],
        previous_close: float = None,
        opening_price: float = None,
        closing_price: float = None,
        ranker_config: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        from app.services.alert_service import save_event
        return save_event(
            db=db, ticker=ticker, event_date=event_date, scanner_type=scanner_type,
            indicators=indicators, criteria_met=criteria_met, enrichment=enrichment,
            previous_close=previous_close, opening_price=opening_price,
            closing_price=closing_price, ranker_config=ranker_config,
        )

    # ------------------------------------------------------------------ #
    #  Scan runners — lazy import shims (avoid load-time cycle)           #
    # ------------------------------------------------------------------ #

    @staticmethod
    async def run_pre_market_scan(
        tickers: List[str],
        db: Session,
        event_date: date = None,
        scanner_run: Optional["ScannerRun"] = None,
    ) -> List[Dict[str, Any]]:
        from app.services.pre_market_scan import run_pre_market_scan as _impl
        return await _impl(tickers, db, event_date=event_date, scanner_run=scanner_run)

    @staticmethod
    async def run_oversold_bounce_scan(
        tickers: List[str],
        db: Session,
        event_date: date = None,
        scanner_run: Optional["ScannerRun"] = None,
    ) -> List[Dict[str, Any]]:
        from app.services.oversold_bounce_scan import run_oversold_bounce_scan as _impl
        return await _impl(tickers, db, event_date=event_date, scanner_run=scanner_run)

    # ------------------------------------------------------------------ #
    #  Date convenience wrappers (stay on facade — tiny, named callers)   #
    # ------------------------------------------------------------------ #

    @staticmethod
    async def run_pre_market_scan_for_date(
        ticker: str, event_date: date, db: Session
    ) -> List[Dict[str, Any]]:
        return await ScannerService.run_pre_market_scan([ticker], db, event_date=event_date)

    @staticmethod
    async def run_oversold_bounce_scan_for_date(
        ticker: str, event_date: date, db: Session
    ) -> List[Dict[str, Any]]:
        return await ScannerService.run_oversold_bounce_scan([ticker], db, event_date=event_date)
```

**5c. Verify line count**
```bash
wc -l backend/app/services/scanner.py
# Expected: ≤300 lines
```

**5d. Run full scanner test suite**
```bash
docker-compose exec backend python -m pytest \
  backend/tests/services/test_scanner_service_methods.py \
  backend/tests/services/test_scanner_refactor.py \
  backend/tests/services/test_feature_enrichment.py \
  backend/tests/services/test_session_metrics.py \
  backend/tests/services/test_scan_enrichment.py \
  -v 2>&1 | tail -20
# Expected: all passed
```

**5e. Commit**
```bash
git add backend/app/services/scanner.py
git commit -m "refactor(scanner): reduce scanner.py to thin delegation facade (~280 lines)

Every extracted method delegates to session_metrics.py or scan_enrichment.py
via top-level imports. Scan runners use lazy function-body imports to avoid
the load-time cycle through scan_orchestrator. All 5 import sites unchanged.

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
```

---

### Task 6 — Verify PR 1 and open the pull request

**6a. Run the full backend test suite**
```bash
docker-compose exec backend python -m pytest backend/tests/ -q --tb=short 2>&1 | tail -20
# Expected: all passed, 0 failures
```

**6b. Confirm final line counts**
```bash
wc -l \
  backend/app/services/scanner.py \
  backend/app/services/session_metrics.py \
  backend/app/services/scan_enrichment.py \
  backend/app/services/pre_market_scan.py \
  backend/app/services/oversold_bounce_scan.py
# Expected:
#   scanner.py:            ≤300
#   session_metrics.py:    ~135
#   scan_enrichment.py:    ~185
#   pre_market_scan.py:    ~400
#   oversold_bounce_scan.py: ~235
```

**6c. Confirm no import site changed**
```bash
grep -rn "from app.services.scanner import\|from app.services import ScannerService" \
  backend/ --include="*.py" | grep -v "__pycache__" | grep -v "scanner.py"
# Expected: same 5 lines as before (scan_orchestrator, __init__, tasks/scanning, pre_market_scan, oversold_bounce_scan)
# (Note: pre_market_scan and oversold_bounce_scan no longer import ScannerService — confirm they're gone)
```

**6d. Push and open PR 1**
```bash
git push origin HEAD
gh pr create \
  --title "refactor(scanner): decompose scanner.py god module (#199 PR 1/2)" \
  --body "$(cat <<'EOF'
## Summary
- Extracts `session_metrics.py` (~135 lines) — `calculate_day_metrics_from_aggs` + `calculate_day_metrics`
- Extracts `scan_enrichment.py` (~185 lines) — `_SECTOR_ETF_MAP` + batch enrichment functions
- Moves `run_pre_market_scan` body into `pre_market_scan.py`; `_run` adapter calls it directly
- Moves `run_oversold_bounce_scan` body into `oversold_bounce_scan.py`; same pattern
- Reduces `scanner.py` from 1,033 → ~280 lines as a thin delegation facade

**Zero import sites changed.** All 5 callers reference only `ScannerService`, which is preserved. All 3 test files pass unchanged.

## Test plan
- [ ] `pytest backend/tests/services/test_scanner_service_methods.py` — all pass
- [ ] `pytest backend/tests/services/test_scanner_refactor.py` — all pass
- [ ] `pytest backend/tests/services/test_feature_enrichment.py` — all pass
- [ ] `pytest backend/tests/services/test_session_metrics.py` — all pass
- [ ] `wc -l backend/app/services/scanner.py` shows ≤300

Closes #199 PR 1/2.
EOF
)"
```

---

## PR 2 — Decompose `futures_data.py`

---

### Task 7 — Create `futures_contracts.py`

**Files:** `backend/app/services/futures_contracts.py` (new)

**7a. Write the failing test** (add to `test_futures_decompose.py`)
```python
# backend/tests/services/test_futures_decompose.py
from app.services.futures_contracts import (
    SYMBOL_EXCHANGE_MAP,
    MAX_HISTORY_YEARS,
    _resolve_exchange,
    FuturesContractService,
)


def test_symbol_exchange_map_importable_from_contracts():
    assert SYMBOL_EXCHANGE_MAP["ES"] == "CME"
    assert SYMBOL_EXCHANGE_MAP["GC"] == "COMEX"


def test_resolve_exchange_importable_from_contracts():
    assert _resolve_exchange("ES") == "CME"
    assert _resolve_exchange("NQ") == "CME"


def test_futures_contract_service_callable():
    assert callable(FuturesContractService.sync_contracts)
```

**7b. Verify it fails**
```bash
docker-compose exec backend python -m pytest backend/tests/services/test_futures_decompose.py -x 2>&1 | tail -5
# Expected: ModuleNotFoundError: No module named 'app.services.futures_contracts'
```

**7c. Create `futures_contracts.py`**

Move `SYMBOL_EXCHANGE_MAP`, `_resolve_exchange`, `MAX_HISTORY_YEARS`, `_sync_contract_catalog`, and `sync_contracts` verbatim from `futures_data.py`:

```python
# backend/app/services/futures_contracts.py
"""Contract catalog management — extracted from FuturesDataService."""
import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List

from sqlalchemy.orm import Session

from app.core.database import SessionLocal
from app.exceptions import ProviderError
from app.models.futures_contract import FuturesContract
from app.providers import DataProviderFactory

logger = logging.getLogger(__name__)

MAX_HISTORY_YEARS = 10

SYMBOL_EXCHANGE_MAP = {
    "ES": "CME",
    "NQ": "CME",
    "MES": "CME",
    "MNQ": "CME",
    "RTY": "CME",
    "GC": "COMEX",
    "SI": "COMEX",
    "CL": "NYMEX",
    "NG": "NYMEX",
    "ZB": "CBOT",
    "ZN": "CBOT",
    "ZF": "CBOT",
}


def _resolve_exchange(symbol: str) -> str:
    """Return the exchange for a known futures symbol, raising ValueError if unknown."""
    exchange = SYMBOL_EXCHANGE_MAP.get(symbol.upper())
    if not exchange:
        raise ValueError(
            f"Unknown futures symbol '{symbol}'. Add it to SYMBOL_EXCHANGE_MAP."
        )
    return exchange


class FuturesContractService:
    """Contract catalog sync — extracted from FuturesDataService."""

    @staticmethod
    async def _sync_contract_catalog(
        db: Session, symbol: str, exchange: str
    ) -> List[Dict[str, Any]]:
        # [PASTE verbatim body from futures_data.py lines 100–185]
        ...

    @staticmethod
    async def sync_contracts(symbol: str) -> List[Dict[str, Any]]:
        # [PASTE verbatim body from futures_data.py lines 192–206]
        # Replace internal reference: FuturesDataService._sync_contract_catalog(...)
        #   → FuturesContractService._sync_contract_catalog(...)
        exchange = _resolve_exchange(symbol.upper())
        db = SessionLocal()
        try:
            return await FuturesContractService._sync_contract_catalog(
                db, symbol.upper(), exchange
            )
        finally:
            db.close()
```

**7d. Verify test passes**
```bash
docker-compose exec backend python -m pytest backend/tests/services/test_futures_decompose.py -x -q
# Expected: 3 passed
```

**7e. Confirm existing futures tests still green**
```bash
docker-compose exec backend python -m pytest backend/tests/services/test_futures_data_service.py -q
# Expected: all passed (futures_data.py unchanged so far)
```

**7f. Commit**
```bash
git add backend/app/services/futures_contracts.py backend/tests/services/test_futures_decompose.py
git commit -m "refactor(futures): extract futures_contracts.py

Move SYMBOL_EXCHANGE_MAP, _resolve_exchange, MAX_HISTORY_YEARS,
FuturesContractService._sync_contract_catalog, and sync_contracts
into focused contract module. Facade re-export added in Task 11.

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
```

---

### Task 8 — Create `futures_aggregates.py`

**Files:** `backend/app/services/futures_aggregates.py` (new)

**8a. Write the failing test** (add to `test_futures_decompose.py`)
```python
from app.services.futures_aggregates import FuturesAggregatesService

def test_futures_aggregates_service_callable():
    assert callable(FuturesAggregatesService._download_contract)
    assert callable(FuturesAggregatesService._download_full_history)
    assert callable(FuturesAggregatesService._fill_data_gaps)
```

**8b. Verify it fails**
```bash
docker-compose exec backend python -m pytest backend/tests/services/test_futures_decompose.py::test_futures_aggregates_service_callable -x 2>&1 | tail -5
# Expected: ModuleNotFoundError: No module named 'app.services.futures_aggregates'
```

**8c. Create `futures_aggregates.py`**

Move `_download_contract`, `_download_full_history`, `_fill_data_gaps` from `futures_data.py` (lines 239–761, extract by symbol name not line numbers). Two of the three methods contain internal `FuturesDataService.X` calls that must be rewritten before the paste — see substitution table below.

**Import block for `futures_aggregates.py`** — needs cross-module service imports because `_download_full_history` calls into `futures_contracts` and `futures_rollovers`:

```python
# backend/app/services/futures_aggregates.py
"""Futures bar download and gap-fill — extracted from FuturesDataService."""
import logging
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.database import SessionLocal
from app.exceptions import ProviderError
from app.models.futures_aggregate import FuturesAggregate
from app.models.futures_contract import FuturesContract
from app.providers import DataProviderFactory
from app.services.futures_contracts import MAX_HISTORY_YEARS, FuturesContractService
from app.services.futures_rollovers import FuturesRolloversService

logger = logging.getLogger(__name__)
```

**`FuturesDataService.X` substitution table** — replace every occurrence in the pasted bodies before committing:

| Original call (in futures_data.py) | Replacement in futures_aggregates.py | Location |
|---|---|---|
| `FuturesDataService._sync_contract_catalog(db, symbol, exchange)` | `FuturesContractService._sync_contract_catalog(db, symbol, exchange)` | `_download_full_history` line ~485 |
| `FuturesDataService._download_contract(db=db, ...)` | `FuturesAggregatesService._download_contract(db=db, ...)` | `_download_full_history` line ~557 |
| `FuturesDataService._detect_rollovers(db=db, ...)` | `FuturesRolloversService._detect_rollovers(db=db, ...)` | `_download_full_history` line ~575 |
| `FuturesDataService._fill_data_gaps(db=db, ...)` | `FuturesAggregatesService._fill_data_gaps(db=db, ...)` | `_download_full_history` line ~585 |
| `FuturesDataService._download_contract(db=db, ...)` | `FuturesAggregatesService._download_contract(db=db, ...)` | `_fill_data_gaps` line ~726 |

**`_download_contract`** — no `FuturesDataService.X` references; paste verbatim.

```python
class FuturesAggregatesService:
    """Bar download and gap-fill — extracted from FuturesDataService."""

    @staticmethod
    async def _download_contract(
        db: Session, symbol: str, exchange: str, contract_month: str,
        timespan: str = "day", multiplier: int = 1,
        force_refresh: bool = False, from_date: Optional[str] = None,
        to_date: Optional[str] = None,
    ) -> Dict[str, Any]:
        # [PASTE verbatim body from futures_data.py _download_contract — no substitutions needed]
        ...

    @staticmethod
    async def _download_full_history(
        db: Session, symbol: str, exchange: str,
        timespan: str = "day", multiplier: int = 1,
        force_refresh: bool = False, from_date: Optional[str] = None,
        to_date: Optional[str] = None, progress_callback=None,
    ) -> Dict[str, Any]:
        # [PASTE body from futures_data.py _download_full_history]
        # Apply substitution table above — 4 replacements required
        ...

    @staticmethod
    async def _fill_data_gaps(
        db: Session, symbol: str, exchange: str,
        timespan: str = "minute", multiplier: int = 1,
        from_date: Optional[str] = None, to_date: Optional[str] = None,
        min_gap_hours: int = 80,
    ) -> Dict[str, Any]:
        # [PASTE body from futures_data.py _fill_data_gaps]
        # Apply substitution table above — 1 replacement required
        ...
```

**Note on line count:** `futures_aggregates.py` will be ~525 lines — this exceeds the spec's general ≤300 target for extracted modules. The spec explicitly flags this as an open question and accepts it for v1; `_download_contract` (~213 lines) could be further split in a follow-up if a subsequent audit flags it.

**8d. Verify test passes**
```bash
docker-compose exec backend python -m pytest backend/tests/services/test_futures_decompose.py -x -q
# Expected: all current tests pass
```

**8e. Commit**
```bash
git add backend/app/services/futures_aggregates.py
git commit -m "refactor(futures): extract futures_aggregates.py

Move _download_contract, _download_full_history, _fill_data_gaps (~520
lines) into FuturesAggregatesService. Imports MAX_HISTORY_YEARS from
futures_contracts.

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
```

---

### Task 9 — Create `futures_rollovers.py`

**Files:** `backend/app/services/futures_rollovers.py` (new)

**9a. Write the failing test** (add to `test_futures_decompose.py`)
```python
from app.services.futures_rollovers import (
    FuturesRolloversService,
    _detect_single_rollover,
    _build_time_slices,
)

def test_futures_rollovers_service_callable():
    assert callable(FuturesRolloversService._detect_rollovers)
    assert callable(_detect_single_rollover)
    assert callable(_build_time_slices)

def test_build_time_slices_empty_rollovers():
    result = _build_time_slices(rollovers=[], first_contract="20250321")
    assert result == [(None, None, "20250321")]
```

**9b. Verify it fails**
```bash
docker-compose exec backend python -m pytest backend/tests/services/test_futures_decompose.py -k "rollover" -x 2>&1 | tail -5
# Expected: ModuleNotFoundError: No module named 'app.services.futures_rollovers'
```

**9c. Create `futures_rollovers.py`**

Move `_detect_rollovers` (class method), `_detect_single_rollover` and `_build_time_slices` (module-level) verbatim from `futures_data.py`:

```python
# backend/app/services/futures_rollovers.py
"""Rollover detection — extracted from FuturesDataService."""
import logging
from datetime import date, datetime, timedelta
from typing import List, Optional, Tuple

import pandas as pd
from sqlalchemy.orm import Session

from app.models.futures_aggregate import FuturesAggregate
from app.models.futures_contract import FuturesContract
from app.models.futures_rollover import FuturesRollover

logger = logging.getLogger(__name__)

CALENDAR_ROLL_DAYS_BEFORE_EXPIRY = 8


class FuturesRolloversService:
    """Rollover detection — extracted from FuturesDataService."""

    @staticmethod
    async def _detect_rollovers(
        db: Session, symbol: str, exchange: str,
        timespan: str = "day", multiplier: int = 1,
    ) -> int:
        # [PASTE verbatim body from futures_data.py lines 763–847]
        # _detect_single_rollover is a module-level function in this same file
        ...


def _detect_single_rollover(
    db: Session, symbol: str, exchange: str, current_month: str,
    next_month: str, current_expiry: Optional[date], timespan: str, multiplier: int,
) -> Optional[Tuple[date, str]]:
    # [PASTE verbatim body from futures_data.py lines 975–1056]
    # CALENDAR_ROLL_DAYS_BEFORE_EXPIRY is defined above in this same file
    ...


def _build_time_slices(
    rollovers: List[FuturesRollover], first_contract: str
) -> List[Tuple[Optional[datetime], Optional[datetime], str]]:
    # [PASTE verbatim body from futures_data.py lines 1059–1086]
    ...
```

**9d. Verify tests pass**
```bash
docker-compose exec backend python -m pytest backend/tests/services/test_futures_decompose.py -x -q
# Expected: all tests pass including _build_time_slices empty-rollovers check
```

**9e. Commit**
```bash
git add backend/app/services/futures_rollovers.py
git commit -m "refactor(futures): extract futures_rollovers.py

Move FuturesRolloversService._detect_rollovers, _detect_single_rollover,
and _build_time_slices into focused rollover module.
CALENDAR_ROLL_DAYS_BEFORE_EXPIRY constant co-located with its callers.

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
```

---

### Task 10 — Create `futures_series.py`

**Files:** `backend/app/services/futures_series.py` (new)

**10a. Write the failing test** (add to `test_futures_decompose.py`)
```python
from app.services.futures_series import FutureSeriesService

def test_future_series_service_callable():
    assert callable(FutureSeriesService.get_continuous_series)
    assert callable(FutureSeriesService._get_continuous_series_with_db)
```

**10b. Verify it fails**
```bash
docker-compose exec backend python -m pytest backend/tests/services/test_futures_decompose.py -k "series" -x 2>&1 | tail -5
# Expected: ModuleNotFoundError
```

**10c. Create `futures_series.py`**

Move `get_continuous_series` and `_get_continuous_series_with_db` verbatim from `futures_data.py` lines 208–967. Import `_build_time_slices` from `futures_rollovers`:

```python
# backend/app/services/futures_series.py
"""Continuous futures series assembly — extracted from FuturesDataService."""
import logging
from datetime import datetime
from typing import Optional

import pandas as pd
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.database import SessionLocal
from app.models.futures_contract import FuturesContract
from app.models.futures_rollover import FuturesRollover
from app.services.futures_rollovers import _build_time_slices

logger = logging.getLogger(__name__)


class FutureSeriesService:
    """Continuous series assembly — extracted from FuturesDataService."""

    @staticmethod
    def get_continuous_series(
        symbol: str, timespan: str = "day", multiplier: int = 1,
        from_date: Optional[str] = None, to_date: Optional[str] = None,
    ) -> pd.DataFrame:
        # [PASTE verbatim body from futures_data.py lines 209–233]
        # Replace internal reference: FuturesDataService._get_continuous_series_with_db(...)
        #   → FutureSeriesService._get_continuous_series_with_db(...)
        db = SessionLocal()
        try:
            return FutureSeriesService._get_continuous_series_with_db(
                db=db, symbol=symbol, timespan=timespan,
                multiplier=multiplier, from_date=from_date, to_date=to_date,
            )
        finally:
            db.close()

    @staticmethod
    def _get_continuous_series_with_db(
        db: Session, symbol: str, timespan: str = "day",
        multiplier: int = 1, from_date: Optional[str] = None,
        to_date: Optional[str] = None,
    ) -> pd.DataFrame:
        # [PASTE verbatim body from futures_data.py lines 854–967]
        # _build_time_slices is imported from futures_rollovers at module level
        ...
```

**10d. Verify tests pass**
```bash
docker-compose exec backend python -m pytest backend/tests/services/test_futures_decompose.py -x -q
# Expected: all tests pass
```

**10e. Commit**
```bash
git add backend/app/services/futures_series.py
git commit -m "refactor(futures): extract futures_series.py

Move FutureSeriesService.get_continuous_series and
_get_continuous_series_with_db into focused series module.
Imports _build_time_slices from futures_rollovers.

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
```

---

### Task 11 — Reduce `futures_data.py` to an explicit-delegation facade

**Files:** `backend/app/services/futures_data.py` (reduce)

**11a. Confirm baseline green**
```bash
docker-compose exec backend python -m pytest backend/tests/services/test_futures_data_service.py -q
# Expected: all passed (futures_data.py still has full bodies)
```

**11b. Replace `futures_data.py` with the explicit-delegation facade**

The new file is ~95 lines. All three symbols that 9 import sites reference (`FuturesDataService`, `SYMBOL_EXCHANGE_MAP`, `_resolve_exchange`) remain importable from this module:

```python
# backend/app/services/futures_data.py
"""
Futures Data Service — backward-compatibility facade.

All implementation lives in focused sibling modules:
  futures_contracts.py  — SYMBOL_EXCHANGE_MAP, _resolve_exchange, FuturesContractService
  futures_aggregates.py — FuturesAggregatesService (download + gap-fill)
  futures_rollovers.py  — FuturesRolloversService, _detect_single_rollover, _build_time_slices
  futures_series.py     — FutureSeriesService (continuous series assembly)

All 9 import sites referencing FuturesDataService, SYMBOL_EXCHANGE_MAP, or
_resolve_exchange continue to work without modification.
"""
from app.core.database import SessionLocal  # retained: test patch target
from app.services.futures_contracts import (
    SYMBOL_EXCHANGE_MAP,
    _resolve_exchange,
    FuturesContractService,
)
from app.services.futures_aggregates import FuturesAggregatesService
from app.services.futures_rollovers import FuturesRolloversService
from app.services.futures_series import FutureSeriesService


class FuturesDataService:
    """Backward-compatibility facade — explicit delegation to focused subservices."""

    # Private methods use staticmethod() class-attribute assignments (no session mgmt).
    # sync_contracts and get_continuous_series are explicit method bodies so that
    # patch("app.services.futures_data.SessionLocal", ...) intercepts their SessionLocal
    # calls. If they were staticmethod() delegations, SessionLocal would be called from
    # futures_contracts.py / futures_series.py namespaces — outside the patched module.

    # Contracts
    _sync_contract_catalog = staticmethod(FuturesContractService._sync_contract_catalog)

    @staticmethod
    async def sync_contracts(symbol: str):
        """Sync contract catalog. SessionLocal called from this module's namespace
        so patch("app.services.futures_data.SessionLocal", ...) intercepts it."""
        exchange = _resolve_exchange(symbol.upper())
        db = SessionLocal()
        try:
            return await FuturesContractService._sync_contract_catalog(
                db, symbol.upper(), exchange
            )
        finally:
            db.close()

    # Series (public interface first — most callers use this)
    @staticmethod
    def get_continuous_series(
        symbol: str,
        timespan: str = "day",
        multiplier: int = 1,
        from_date=None,
        to_date=None,
    ):
        """Assemble continuous series. SessionLocal called from this module's namespace
        so patch("app.services.futures_data.SessionLocal", ...) intercepts it."""
        db = SessionLocal()
        try:
            return FutureSeriesService._get_continuous_series_with_db(
                db=db,
                symbol=symbol,
                timespan=timespan,
                multiplier=multiplier,
                from_date=from_date,
                to_date=to_date,
            )
        finally:
            db.close()

    _get_continuous_series_with_db = staticmethod(FutureSeriesService._get_continuous_series_with_db)

    # Aggregates
    _download_contract = staticmethod(FuturesAggregatesService._download_contract)
    _download_full_history = staticmethod(FuturesAggregatesService._download_full_history)
    _fill_data_gaps = staticmethod(FuturesAggregatesService._fill_data_gaps)

    # Rollovers
    _detect_rollovers = staticmethod(FuturesRolloversService._detect_rollovers)
```

> **Why explicit method bodies for `sync_contracts` and `get_continuous_series`?** `test_futures_data_service.py` (lines 109, 118) and `test_futures.py` (lines 113, 131, 145) all patch `"app.services.futures_data.SessionLocal"`. That patch replaces the `SessionLocal` attribute on the `futures_data` module object. The explicit method bodies call `SessionLocal()` from the facade's own `futures_data.py` namespace — so the patch intercepts them. If these were `staticmethod(FuturesContractService.sync_contracts)` delegations, `SessionLocal` would be called from `futures_contracts.py`'s namespace (unpatchable). The private methods have no `SessionLocal` call in their signatures, so `staticmethod()` assignments are fine for them.

**11c. Verify line count**
```bash
wc -l backend/app/services/futures_data.py
# Expected: ~95 lines (sync_contracts + get_continuous_series have explicit bodies)
```

**11d. Run full futures test suite**
```bash
docker-compose exec backend python -m pytest backend/tests/services/test_futures_data_service.py -v 2>&1 | tail -20
# Expected: all passed — FuturesDataService.method calls route through the facade
```

**11e. Confirm all 9 import sites still resolve**
```bash
grep -rn "from app.services.futures_data import\|from app.services import.*FuturesDataService" \
  backend/ --include="*.py" | grep -v "__pycache__" | grep -v "futures_data.py"
# Expected: same 9 lines as before, unchanged
```

**11f. Commit**
```bash
git add backend/app/services/futures_data.py
git commit -m "refactor(futures): reduce futures_data.py to explicit-delegation facade (~70 lines)

FuturesDataService delegates every method via class-attribute assignment
to focused subservice classes. All three public symbols (FuturesDataService,
SYMBOL_EXCHANGE_MAP, _resolve_exchange) remain importable from this module,
preserving all 9 import sites unchanged.

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
```

---

### Task 12 — Verify PR 2 and open the pull request

**12a. Run the full backend test suite**
```bash
docker-compose exec backend python -m pytest backend/tests/ -q --tb=short 2>&1 | tail -20
# Expected: all passed, 0 failures
```

**12b. Confirm final line counts**
```bash
wc -l \
  backend/app/services/futures_data.py \
  backend/app/services/futures_contracts.py \
  backend/app/services/futures_aggregates.py \
  backend/app/services/futures_rollovers.py \
  backend/app/services/futures_series.py
# Expected:
#   futures_data.py:      ~95 lines
#   futures_contracts.py: ~130 lines
#   futures_aggregates.py: ~525 lines (within spec; open question logged in spec)
#   futures_rollovers.py:  ~170 lines
#   futures_series.py:     ~165 lines
```

**12c. Confirm no import site changed**
```bash
grep -rn "from app.services.futures_data import\|SYMBOL_EXCHANGE_MAP\|_resolve_exchange" \
  backend/ --include="*.py" | grep -v "__pycache__" | grep -v "futures_data.py" | grep -v "futures_contracts.py"
# Expected: same callers as before — all still import from futures_data
```

**12d. Push and open PR 2**
```bash
git push origin HEAD
gh pr create \
  --title "refactor(futures): decompose futures_data.py god module (#199 PR 2/2)" \
  --body "$(cat <<'EOF'
## Summary
- Extracts `futures_contracts.py` (~130 lines) — `SYMBOL_EXCHANGE_MAP`, `_resolve_exchange`, `FuturesContractService`
- Extracts `futures_aggregates.py` (~525 lines) — `FuturesAggregatesService` (download + gap-fill)
- Extracts `futures_rollovers.py` (~170 lines) — `FuturesRolloversService`, `_detect_single_rollover`, `_build_time_slices`
- Extracts `futures_series.py` (~165 lines) — `FutureSeriesService` (continuous series)
- Reduces `futures_data.py` from 1,086 → ~70 lines as an explicit-delegation facade

**Zero import sites changed.** All 9 callers continue importing from `futures_data`; all three public symbols (`FuturesDataService`, `SYMBOL_EXCHANGE_MAP`, `_resolve_exchange`) remain importable there. No subpackages introduced — all files are flat siblings in `app/services/`.

Explicit class-attribute delegation (`FuturesDataService.method = SubService.method`) chosen over multiple inheritance per spec recommendation — avoids MRO complexity and keeps `FuturesDataService.<method>` calls working without surprise.

## Test plan
- [ ] `pytest backend/tests/services/test_futures_data_service.py` — all pass
- [ ] `pytest backend/tests/services/test_futures_decompose.py` — all pass
- [ ] `pytest backend/tests/` — 0 failures
- [ ] `wc -l backend/app/services/futures_data.py` shows ~70 lines

Closes #199 PR 2/2.
EOF
)"
```

---

## Quick Reference — All New Files

| Module | Contains |
|--------|----------|
| `session_metrics.py` | `calculate_day_metrics_from_aggs`, `calculate_day_metrics` |
| `scan_enrichment.py` | `_SECTOR_ETF_MAP`, `_SECTOR_ETF_SYMBOLS`, `_get_batch_enrichment_data[_impl]` |
| `futures_contracts.py` | `SYMBOL_EXCHANGE_MAP`, `_resolve_exchange`, `MAX_HISTORY_YEARS`, `FuturesContractService` |
| `futures_aggregates.py` | `FuturesAggregatesService` (`_download_contract`, `_download_full_history`, `_fill_data_gaps`) |
| `futures_rollovers.py` | `FuturesRolloversService._detect_rollovers`, `_detect_single_rollover`, `_build_time_slices`, `CALENDAR_ROLL_DAYS_BEFORE_EXPIRY` |
| `futures_series.py` | `FutureSeriesService.get_continuous_series`, `FutureSeriesService._get_continuous_series_with_db` |
