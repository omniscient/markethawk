# Implementation Plan: tasks.py God Module Split

## Goal
Split `backend/app/tasks.py` (1,678 LOC) into four domain-focused modules — `sync.py`, `scanning.py`, `trading.py`, `quality.py` — under a new `tasks/` package, while preserving all Celery task names, Python import paths, and beat schedule strings. Zero behaviour changes.

## Architecture
- `backend/app/tasks/` replaces `backend/app/tasks.py`
- Python package semantics: when both `tasks.py` and `tasks/` exist, the package takes precedence — enables incremental creation before deletion of the flat file
- `tasks/__init__.py` re-exports all 14 public tasks under the same names; `celery_app.py` `include=['app.tasks']` stays unchanged
- Every `@celery_app.task` decorator gains an explicit `name='app.tasks.<task_name>'` to pin the Celery task name; beat schedule strings in `celery_app.py` need no changes
- `evaluate_scanner_alerts` (scanning domain) calls `execute_auto_trade.delay()` (trading domain) — resolved via a lazy import inside the function body to avoid any circular import through `__init__.py`

## Tech Stack
FastAPI + Celery + SQLAlchemy 2.0 (sync ORM session) + Redis + PostgreSQL

## File Structure

| Action | File |
|--------|------|
| Create | `backend/app/tasks/__init__.py` |
| Create | `backend/app/tasks/sync.py` |
| Create | `backend/app/tasks/scanning.py` |
| Create | `backend/app/tasks/trading.py` |
| Create | `backend/app/tasks/quality.py` |
| Delete | `backend/app/tasks.py` |
| Update | `backend/tests/tasks/test_slippage.py` |
| Update | `backend/tests/tasks/test_paper_exit.py` |
| Create | `backend/tests/tasks/test_package_exports.py` |

---

## Task 1: TDD — Write Failing Package Import Tests

### Files
- `backend/tests/tasks/test_package_exports.py`

### TDD Steps

**Write failing test:**

```python
# backend/tests/tasks/test_package_exports.py
"""
Smoke tests verifying the tasks/ package structure after the god-module split.
All assertions should FAIL before the package is created.
"""
import pytest


def test_sync_tasks_importable_from_submodule():
    from app.tasks.sync import (
        sync_tickers_batch,
        sync_ticker_details,
        start_details_crawl,
        sync_stock_aggregates,
        sync_futures_aggregates,
        sync_stock_splits,
        poll_massive_news,
    )
    # All should be Celery tasks with correct pinned names
    assert sync_tickers_batch.name == 'app.tasks.sync_tickers_batch'
    assert sync_ticker_details.name == 'app.tasks.sync_ticker_details'
    assert start_details_crawl.name == 'app.tasks.start_details_crawl'
    assert sync_stock_aggregates.name == 'app.tasks.sync_stock_aggregates'
    assert sync_futures_aggregates.name == 'app.tasks.sync_futures_aggregates'
    assert sync_stock_splits.name == 'app.tasks.sync_stock_splits'
    assert poll_massive_news.name == 'app.tasks.poll_massive_news'


def test_scanning_tasks_importable_from_submodule():
    from app.tasks.scanning import (
        run_universe_scan,
        run_range_scan,
        run_liquidity_hunt_scheduled,
        evaluate_scanner_alerts,
    )
    assert run_universe_scan.name == 'app.tasks.run_universe_scan'
    assert run_range_scan.name == 'app.tasks.run_range_scan'
    assert run_liquidity_hunt_scheduled.name == 'app.tasks.run_liquidity_hunt_scheduled'
    assert evaluate_scanner_alerts.name == 'app.tasks.evaluate_scanner_alerts'


def test_trading_tasks_importable_from_submodule():
    from app.tasks.trading import (
        execute_auto_trade,
        submit_approved_order,
        poll_auto_trade_fills,
    )
    assert execute_auto_trade.name == 'app.tasks.execute_auto_trade'
    assert submit_approved_order.name == 'app.tasks.submit_approved_order'
    assert poll_auto_trade_fills.name == 'app.tasks.poll_auto_trade_fills'


def test_trading_private_helpers_importable_from_trading_submodule():
    from app.tasks.trading import (
        _check_entry_slippage,
        _record_entry_fill,
        _record_exit_fill,
        _poll_live_orders,
        _simulate_paper_exit,
    )
    # Private helpers — importable from trading submodule, but NOT re-exported from __init__
    assert callable(_check_entry_slippage)


def test_quality_tasks_importable_from_submodule():
    from app.tasks.quality import (
        analyze_universe_quality,
        normalize_universe_quality,
        analyze_signal_features,
    )
    assert analyze_universe_quality.name == 'app.tasks.analyze_universe_quality'
    assert normalize_universe_quality.name == 'app.tasks.normalize_universe_quality'
    assert analyze_signal_features.name == 'app.tasks.analyze_signal_features'


def test_all_public_tasks_re_exported_from_init():
    import app.tasks as t
    public = [
        'sync_tickers_batch', 'sync_ticker_details', 'start_details_crawl',
        'sync_stock_aggregates', 'sync_futures_aggregates', 'sync_stock_splits',
        'poll_massive_news',
        'run_universe_scan', 'run_range_scan', 'run_liquidity_hunt_scheduled',
        'evaluate_scanner_alerts',
        'execute_auto_trade', 'submit_approved_order', 'poll_auto_trade_fills',
        'analyze_universe_quality', 'normalize_universe_quality', 'analyze_signal_features',
    ]
    for name in public:
        assert hasattr(t, name), f"app.tasks missing: {name}"


def test_private_helpers_not_in_init_all():
    import app.tasks as t
    private = [
        '_check_entry_slippage', '_record_entry_fill', '_record_exit_fill',
        '_poll_live_orders', '_simulate_paper_exit',
    ]
    all_exports = getattr(t, '__all__', [])
    for name in private:
        assert name not in all_exports, f"{name} should not be in app.tasks.__all__"
```

