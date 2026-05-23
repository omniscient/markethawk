# Extract Business Logic from Scanner, Universe, and Stocks Routers

**Date:** 2026-05-23
**Issue:** #62

## Overview

Business logic has leaked into three FastAPI route handlers — concurrency guards, date defaulting, stats computation, and data enrichment decisions live in routers instead of behind module interfaces. This logic cannot be tested without spinning up HTTP. The goal is to make routers thin HTTP-to-module translators and move all domain logic into the service layer.

## Requirements

1. **Scanner router**: Move the Redis concurrency guard, date range defaulting, and ticker count validation out of `run_scanner()` into static methods on `ScannerService`. The helper `_last_completed_weekday()` moves with them.
2. **Universe router**: Move `_compute_universe_stats()` (all ~95 lines of aggregate computation) into a new `UniverseStatsService.compute(universe_id, db)` in a new `backend/app/services/universe_stats.py` file. Both call sites in the router update to use the service.
3. **Stocks router**: Move `_is_futures_ticker()`, numeric coercion (`pd.to_numeric` loop), and indicator gating (`if timespan in ["minute", "hour"] and len(data) <= INDICATOR_ROW_LIMIT`) into `StockDataService`. The compact dict-building serialization stays in the router (HTTP concern).
4. **No behaviour changes**: All refactoring is pure extraction — identical logic, new location. No new features.
5. **Routers become testable**: After extraction, the three business logic units (scanner submission pre-checks, universe stats, stock data preparation) are exercisable via plain function calls without an HTTP client.

## Architecture / Approach

### Scanner: New static methods on `ScannerService`

Four items move from `routers/scanner.py` into `backend/app/services/scanner.py`:

```python
class ScannerService:
    # existing methods ...

    @staticmethod
    def default_scan_date() -> date:
        """Most recent completed trading weekday."""
        # moves from _last_completed_weekday()

    @staticmethod
    def check_concurrency(redis_url: str, universe_id: int, scanner_type: str) -> Optional[dict]:
        """Returns in-flight scan state dict if one exists, else None.
        The router raises HTTPException(409) when this returns non-None.
        On corrupt Redis key: clears it and returns None (proceed).
        """

    @staticmethod
    def resolve_date_range(
        start_date: Optional[date],
        end_date: Optional[date],
    ) -> tuple[date, date]:
        """Apply date defaults (both bounds → default_scan_date) and validate ordering.
        Raises ValueError if end_date < start_date; router maps this to HTTP 400.
        """

    @staticmethod
    def count_active_tickers(db: Session, universe_id: int) -> int:
        """Count active tickers in a universe. Returns count (may be 0).
        Router raises HTTP 400 when count == 0.
        """
```

The `run_scanner()` route handler becomes ~15 lines: call the four methods, map results to HTTP exceptions, then enqueue the Celery task.

**Rationale:** Issue #60 (Scan Orchestrator) already has `spec-pending-review` and will absorb these methods when it's implemented. Adding them to `ScannerService` now is the migration path the #60 spec expects — it avoids creating a `ScanRunService` that would immediately be dissolved in #60's PR 1.

### Universe: New `UniverseStatsService`

New file `backend/app/services/universe_stats.py`:

```python
class UniverseStatsService:
    @staticmethod
    def compute(universe_id: int, db: Session) -> dict:
        """Aggregate stats for one universe.
        Returns: {ticker_count, aggregate_count, min_date, max_date, timespans: list[str]}
        Queries StockAggregate and FuturesAggregate tables directly.
        No caching — callers are responsible for persisting results to cached columns.
        """
```

Two call sites in `routers/universe.py` change from:
```python
stats = _compute_universe_stats(universe_id, db)
```
to:
```python
from app.services.universe_stats import UniverseStatsService
stats = UniverseStatsService.compute(universe_id, db)
```

The private function `_compute_universe_stats()` is deleted from the router.

