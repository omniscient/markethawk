# Extract Business Logic from Thick Routers into Services

**Date:** 2026-05-27  
**Status:** Pending Review  
**Issue:** #96  
**Scope:** `backend/app/routers/scanner.py`, `system.py`, `auto_trading.py` → new and existing service modules

## Problem

The Separation of Concerns score in the Architecture & Quality Report (3/5) reflects business logic scattered across three router files that should be thin HTTP adapters. `routers/scanner.py` (857 lines), `routers/system.py` (480 lines), and `routers/auto_trading.py` (557 lines) each contain non-trivial domain logic — Redis state management, market session calculation, IBKR execution wiring, and DB aggregation queries — mixed directly with HTTP handling.

The universe refactor (PR #82) established the target pattern: `routers/universe.py` is a thin adapter that delegates to `universe_orchestrator.py`. This spec applies that pattern to the remaining three thick routers.

## Goals

1. Routers handle only: request validation, service calls, response formatting, HTTP status codes
2. Business logic is independently testable without HTTP concerns
3. No behaviour changes — identical HTTP API contract before and after

## Phasing

Delivered as three independent PRs, one per router, in risk order:

| Phase | Router | New/Modified Service | Risk |
|-------|--------|---------------------|------|
| 1 | `system.py` | New `system_service.py` | Low — read-mostly, no trading state |
| 2 | `scanner.py` | Extended `scan_orchestrator.py` + new `scanner_query_service.py` | Medium — core product, existing service scaffold |
| 3 | `auto_trading.py` | Extended `auto_trade_service.py` + new `schemas/auto_trade.py` | High — touches live IBKR orders |

Each PR delivers both the service extraction and unit tests for the new service functions in the same diff. The existing API integration tests act as a regression net throughout.

## Phase 1 — `system.py` → `system_service.py`

### What moves

| Function | Destination | Notes |
|----------|-------------|-------|
| `_market_status()` | `SystemService.get_market_status()` | Already duplicated in `ScannerService` — unify |
| `_ibkr_reachable(host, port)` | `SystemService.check_ibkr_reachable(host, port)` | Pure TCP probe |
| `format_bytes(size)` | `SystemService.format_bytes(size)` | Static utility |
| Storage query in `get_storage_stats()` | `SystemService.get_storage_stats(db)` | PostgreSQL `pg_catalog` introspection |
| All Redis/Celery logic in `system_tasks_websocket()` | `async SystemService.get_active_tasks(redis_client, db)` | See WS boundary below |

### WebSocket boundary

`system_tasks_websocket()` currently has ~150 lines of embedded polling logic (four Redis pattern scans, 4-hour stale TTL cleanup, `AsyncResult.state` checks, DB queries for universe names, `UniverseQualityReport` auto-reset). This matches the `universe_orchestrator.get_sync_status()` pattern: Redis key scanning + Celery polling is service-layer work.

The extracted function signature:

```python
async def get_active_tasks(
    redis_client: aioredis.Redis,
    db: Session,
) -> list[dict]:
    ...
```

The WS handler retains only the connection lifecycle and the send/sleep loop:

```python
async def system_tasks_websocket(websocket: WebSocket):
    await websocket.accept()
    redis_client = aioredis.from_url(settings.REDIS_URL, decode_responses=True)
    try:
        while True:
            tasks = await SystemService.get_active_tasks(redis_client, SessionLocal())
            await websocket.send_json({"tasks": tasks})
            await asyncio.sleep(2.5)
    except WebSocketDisconnect:
        pass
    finally:
        await redis_client.close()
```

### New file

`backend/app/services/system_service.py` — `SystemService` class with static methods, following the `StatsService` convention. No new models or migrations needed.

### Tests

New `backend/tests/services/test_system_service.py` covering:
- `get_market_status()` for each session boundary (pre, regular, post, closed, weekend)
- `get_storage_stats()` with a real Postgres session (testcontainers fixture)
- `get_active_tasks()` with `fakeredis` and mocked `AsyncResult`

---

## Phase 2 — `scanner.py` → `scan_orchestrator.py` + `scanner_query_service.py`

The remaining router logic splits into two categories with different service homes.

### Category A — Orchestration → `scan_orchestrator.py`

The existing `scan_orchestrator.py` is a 41-line registry/dispatch stub. The following router logic moves into it:

| Router code | New orchestrator function |
|------------|--------------------------|
| `_compute_next_run(scanner_type)` | `compute_next_run(scanner_type) -> Optional[datetime]` |
| Redis progress poll in `get_scan_status()` | `get_scan_progress(redis_url, universe_id, scanner_type) -> Optional[dict]` |
| Redis cancel flag in `cancel_scan()` | `request_scan_cancel(redis_url, scan_id)` |
| `ScannerRun` row creation + Celery `.delay()` in `run_scanner()` | `enqueue_scan(db, request) -> (ScannerRun, AsyncResult)` |

The router's `run_scanner()` becomes: validate → call `enqueue_scan()` → serialize response.

### Category B — DB Aggregations → `scanner_query_service.py`

New file following the `StatsService` class pattern (static methods, `db: Session` first arg):

| Router function | New service method |
|----------------|-------------------|
| `get_signal_quality_distribution()` — decile bucketing | `ScannerQueryService.get_signal_quality_distribution(db, scanner_type, start_date, end_date)` |
| `get_review_stats()` — acceptance rate, by-type breakdown | `ScannerQueryService.get_review_stats(db, scanner_type, start_date, end_date)` |
| `get_scan_status_block()` — success rate, sparkline, event count | `ScannerQueryService.get_scan_status_block(db, scanner_type, universe_id)` |

The router retains only: parameter extraction, `db` injection, single service call, return value.

### What stays in the router

- `list_scanner_types()` — one-liner delegation to `scan_orchestrator.get_all()`, already clean
- `get_scanner_results()` — query assembly with many optional filters; the filter-building itself is HTTP-parameter-driven and belongs in the router
- `get_scanner_history()` — simple `ORDER BY / LIMIT` query, no business logic
- `get_scanner_stats()` — 4 scalar queries; acceptable to leave or move to `StatsService`
- WebSocket endpoint `scan_run_websocket()` — async Redis pub/sub, connection lifecycle is the dominant concern
- Review CRUD endpoints — thin enough already

### Tests

New `backend/tests/services/test_scanner_query_service.py` and extended `test_scan_orchestrator.py` covering:
- Each `ScannerQueryService` method with seeded `ScannerRun`, `ScannerEvent`, `SignalReview` rows
- `compute_next_run()` for liquidity_hunt and non-scheduled scanner types
- `request_scan_cancel()` with `fakeredis`

---

## Phase 3 — `auto_trading.py` → `auto_trade_service.py` + `schemas/auto_trade.py`

### Serializers → Pydantic schemas

`_strategy_to_dict()` and `_order_to_dict()` are replaced by two new Pydantic models in a new file `backend/app/schemas/auto_trade.py`:

```python
class TradingStrategyResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    name: str
    ...

class AutoTradeOrderResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    symbol: str
    ...
```

Exported through `schemas/__init__.py`. Router endpoints switch from `return _order_to_dict(o)` to `return AutoTradeOrderResponse.model_validate(o)`.

### Business logic → `auto_trade_service.py`

`auto_trade_service.py` already exists (533 lines). The following inlined router logic moves into it:

| Router function | New service method |
|----------------|-------------------|
| `approve_order()` — paper mock IDs vs. Celery dispatch | `approve_order(order_id: int, db: Session) -> AutoTradeOrder` |
| `cancel_order()` — IBKR bracket cancel + status update | `cancel_order(order_id: int, db: Session) -> AutoTradeOrder` |
| `get_account()` — IBKR account + open orders fetch | `get_account_summary(db: Session) -> dict` |
| `get_stats()` — P&L, win rate, by-status counts | `get_trading_stats(days: int, db: Session) -> dict` |

### `asyncio.new_event_loop()` convention

The IBKR sync-to-async bridge (`asyncio.new_event_loop()` + `loop.run_until_complete()`) is the established pattern in this codebase (`auto_trade_service.py` lines 331 and 519, `tasks/trading.py` line 300). The extracted `cancel_order` and `get_account_summary` service methods use the same pattern. The router endpoints remain `def` (sync). No conversion to `async def` — that would require refactoring `IBKROrderManager`'s async interface, which is out of scope.

### Tests

Extend `backend/tests/services/test_auto_trade_service.py` with:
- `approve_order()` for paper path (mock IDs assigned) and live path (Celery task queued)
- `cancel_order()` for paper and live paths, and the 409 guard for non-cancellable statuses
- `get_trading_stats()` with seeded `AutoTradeOrder` + `Trade` rows

---

## Alternatives Considered

**Single PR for all three routers.** Rejected: each router is M-sized on its own; bundling all three creates a very large diff that mixes three independent risk profiles and is hard to review safely.

**Option A for `system.py` WS handler: leave WS handler as-is, only extract sync helpers.** Rejected: the 150-line polling block is the primary business logic violating the thin-router principle, and the `universe_orchestrator.get_sync_status()` precedent shows this category of logic belongs in services.

**Option A for `scanner.py`: single `scan_orchestrator.py` for both orchestration and aggregation.** Rejected: `scan_orchestrator.py` is a registry/dispatch module with no DB query layer. Adding decile bucketing and `ScannerRun` aggregations would violate its single responsibility and fight the existing `StatsService` pattern.

**Convert IBKR endpoints to `async def`.** Rejected: requires refactoring `IBKROrderManager`, introduces a second pattern for sync-to-async bridging, and provides no practical benefit for infrequent human-initiated operations already dominated by IBKR network latency.

---

## Open Questions

- `_market_status()` in `system.py` duplicates session-boundary logic in `ScannerService.calculate_day_metrics()`. Phase 1 can unify these by importing from `system_service.py` — or defer unification to a separate cleanup ticket. Non-blocking.
- `get_scanner_stats()` in `scanner.py` (4 scalar queries) is borderline — it could move to `StatsService` or stay in the router. Non-blocking for Phase 2.

---

## Assumptions

- **[ASSUMED]** No behaviour changes are in scope. All extracted functions must produce identical outputs to the current inlined router code.
- **[ASSUMED]** The 60% coverage gate in `pyproject.toml` has headroom. New service files with their own tests will only raise the measured percentage.
- **[ASSUMED]** `auto_trade_service.py`'s existing `submit_existing_order()` is called by the new `approve_order()` service method for the live path (it already exists and is tested).