**Verify it fails:**
```bash
cd backend && python -m pytest tests/tasks/test_package_exports.py -v
# Expected: ImportError — ModuleNotFoundError: No module named 'app.tasks.sync'
```

**Commit:**
```bash
git add backend/tests/tasks/test_package_exports.py
git commit -m "test(tasks): add failing package import tests for god-module split"
```

---

## Task 2: Create the `tasks/` Package

### Files
- `backend/app/tasks/__init__.py`
- `backend/app/tasks/sync.py`
- `backend/app/tasks/trading.py`
- `backend/app/tasks/scanning.py`
- `backend/app/tasks/quality.py`

### TDD Steps

**Verify current test suite passes** (baseline before creating package):
```bash
cd backend && python -m pytest tests/tasks/ -v
```

**Create `backend/app/tasks/sync.py`**

This file receives the seven sync-domain tasks. Copy verbatim from `tasks.py`, changing only the decorator line to add an explicit `name=`.

Module-level imports (extract from `tasks.py` top-level, keep only what sync needs):

```python
# backend/app/tasks/sync.py
import logging
import httpx
import redis
import asyncio
import json
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from sqlalchemy.orm import Session

from app.core.celery_app import celery_app
from app.core.database import SessionLocal
from app.core.config import settings
from app.exceptions import DataFetchError, ProviderError
from app.models.ticker_reference import TickerReference
from app.models.stock_aggregate import StockAggregate
from app.services.stock_data import StockDataService
from app.models.news_preference import NewsPreference
from app.models.news_article import NewsArticle
from app.models.monitored_stock import MonitoredStock
from app.models.stock_split import StockSplit

logger = logging.getLogger(__name__)
```

Decorator changes — each task gets an explicit `name=`. Before → After:

