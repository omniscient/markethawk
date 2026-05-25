# tasks.py God Module Split — Domain-Focused Task Modules

## Problem

`backend/app/tasks.py` is 1,678 LOC mixing four unrelated domains: data synchronisation, scanning, auto-trading, and quality analysis. Any agent (dark factory or sub-agent) touching a single task reads the entire file, wasting ~75% of the token budget on unrelated code. Trading bugs require grepping through sync logic, and scan changes require skipping over fill-polling helpers.

## Goal

Split `tasks.py` into four domain-focused modules while preserving all existing Celery task names, Python import paths, and beat schedule strings. Zero behaviour changes; only file locations change.

## Requirements

- Four domain modules replace `tasks.py`: `sync.py`, `scanning.py`, `trading.py`, `quality.py`
- A thin `tasks/__init__.py` re-exports all public task objects so `from app.tasks import <task_name>` continues to work everywhere
- Every `@celery_app.task` decorator carries an explicit `name='app.tasks.<task_name>'` so string-based dispatch (`send_task`, beat schedule) is unaffected
- `celery_app.py` `include=['app.tasks']` stays unchanged — `__init__.py` imports sub-modules, Celery auto-discovers all tasks
- Beat schedule strings in `celery_app.py` stay unchanged
- `live_scanner/publisher.py` and `auto_trading.py` string references stay unchanged
- Private helpers (`_check_entry_slippage`, `_record_entry_fill`, `_record_exit_fill`, `_poll_live_orders`, `_simulate_paper_exit`) move to `tasks/trading.py`; they are NOT re-exported from `__init__.py`
- Test files in `tests/tasks/` are updated to import from `app.tasks.trading` and patch `app.tasks.trading.*` private helpers
- No logic changes — this is a file-splitting refactor only

## Module Map

| Module | Public tasks | Private helpers |
|--------|-------------|-----------------|
| `tasks/sync.py` | `sync_tickers_batch`, `sync_ticker_details`, `start_details_crawl`, `sync_stock_aggregates`, `sync_futures_aggregates`, `sync_stock_splits`, `poll_massive_news` | — |
| `tasks/scanning.py` | `run_universe_scan`, `run_range_scan`, `run_liquidity_hunt_scheduled`, `evaluate_scanner_alerts` | — |
| `tasks/trading.py` | `execute_auto_trade`, `submit_approved_order`, `poll_auto_trade_fills` | `_check_entry_slippage`, `_record_entry_fill`, `_record_exit_fill`, `_poll_live_orders`, `_simulate_paper_exit` |
| `tasks/quality.py` | `analyze_universe_quality`, `normalize_universe_quality`, `analyze_signal_features` | — |
| `tasks/__init__.py` | Re-exports all public tasks above | — |

> `start_details_crawl` is not listed in the issue's proposed structure but lives in `tasks.py`; it belongs in `sync.py` alongside `sync_ticker_details` which it launches.

## Architecture

### Decorator naming

Every public task gets an explicit `name=` to pin the Celery task name:

```python
# tasks/scanning.py
@celery_app.task(bind=True, max_retries=0, name='app.tasks.run_universe_scan')
def run_universe_scan(self, ...):
    ...
```

`analyze_signal_features` already has `name='app.tasks.analyze_signal_features'` — keep it.

### `__init__.py` re-export pattern

```python
# tasks/__init__.py
from app.tasks.sync import (
    sync_tickers_batch,
    sync_ticker_details,
    start_details_crawl,
    sync_stock_aggregates,
    sync_futures_aggregates,
    sync_stock_splits,
    poll_massive_news,
)
from app.tasks.scanning import (
    run_universe_scan,
    run_range_scan,
    run_liquidity_hunt_scheduled,
    evaluate_scanner_alerts,
)
from app.tasks.trading import (
    execute_auto_trade,
    submit_approved_order,
    poll_auto_trade_fills,
)
from app.tasks.quality import (
    analyze_universe_quality,
    normalize_universe_quality,
    analyze_signal_features,
)

__all__ = [
    "sync_tickers_batch", "sync_ticker_details", "start_details_crawl",
    "sync_stock_aggregates", "sync_futures_aggregates", "sync_stock_splits",
    "poll_massive_news",
    "run_universe_scan", "run_range_scan", "run_liquidity_hunt_scheduled",
    "evaluate_scanner_alerts",
    "execute_auto_trade", "submit_approved_order", "poll_auto_trade_fills",
    "analyze_universe_quality", "normalize_universe_quality", "analyze_signal_features",
]
```

### Celery discovery

`celery_app.py` `include=['app.tasks']` loads `tasks/__init__.py`, which imports all sub-modules, which registers all tasks with the Celery app. No change to `celery_app.py` is required.

### Test updates

Two test files reference private helpers by module path:

| File | Current import/patch | Updated to |
|------|---------------------|-----------|
| `tests/tasks/test_slippage.py` | `import app.tasks as tasks_module` | `import app.tasks.trading as tasks_module` |
| `tests/tasks/test_slippage.py` | `patch("app.tasks._record_entry_fill")` | `patch("app.tasks.trading._record_entry_fill")` |
| `tests/tasks/test_paper_exit.py` | `import app.tasks as tasks_module` | `import app.tasks.trading as tasks_module` |
| `tests/tasks/test_paper_exit.py` | `patch("app.tasks._record_exit_fill")` | `patch("app.tasks.trading._record_exit_fill")` |
| `tests/tasks/test_paper_exit.py` | `patch("app.tasks._simulate_paper_exit")` | no change needed — called directly via `tasks_module` |

All other tests that patch public tasks (e.g. `patch("app.tasks.poll_massive_news")`) continue to work because `__init__.py` re-exports the task objects under the same names.

### Files changed

| Action | File |
|--------|------|
| Delete | `backend/app/tasks.py` |
| Create | `backend/app/tasks/__init__.py` |
| Create | `backend/app/tasks/sync.py` |
| Create | `backend/app/tasks/scanning.py` |
| Create | `backend/app/tasks/trading.py` |
| Create | `backend/app/tasks/quality.py` |
| Update | `backend/tests/tasks/test_slippage.py` |
| Update | `backend/tests/tasks/test_paper_exit.py` |

**No changes to:** `celery_app.py`, any router, `live_scanner/publisher.py`, `auto_trading.py`, `alert_service.py`, `discovery_service.py`, or any other callers.

## Alternatives Considered

### Option B: Update all string references to new paths

Update beat schedule, `send_task` calls, and all router imports to use `app.tasks.scanning.*` etc. Rejected: converts a low-risk file-split into a broad cross-cutting refactor touching infrastructure, routers, and live scanner. Celery tasks fail at dispatch time (not import time), making missed references hard to catch. The issue explicitly calls for a "safe, mechanical refactor — no logic changes."

### Inline all tasks in `__init__.py`

Keeps a single file but defeats the goal — agents still read 1,678 lines to find one task. Rejected.

## Assumptions

- `celery_app.task` discovers tasks via `__init__.py` import chain — standard Python package behaviour; no Celery-specific concern.
- No other files reference `app.tasks._<private_helper>` beyond the two test files identified by grep.
- `start_details_crawl` belongs in `sync.py` with the other crawler tasks; the issue omitted it from the table but it is clearly a sync-domain task.

## Open Questions

- None blocking. The refactor is fully mechanical once the module structure is agreed.