### Stocks: Additions to `StockDataService`

Three items move from `routers/stocks.py` into `backend/app/services/stock_data.py`:

**1. Asset class check:**
```python
@staticmethod
def is_futures_ticker(db: Session, ticker: str) -> bool:
    """Return True if ticker is tracked as futures asset class."""
    # moves from _is_futures_ticker() in router
```

**2. Enriched historical fetch** — a new orchestration method:
```python
@staticmethod
def get_historical_enriched(
    db: Session,
    ticker: str,
    period: str,
    timespan: str,
    multiplier: int,
) -> pd.DataFrame:
    """Fetch, coerce, and optionally enrich with indicators.
    - Dispatches to get_historical_from_db or get_futures_historical_from_db
    - Applies pd.to_numeric() coercion (Decimal → float, required by orjson + indicators)
    - Applies INDICATOR_ROW_LIMIT guard and calls ChartIndicatorsService.add_indicators()
    - Returns empty DataFrame on no data
    Router remains responsible for compact serialization.
    """
```

The `get_historical_data()` router endpoint calls `StockDataService.get_historical_enriched()` and then handles only the compact dict-building and `ORJSONResponse` construction.

The private `_is_futures_ticker()` function is deleted from the router. Its three call sites in `get_historical_data()`, `refresh_stock_data()`, and `get_stock_detail_consolidated()` change to `StockDataService.is_futures_ticker(db, ticker)`.

### File changes summary

| File | Change |
|------|--------|
| `backend/app/services/scanner.py` | Add 4 static methods to `ScannerService` |
| `backend/app/services/universe_stats.py` | **New file** — `UniverseStatsService` with `compute()` |
| `backend/app/services/stock_data.py` | Add `is_futures_ticker()` and `get_historical_enriched()` static methods |
| `backend/app/routers/scanner.py` | Remove 4 local functions/blocks; call `ScannerService` methods |
| `backend/app/routers/universe.py` | Remove `_compute_universe_stats()`; call `UniverseStatsService.compute()` |
| `backend/app/routers/stocks.py` | Remove `_is_futures_ticker()`; thin `get_historical_data()` body |

## Alternatives Considered

### Alternative 1 — Inline static methods only (no new files)
Move all extracted logic onto the nearest existing service class. Universe stats would have to go into `stock_data.py` or `discovery_service.py` — both are wrong-domain fits. This works for scanner and stocks but forces an awkward home for the universe stats function. Rejected in favor of a dedicated `UniverseStatsService`.

### Alternative 2 — Single `router_services.py` grab-bag
Collect all extracted logic into one new file. Creates a well-named anti-pattern (a module whose cohesion is "things the router didn't want"). Rejected; per-domain placement is more discoverable.

## Open Questions

- **`_compute_next_run()` in `routers/scanner.py`**: This helper (lines 545-558) computes the next scheduled fire time for a scanner type. It touches scheduling concepts but is small and only used by `get_scan_status_block()`. This issue does not include it in scope; it can be extracted in a later pass or as part of #60.
- **`MAX_DATAPOINTS` guardrail**: Currently in the router. Moving it inside `get_historical_enriched()` treats it as a data-integrity limit (which it is) rather than an HTTP-layer concern. This spec places it in the service; reviewers should confirm this is the intended interpretation.

## Assumptions

- **No migration needed**: All changes are code-only (function moves + new service file). No DB schema changes.
- **Issue #60 is not a blocker**: This spec proceeds without waiting for the Scan Orchestrator. The `ScannerService` static methods added here will become internal methods of the orchestrator when #60 is implemented.
- **`services/__init__.py`**: `UniverseStatsService` will need to be importable. The new file should be importable as `from app.services.universe_stats import UniverseStatsService`; whether it also gets re-exported from `services/__init__.py` follows the existing convention for that file.
- **No test files in scope**: This is a refactor extraction. Tests can be added in a follow-on; the value here is establishing the testable surface.
