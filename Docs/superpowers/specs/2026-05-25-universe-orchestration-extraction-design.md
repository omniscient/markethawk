# Universe Router Orchestration Extraction — Design Spec

**Issue**: [#76 — refactor: extract orchestration logic from oversized routers](https://github.com/omniscient/markethawk/issues/76)
**Date**: 2026-05-25
**Status**: Pending Review

## Overview

`backend/app/routers/universe.py` is 1,006 LOC with 18 endpoints, but roughly 600 of those lines are orchestration logic — Celery task dispatch, Redis state management, multi-service coordination, and data export — inlined directly in route handlers. This makes the module expensive for agents and humans alike: modifying sync logic requires reading the whole router to find it.

This refactor extracts that orchestration into two focused service modules, leaving the router as a thin HTTP adapter (validate → delegate → respond). Scanner.py is a similar but independent problem deferred to a follow-on issue.

## Requirements

1. Extract Celery/Redis coordination logic from `universe.py` into a new `services/universe_orchestrator.py`.
2. Extract data export logic from `universe.py` into a new `services/universe_export.py` (following the existing `universe_stats.py` precedent for single-purpose data services).
3. Add `UniverseNotFoundError` and `UniverseValidationError` to `backend/app/exceptions.py`; service methods raise these instead of `HTTPException`; the router catches and converts them.
4. `routers/universe.py` becomes ~360–380 LOC — thin HTTP adapters only.
5. No change to public API surface: all endpoint paths, request schemas, and response schemas remain identical.
6. Service methods accept a synchronous `Session` parameter (matching the existing sync pattern in `universe.py`; do not migrate to `AsyncSession` in this issue).
7. Validate each affected endpoint with `curl` after extraction per the dev rules in CLAUDE.md.

## Architecture

### New Files

#### `backend/app/services/universe_orchestrator.py` (~485 LOC)

Owns all Celery task dispatch, Redis state read/write, and multi-service coordination for universes.

| Method | Source in router | LOC | What it does |
|--------|-----------------|-----|--------------|
| `discover_and_refresh(universe_id, db)` | `refresh_universe` (L265–343) | ~79 | Clears MonitoredStock + StockUniverseTicker, runs DiscoveryService.run_screen(), bulk-inserts results, refreshes cached stats via UniverseStatsService. |
| `sync_missing_aggregates(universe_id, db)` | `sync_missing_aggregates` (L347–464) | ~118 | Gaps stocks + futures by (timespan, multiplier), queues `sync_stock_aggregates` / `sync_futures_aggregates` Celery tasks, writes Redis `universe:{id}:sync` key (4-hour TTL). |
| `get_sync_status(universe_id)` | `get_universe_sync_status` (L468–523) | ~56 | Reads Redis sync key, inspects `AsyncResult.state` for all task IDs, detects stale keys (>4 h), returns progress dict. |
| `sync_aggregates(universe_id, from_date, to_date, multiplier, timespan, …, db)` | `sync_universe_aggregates` (L683–828) | ~143 | Redis dedup check, queues one Celery task per stock/futures symbol, writes Redis `universe:{id}:sync` key. |
| `queue_quality_analysis(universe_id, db)` | `trigger_quality_analysis` (L831–867) | ~37 | Upserts a pending `UniverseQualityReport` row (clears stale snapshot fields), queues `analyze_universe_quality` task. |
| `queue_normalization(universe_id, request, db)` | `trigger_normalization` (L955–1006) | ~52 | Reads existing quality report, computes resume flag, marks report as pending, queues `normalize_universe_quality` task. |

#### `backend/app/services/universe_export.py` (~139 LOC)

Owns data retrieval and ZIP streaming for universe aggregate exports. Follows the `universe_stats.py` pattern: pure DB queries, no Celery, no Redis.

| Method | Source in router | LOC | What it does |
|--------|-----------------|-----|--------------|
| `export_aggregates(universe_id, request, db)` | `export_universe_aggregates` (L527–665) | ~139 | Queries StockAggregate + FuturesAggregate per requested tickers, formats as CSV, streams a ZIP via `StreamingResponse`. |

### Modified Files

#### `backend/app/exceptions.py`

Add two new exception classes under the existing `MarketHawkError` hierarchy:

```python
class UniverseNotFoundError(MarketHawkError):
    """Raised when a universe_id does not exist in the DB."""
    is_retryable = False

class UniverseValidationError(MarketHawkError):
    """Raised when universe state is invalid for the requested operation."""
    is_retryable = False
```

#### `backend/app/routers/universe.py`

Each extracted route handler becomes a thin shell:

```python
@router.post("/{universe_id}/refresh")
def refresh_universe(universe_id: int, db: Session = Depends(get_db)):
    try:
        return universe_orchestrator.discover_and_refresh(universe_id, db)
    except UniverseNotFoundError:
        raise HTTPException(status_code=404, detail="Universe not found")

@router.post("/{universe_id}/sync-missing")
def sync_missing_aggregates(universe_id: int, db: Session = Depends(get_db)):
    return universe_orchestrator.sync_missing_aggregates(universe_id, db)

@router.get("/{universe_id}/sync-status")
def get_universe_sync_status(universe_id: int):
    return universe_orchestrator.get_sync_status(universe_id)

# … etc.
```

Endpoints that are already thin CRUD (create, update, delete, list, get_universe_stocks, refresh_universe_stats, sync_fundamental_data, sync_ticker_details, stop_sync, sync_daily_metrics, delete_ticker_aggregates, get_quality_report) remain in the router untouched.

### Unchanged

- `backend/app/tasks.py` — all Celery tasks stay in place; the orchestrator calls them the same way the router does today.
- All request/response Pydantic schemas.
- All public endpoint paths.
- `backend/app/services/universe_stats.py` — not modified.

## Extraction Map (LOC accounting)

| Block | Current location | Destination |
|-------|-----------------|-------------|
| `refresh_universe` (~79 LOC) | `routers/universe.py` L265 | `universe_orchestrator.discover_and_refresh` |
| `sync_missing_aggregates` (~118 LOC) | `routers/universe.py` L347 | `universe_orchestrator.sync_missing_aggregates` |
| `get_universe_sync_status` (~56 LOC) | `routers/universe.py` L468 | `universe_orchestrator.get_sync_status` |
| `export_universe_aggregates` (~139 LOC) | `routers/universe.py` L527 | `universe_export.export_aggregates` |
| `sync_universe_aggregates` (~143 LOC) | `routers/universe.py` L683 | `universe_orchestrator.sync_aggregates` |
| `trigger_quality_analysis` (~37 LOC) | `routers/universe.py` L831 | `universe_orchestrator.queue_quality_analysis` |
| `trigger_normalization` (~52 LOC) | `routers/universe.py` L955 | `universe_orchestrator.queue_normalization` |
| **Total extracted** | ~624 LOC | — |
| **Router remainder** | ~382 LOC | `routers/universe.py` |

## Alternatives Considered

### 1. Single `universe_orchestrator.py` for everything including export

Rejected. `export_universe_aggregates` does not orchestrate anything — it queries two models and streams a ZIP. It has no Celery calls, no Redis state, and no cross-service coordination. Folding it into the orchestrator would make the file's name misleading. The `universe_stats.py` precedent (same two models, no Celery, own file) establishes the right pattern for this kind of work.

### 2. Cover both universe.py and scanner.py in one issue

Rejected. The two routers have different orchestration shapes (universe: heavy Celery/Redis coordination; scanner: analytics queries + review aggregation), and combined they would produce ~900 LOC of extraction across 4 new files. That exceeds the size:M label (1–4 hours). Scanner.py is a self-contained follow-on.

### 3. Return `None` from services for not-found cases

Rejected for the orchestration methods. The `journal_service.py` pattern (return `None`, router raises 404) works for simple CRUD lookups where `None` is unambiguous. For orchestration methods like `sync_missing_aggregates` and `queue_normalization`, returning `None` is ambiguous — the caller cannot distinguish "universe not found" from "operation produced no result." Domain exceptions (`UniverseNotFoundError`) are explicit and also make the service reusable from Celery tasks that cannot handle `HTTPException`.

## Assumptions

- The `universe.py` router uses synchronous `Session` (not `AsyncSession`). The new service methods must accept the same sync `Session` to avoid a session-type mismatch — migrating to async is out of scope.
- `SYMBOL_EXCHANGE_MAP` and the Celery task imports can be imported at module level in the new service files (they are currently imported inside the route handler body to avoid circular imports; verify this during implementation).
- `StreamingResponse` stays in the router — `universe_export.export_aggregates` returns a `StreamingResponse` object and the router returns it directly. This is the minimal coupling that keeps streaming working without threading the response type through the service.

## Open Questions (non-blocking)

- Should `get_sync_status()` in the orchestrator be extracted as a standalone function or as a static method on a class? Both work; function is simpler given no shared state.
- The `stop_sync` endpoint (line ~226) writes a Redis key to cancel an in-flight sync. It is currently thin (~20 LOC) but is logically coupled to `sync_aggregates` and `sync_missing_aggregates`. Include it in the orchestrator extraction if it grows in a follow-on, or leave it in the router for now.

## Acceptance Criteria

- [ ] `backend/app/services/universe_orchestrator.py` exists with all six methods extracted from `universe.py`
- [ ] `backend/app/services/universe_export.py` exists with `export_aggregates` extracted
- [ ] `UniverseNotFoundError` and `UniverseValidationError` added to `backend/app/exceptions.py`
- [ ] `routers/universe.py` is ≤400 LOC
- [ ] All 18 endpoints respond correctly via `curl` (per CLAUDE.md validation rules)
- [ ] No changes to public API paths, request schemas, or response schemas
- [ ] Backend restarts cleanly after the change (`docker-compose logs backend --tail=10`)

## Out of Scope

- `backend/app/routers/scanner.py` orchestration extraction (follow-on issue)
- Migration from sync `Session` to `AsyncSession` in universe.py
- Moving scanner review endpoints to `routers/reviews.py`
- Unit tests for the new service modules (tracked separately in issue #25)
