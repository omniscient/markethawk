# Celery Task Coverage — Design

**Date:** 2026-06-05
**Status:** Draft — pending implementation plan
**Author:** Brainstormed with Claude (Opus 4.8)
**Issue:** [#204](https://github.com/omniscient/markethawk/issues/204)

## Problem

`backend/pyproject.toml` excludes the entire `app/tasks/` package from
pytest-cov measurement. About 1,800 lines of task business logic — date-range
iteration, scan-result persistence, quality analysis lifecycle, fill recording,
trading-hours guards — never appear in the 60% coverage gate. The gate
overstates coverage and gives a false signal on regressions in task code.

## Requirements

1. Remove the blanket `app/tasks/*.py` omit from `[tool.coverage.run]`.
2. Replace it with precise per-line or per-function `# pragma: no cover`
   annotations on the two genuinely broker-bound code paths:
   - `trading.py::_poll_live_orders` (live IBKR socket via `IBKROrderManager`)
   - `sync.py::sync_futures_aggregates` body (delegates to
     `FuturesDataService` which needs a live IBKR connection; keep the existing
     `app/services/futures_data.py` omit unchanged)
3. Extract the business logic of each task into injectable helper functions
   within the same task module. Each helper receives a DB session, a publish
   callable, and any other injected dependencies rather than constructing them
   internally. The Celery-decorated shell retains only broker-bound concerns:
   `self.request.id`, `SessionLocal()`, `redis.Redis.from_url(...)`, retry,
   OTel span creation, and Prometheus timing.
4. Add unit tests in `backend/tests/tasks/` covering the extracted helpers and
   the task guard logic. Tests follow the existing pattern in the directory:
   `SessionLocal` patched with `MagicMock`, `httpx.Client` mocked with
   `unittest.mock`, `fakeredis` for Redis, task `.run()` called directly for
   `bind=True` tasks.
5. The 60% coverage gate must continue to pass after the omit is narrowed.

## Scope

**In scope:**
- `app/tasks/scanning.py` — extract and test logic in all five task bodies
  (`run_universe_scan`, `run_range_scan`, `run_liquidity_hunt_scheduled`,
  `run_pocket_pivot_scheduled`, `evaluate_scanner_alerts`) and
  `validate_scheduled_scanner_configs` (already partially tested; expand).
- `app/tasks/quality.py` — extract and test lifecycle logic in
  `analyze_universe_quality`, `normalize_universe_quality`,
  `analyze_signal_features`.
- `app/tasks/trading.py` — the pure helper functions (`_record_entry_fill`,
  `_record_exit_fill`, `_check_entry_slippage`, `_simulate_paper_exit`) are
  already tested via `test_paper_exit.py` and `test_slippage.py`; add tests
  for the three task shells (`execute_auto_trade`, `submit_approved_order`,
  `poll_auto_trade_fills` paper path). Mark `_poll_live_orders` with
  `# pragma: no cover`.
- `app/tasks/sync.py` — mock `httpx.Client` (no new dependencies; use
  `unittest.mock.patch` per the existing `tests/fixtures/providers.py`
  pattern) and test: trading-hours guard in `poll_massive_news`, ticker-upsert
  loop in `sync_tickers_batch`, aggregate-insert path in
  `sync_stock_aggregates`, split-dedup in `sync_stock_splits`,
  `trigger_tweet_monitor`. Mark `sync_futures_aggregates` body with
  `# pragma: no cover` (delegates entirely to `FuturesDataService`).
- `backend/pyproject.toml` — narrow coverage omit.
- `backend/tests/tasks/` — new test functions in existing files or new files.

**Out of scope:**
- Changing the public task signatures or Celery task names.
- Adding `respx` or any other HTTP mocking library.
- Increasing the 60% gate percentage (that is a separate issue).
- Testing `app/services/futures_data.py` (stays excluded; live IBKR only).
- Testing `app/main.py` (stays excluded).

## Architecture

### Extraction pattern

For each task with non-trivial inline logic, extract a `_<task>_logic(...)` helper:

```python
# BEFORE
@celery_app.task(bind=True, name="app.tasks.run_universe_scan")
def run_universe_scan(self, scan_id, scanner_type, universe_id, ...):
    r = redis.Redis.from_url(settings.REDIS_URL, ...)
    db = SessionLocal()
    # 200 lines of logic...

# AFTER
def _run_universe_scan_logic(
    scan_id: str,
    scanner_type: str,
    universe_id: int,
    start: date,
    end: date,
    db: Session,
    publish: Callable[[dict], None],   # injected: r.publish(channel, json.dumps(...))
    is_cancelled: Callable[[], bool],  # injected: lambda: r.exists(cancel_key) > 0
    task_id: str,
) -> None:
    # all the business logic, no Redis/Celery imports needed

@celery_app.task(bind=True, max_retries=0, name="app.tasks.run_universe_scan")
def run_universe_scan(self, scan_id, scanner_type, universe_id, start_date_iso, end_date_iso):
    r = redis.Redis.from_url(...)          # broker concern
    db = SessionLocal()                   # broker concern
    channel = f"scan_task:{self.request.id}"
    cancel_key = f"scan_cancel:{scan_id}"
    _run_universe_scan_logic(
        scan_id, scanner_type, universe_id,
        date.fromisoformat(start_date_iso),
        date.fromisoformat(end_date_iso),
        db=db,
        publish=lambda p: r.publish(channel, json.dumps(p, default=str)),
        is_cancelled=lambda: r.exists(cancel_key) > 0,
        task_id=self.request.id,
    )
```

The same injection pattern applies to `run_range_scan`, `run_liquidity_hunt_scheduled`,
`run_pocket_pivot_scheduled`, and `evaluate_scanner_alerts`.

For `quality.py` and `trading.py` shells the tasks are already thin enough that
helper extraction may not be necessary — the test can patch `SessionLocal` and
call `.run()` directly, matching the existing `test_scheduled_scanner_tasks.py`
pattern.

### Coverage exclusion mechanism

Prefer `# pragma: no cover` on the function def line over adding a file-level
entry to `[tool.coverage.run] omit`, so coverage reports include the file-level
summary and non-excluded lines count toward the gate.

```python
def _poll_live_orders(orders, db, now) -> None:  # pragma: no cover
    ...

@celery_app.task(bind=True, max_retries=3, name="app.tasks.sync_futures_aggregates")
def sync_futures_aggregates(self, symbol, exchange, ...):  # pragma: no cover
    ...
```

`app/services/futures_data.py` stays in the file-level omit list unchanged.

### Test strategy per file

| File | New test target | Mocking approach |
|------|-----------------|------------------|
| `scanning.py` | `_run_universe_scan_logic` (day iteration, cancel path, failed-run path), `run_range_scan` guard logic | `MagicMock` DB; `fakeredis.FakeRedis` for publish; mock `_orchestrator.run` |
| `scanning.py` | `run_liquidity_hunt_scheduled` / `run_pocket_pivot_scheduled` extra cases | Already tested; extend `TestRunLiquidityHuntScheduledFixed` |
| `quality.py` | `analyze_universe_quality` (running→complete, running→error), `normalize_universe_quality` (missing report guard, success path), `analyze_signal_features` (insufficient data early return) | `MagicMock` DB + mock service calls |
| `trading.py` | `execute_auto_trade` (rule not found, event not found, success), `submit_approved_order` (not found, wrong status, success), `poll_auto_trade_fills` paper path | `MagicMock` DB; `_record_entry_fill`/`_record_exit_fill` already tested |
| `sync.py` | `poll_massive_news` weekday guard + fetch loop, `sync_tickers_batch` upsert, `sync_stock_splits` dedup, `trigger_tweet_monitor` success + retry | `patch("httpx.Client")` per fixture in `tests/fixtures/providers.py:173` |

### pyproject.toml change

```toml
[tool.coverage.run]
source = ["app"]
omit = [
    "app/main.py",
    "app/migrations/*",
    # Requires live IBKR connection — tested via manual QA
    "app/services/futures_data.py",
]
# _poll_live_orders and sync_futures_aggregates carry # pragma: no cover
```

## Alternatives Considered

**File-level omit narrowed to per-file rather than per-function.** E.g. keep
`app/tasks/sync.py` excluded and only remove `scanning.py` / `quality.py`.
Rejected because the issue explicitly calls for "coverage reflects task logic"
and the sync.py logic (trading-hours guards, upsert loops, split dedup) is
non-trivial. Mocking `httpx.Client` is standard practice and adds no new
dependencies.

**Push logic into services (service layer extraction).** Extract task body into
a new `scan_execution_service.py` with a clean Redis-state and progress-callback
abstraction. Rejected for this issue: the tasks already delegate the heavy
computation to services; what remains is orchestration glue. A full service
extraction would redesign the orchestrator contract and exceed the M budget.
Tracked as a possible follow-up.

**Test tasks in-place without extraction.** Patch `SessionLocal`, `redis.Redis`,
`celery_app`, OTel, and Prometheus all at once and call the decorated function
body. Rejected: fragile, tests scaffolding over logic, and doesn't address the
fundamental coverage gap (the decorated body is still opaque to coverage when
`celery_app` is mocked at import time).

## Open Questions

None.

## Assumptions

- `fakeredis` is already available in the test environment (confirmed:
  `fakeredis==2.28.1` in `backend/requirements.txt`).
- `pandas`, `lightgbm`, and `shap` are in `backend/requirements.txt` (confirmed), so
  `analyze_signal_features` tests can import them without conditional skipping.
- `respx` is NOT available and NOT needed — `unittest.mock.patch("httpx.Client")`
  is the established convention.
- The 60% gate continues to pass after the omit narrows. If the task code
  brings the overall coverage below 60%, the implement agent must add enough
  test cases to bring it back over the threshold before committing.
- `app/tasks/__init__.py` imports are unchanged; task module names and Celery
  task string identities (`name='app.tasks.*'`) are not altered.