| Task | Before | After |
|------|--------|-------|
| `sync_tickers_batch` | `@celery_app.task(bind=True, max_retries=3)` | `@celery_app.task(bind=True, max_retries=3, name='app.tasks.sync_tickers_batch')` |
| `sync_ticker_details` | `@celery_app.task(bind=True, max_retries=3)` | `@celery_app.task(bind=True, max_retries=3, name='app.tasks.sync_ticker_details')` |
| `start_details_crawl` | `@celery_app.task(bind=True)` | `@celery_app.task(bind=True, name='app.tasks.start_details_crawl')` |
| `sync_stock_aggregates` | `@celery_app.task(bind=True, max_retries=3)` | `@celery_app.task(bind=True, max_retries=3, name='app.tasks.sync_stock_aggregates')` |
| `poll_massive_news` | `@celery_app.task(bind=True, max_retries=3)` | `@celery_app.task(bind=True, max_retries=3, name='app.tasks.poll_massive_news')` |
| `sync_futures_aggregates` | `@celery_app.task(bind=True, max_retries=3)` | `@celery_app.task(bind=True, max_retries=3, name='app.tasks.sync_futures_aggregates')` |
| `sync_stock_splits` | `@celery_app.task(bind=True, max_retries=3)` | `@celery_app.task(bind=True, max_retries=3, name='app.tasks.sync_stock_splits')` |

Task body: identical to `tasks.py`, no changes.

**Create `backend/app/tasks/trading.py`**

Receives the three public trading tasks and five private helpers. The complete module-level import block (all symbols used by the trading tasks and helpers, extracted from `tasks.py` lines 1–20):

```python
# backend/app/tasks/trading.py
import logging
import asyncio
from datetime import datetime, timezone
from sqlalchemy.orm import Session

from app.core.celery_app import celery_app
from app.core.database import SessionLocal

logger = logging.getLogger(__name__)
```

Note: `execute_auto_trade`, `submit_approved_order`, and `poll_auto_trade_fills` each use local imports inside their function bodies (e.g., `from app.models.alert_rule import AlertRule`) — these are already written that way in `tasks.py` and carry over verbatim. The module-level imports above are the only additions needed beyond what each function already imports locally.

Decorator changes:

| Task | Before | After |
|------|--------|-------|
| `execute_auto_trade` | `@celery_app.task(bind=True, max_retries=1)` | `@celery_app.task(bind=True, max_retries=1, name='app.tasks.execute_auto_trade')` |
| `submit_approved_order` | `@celery_app.task(bind=True, max_retries=1)` | `@celery_app.task(bind=True, max_retries=1, name='app.tasks.submit_approved_order')` |
| `poll_auto_trade_fills` | `@celery_app.task(bind=True, max_retries=0)` | `@celery_app.task(bind=True, max_retries=0, name='app.tasks.poll_auto_trade_fills')` |

Everything else in these functions (including local `from app.models.*` and `from app.providers.*` imports inside each function body): copied verbatim from `tasks.py`. Private helpers `_check_entry_slippage`, `_record_entry_fill`, `_record_exit_fill`, `_poll_live_orders`, `_simulate_paper_exit`: copied verbatim from `tasks.py`, no changes.

**Create `backend/app/tasks/scanning.py`**

Receives the four scanning tasks. The complete module-level import block:

```python
# backend/app/tasks/scanning.py
import logging
import asyncio
import redis
import json
from datetime import datetime, timezone, timedelta
from sqlalchemy.orm import Session

from app.core.celery_app import celery_app
from app.core.database import SessionLocal
from app.core.config import settings
from app.exceptions import DataFetchError, ProviderError
from app.services.stock_data import StockDataService
from app.models.monitored_stock import MonitoredStock

logger = logging.getLogger(__name__)
```

Note: `evaluate_scanner_alerts`, `run_range_scan`, `run_liquidity_hunt_scheduled`, and `run_universe_scan` each use local imports inside their function bodies (e.g., `from app.services.scanner import ScannerService`, `from app.models.scanner_run import ScannerRun`) — these are already written that way in `tasks.py` and carry over verbatim.

**CRITICAL — no module-level import of `execute_auto_trade` in `scanning.py`:** `execute_auto_trade` is currently resolved in `tasks.py` as a sibling function in the same module. In `scanning.py` it has no module-level declaration. Do NOT add `from app.tasks.trading import execute_auto_trade` at the top of the file. Use the function-body lazy import instead. This keeps the cross-domain dependency scoped to the single call site rather than implied at the module boundary, and prevents a true circular import if `trading.py` ever grows to import from `scanning.py` in the future.

Decorator changes:

| Task | Before | After |
|------|--------|-------|
| `evaluate_scanner_alerts` | `@celery_app.task(bind=True, max_retries=2)` | `@celery_app.task(bind=True, max_retries=2, name='app.tasks.evaluate_scanner_alerts')` |
| `run_range_scan` | `@celery_app.task` | `@celery_app.task(name='app.tasks.run_range_scan')` |
| `run_liquidity_hunt_scheduled` | `@celery_app.task(bind=True, max_retries=1)` | `@celery_app.task(bind=True, max_retries=1, name='app.tasks.run_liquidity_hunt_scheduled')` |
| `run_universe_scan` | `@celery_app.task(bind=True, max_retries=0)` | `@celery_app.task(bind=True, max_retries=0, name='app.tasks.run_universe_scan')` |

Cross-module import in `evaluate_scanner_alerts`: `execute_auto_trade` is currently an in-scope sibling in `tasks.py`. In `scanning.py` there is no module-level access to it. Find the `if rule.auto_trade and rule.trading_strategy_id:` block inside `evaluate_scanner_alerts` and replace the bare call with a lazy import:

```python
# Inside evaluate_scanner_alerts, inside the `if rule.auto_trade and rule.trading_strategy_id:` block:
from app.tasks.trading import execute_auto_trade  # lazy import — see CRITICAL note above
execute_auto_trade.delay(
    rule_id=rule.id,
    scanner_event_id=scanner_event_id,
)
```

This local import is the ONLY place `execute_auto_trade` appears in `scanning.py`. Do not add it anywhere else.

**Create `backend/app/tasks/quality.py`**

Receives the three quality tasks. Module-level imports:

```python
# backend/app/tasks/quality.py
import logging
from datetime import datetime, timezone
from sqlalchemy.orm import Session

from app.core.celery_app import celery_app
from app.core.database import SessionLocal

logger = logging.getLogger(__name__)
```

Decorator changes:

| Task | Before | After |
|------|--------|-------|
| `analyze_universe_quality` | `@celery_app.task(bind=True, max_retries=0)` | `@celery_app.task(bind=True, max_retries=0, name='app.tasks.analyze_universe_quality')` |
| `normalize_universe_quality` | `@celery_app.task(bind=True, max_retries=0)` | `@celery_app.task(bind=True, max_retries=0, name='app.tasks.normalize_universe_quality')` |
| `analyze_signal_features` | `@celery_app.task(bind=True, max_retries=1, name='app.tasks.analyze_signal_features')` | unchanged — already has explicit name |

**Create `backend/app/tasks/__init__.py`**

```python
# backend/app/tasks/__init__.py
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

**Verify test suite now passes:**
```bash
cd backend && python -m pytest tests/tasks/test_package_exports.py -v
# Expected: all 6 tests PASS

cd backend && python -m pytest tests/tasks/ -v
# Expected: all tests pass (re-exports from __init__ mean existing tests still work)
```

**Commit:**
```bash
git add backend/app/tasks/
git commit -m "feat(tasks): split tasks.py god module into domain packages (sync/scanning/trading/quality)"
```

---

## Task 3: Remove `tasks.py` and Update Test Imports (Atomic)

### Files
- `backend/app/tasks.py` (deleted)
- `backend/tests/tasks/test_slippage.py`
- `backend/tests/tasks/test_paper_exit.py`

### Why atomic
Once `tasks.py` is deleted, `__init__.py` no longer re-exports private helpers (`_check_entry_slippage`, etc.), so `test_slippage.py` and `test_paper_exit.py` break immediately. Fixing both in the same commit ensures every commit on the branch is green.

### TDD Steps

**Verify tests still pass before any deletions** (package takes precedence over `tasks.py` while both exist, but test imports are still via old paths):
```bash
cd backend && python -m pytest tests/tasks/ -v
# NOTE: test_slippage.py and test_paper_exit.py may show AttributeError here already
# because tasks_module._check_entry_slippage is no longer on the app.tasks namespace.
# That's expected — we fix them below in the same commit.
```

**Delete `backend/app/tasks.py`:**
```bash
rm backend/app/tasks.py
```

**Update `backend/tests/tasks/test_slippage.py`:**

Line 4: change the module import:
```python
# Before:
import app.tasks as tasks_module

# After:
import app.tasks.trading as tasks_module
```

Line 26: change the patch target (the only patch in this file — inside the `_run` helper):
```python
# Before:
with patch("app.tasks._record_entry_fill") as mock_fill:

# After:
with patch("app.tasks.trading._record_entry_fill") as mock_fill:
```

**Update `backend/tests/tasks/test_paper_exit.py`:**

Line 5: change the module import:
```python
# Before:
import app.tasks as tasks_module

# After:
import app.tasks.trading as tasks_module
```

There are two occurrences of `patch("app.tasks._record_exit_fill")` in this file — both must be updated:

Occurrence 1 (line 94, inside the `_run` helper of `TestSimulatePaperExit`):
```python
# Before:
             patch("app.tasks._record_exit_fill") as mock_exit:

# After:
             patch("app.tasks.trading._record_exit_fill") as mock_exit:
```

Occurrence 2 (line 139, inside `test_no_provider_skips_silently`):
```python
# Before:
             patch("app.tasks._record_exit_fill") as mock_exit:

# After:
             patch("app.tasks.trading._record_exit_fill") as mock_exit:
```

**Verify all tests pass:**
```bash
cd backend && python -m pytest tests/tasks/ -v
# Expected: all tests in test_slippage.py, test_paper_exit.py, test_package_exports.py PASS
```

**Commit (single atomic commit covering both the deletion and the test fixes):**
```bash
git add -u backend/app/tasks.py
git add backend/tests/tasks/test_slippage.py backend/tests/tasks/test_paper_exit.py
git commit -m "refactor(tasks): remove tasks.py and update private helper patch paths in tests"
```

---

## Task 4: Validate

### Steps

**Full backend test suite:**
```bash
cd backend && python -m pytest -v
# Expected: all tests pass; zero failures
```

**Verify Celery can discover all tasks:**
```bash
docker-compose exec backend python -c "
from app.tasks import (
    sync_tickers_batch, sync_ticker_details, start_details_crawl,
    sync_stock_aggregates, sync_futures_aggregates, sync_stock_splits,
    poll_massive_news, run_universe_scan, run_range_scan,
    run_liquidity_hunt_scheduled, evaluate_scanner_alerts,
    execute_auto_trade, submit_approved_order, poll_auto_trade_fills,
    analyze_universe_quality, normalize_universe_quality, analyze_signal_features,
)
tasks = [
    sync_tickers_batch, sync_ticker_details, start_details_crawl,
    sync_stock_aggregates, sync_futures_aggregates, sync_stock_splits,
    poll_massive_news, run_universe_scan, run_range_scan,
    run_liquidity_hunt_scheduled, evaluate_scanner_alerts,
    execute_auto_trade, submit_approved_order, poll_auto_trade_fills,
    analyze_universe_quality, normalize_universe_quality, analyze_signal_features,
]
for t in tasks:
    expected = f'app.tasks.{t.__name__}'
    assert t.name == expected, f'{t.__name__}: got {t.name!r}, want {expected!r}'
    print(f'  OK  {t.name}')
print('All 17 tasks verified.')
"
# Expected: prints 'OK  app.tasks.<name>' for all 17 tasks, then 'All 17 tasks verified.'
```

**Verify beat schedule task names are still registered:**
```bash
docker-compose exec backend python -c "
from app.core.celery_app import celery_app
from app.tasks import *  # trigger registration
beat_tasks = [v['task'] for v in celery_app.conf.beat_schedule.values()]
print('Beat schedule tasks:', beat_tasks)
registered = list(celery_app.tasks.keys())
for bt in beat_tasks:
    assert bt in registered, f'{bt} not registered!'
    print(f'  OK  {bt}')
"
# Expected: all 5 beat schedule task names confirm registered
```

**Verify send_task string in auto_trading router still resolves:**
```bash
docker-compose exec backend python -c "
from app.core.celery_app import celery_app
from app.tasks import *
task_name = 'app.tasks.submit_approved_order'
assert task_name in celery_app.tasks, f'{task_name} not registered'
print(f'OK: {task_name} is registered for send_task dispatch')
"
```

**Restart Celery worker and confirm startup log shows all tasks:**
```bash
docker-compose restart celery_worker
docker-compose logs celery_worker --tail=30
# Expected: log lines showing registered tasks include app.tasks.sync_tickers_batch etc.
# No ImportError or missing task warnings
```
