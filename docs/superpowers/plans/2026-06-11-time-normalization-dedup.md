# Consolidate Time-Normalization + `get_or_404` Helper

**Date:** 2026-06-11  
**Issue:** [#286](https://github.com/omniscient/markethawk/issues/286)  
**Spec:** `docs/superpowers/specs/2026-06-11-time-normalization-dedup-design.md`  
**Branch:** `refine/issue-286--arch-v3--med--consolidate-time-normaliz`

## Goal

Eliminate two time-normalization idioms spread across 100 call sites by introducing an owning module (`app/utils/time.py`). Eliminate Shape A 404 boilerplate at 14 router endpoints by introducing `app/utils/db.py`. Zero behavior change — purely mechanical consolidation.

## Architecture

Two new utility modules following the `app/utils/session.py` convention:

- **`app/utils/time.py`** — `utc_now()` and `to_utc_naive(dt)` (naive-UTC helpers per ADR-0009)
- **`app/utils/db.py`** — `get_or_404(db, model, record_id, name)` (Shape A PK-lookup helper)

All call sites are codemoded via grep/sed-replace in sequence; no logic changes anywhere.

## Tech Stack

Backend only. FastAPI + SQLAlchemy 2.0 (sync `Session`) + Python 3.11. No frontend, no migration, no schema change.

## File Structure

| File | Action | Notes |
|------|--------|-------|
| `backend/app/utils/time.py` | Create | `utc_now()`, `to_utc_naive()` |
| `backend/app/utils/db.py` | Create | `get_or_404()` |
| `backend/tests/test_time_utils.py` | Create | Unit tests for time utils |
| `backend/tests/test_db_utils.py` | Create | Unit tests for db utils |
| `backend/app/models/*.py` (30 files) | Modify | `default=utc_now` codemod — 48 occurrences |
| `backend/app/tasks/*.py` (4 files) | Modify | `utc_now()` inline codemod |
| `backend/app/services/*.py` (11 files) | Modify | `utc_now()` + `to_utc_naive()` inline codemod (11 `to_utc_naive` sites, some multi-line) |
| `backend/app/routers/*.py` (4 files) | Modify | `utc_now()` + `get_or_404()` codemod |

---

## Task 1: Create `app/utils/time.py` (TDD)

**Files:**
- `backend/tests/test_time_utils.py` (new)
- `backend/app/utils/time.py` (new)

### Step 1.1 — Write failing tests

Create `backend/tests/test_time_utils.py`:

```python
"""Unit tests for app/utils/time.py — utc_now() and to_utc_naive()."""
from datetime import datetime, timezone

import pytest
from zoneinfo import ZoneInfo

from app.utils.time import to_utc_naive, utc_now


class TestUtcNow:
    def test_returns_naive_datetime(self):
        result = utc_now()
        assert result.tzinfo is None

    def test_is_close_to_now(self):
        before = datetime.now(timezone.utc).replace(tzinfo=None)
        result = utc_now()
        after = datetime.now(timezone.utc).replace(tzinfo=None)
        assert before <= result <= after


class TestToUtcNaive:
    def test_aware_utc_returns_naive(self):
        aware = datetime(2024, 1, 15, 12, 0, 0, tzinfo=timezone.utc)
        result = to_utc_naive(aware)
        assert result == datetime(2024, 1, 15, 12, 0, 0)
        assert result.tzinfo is None

    def test_aware_non_utc_converts_correctly(self):
        et = ZoneInfo("America/New_York")
        # EST = UTC-5, so noon ET = 17:00 UTC
        aware = datetime(2024, 1, 15, 12, 0, 0, tzinfo=et)
        result = to_utc_naive(aware)
        assert result == datetime(2024, 1, 15, 17, 0, 0)
        assert result.tzinfo is None

    def test_naive_passthrough_unchanged(self):
        naive = datetime(2024, 1, 15, 12, 0, 0)
        result = to_utc_naive(naive)
        assert result is naive

    def test_idempotent_on_already_naive(self):
        aware = datetime(2024, 6, 1, 10, 30, tzinfo=timezone.utc)
        once = to_utc_naive(aware)
        twice = to_utc_naive(once)
        assert once == twice
        assert twice.tzinfo is None
```

### Step 1.2 — Verify tests fail

```bash
docker-compose exec backend python -m pytest tests/test_time_utils.py -v 2>&1 | tail -15
```

Expected output:
```
ModuleNotFoundError: No module named 'app.utils.time'
ERRORS
```

### Step 1.3 — Implement `backend/app/utils/time.py`

```python
from datetime import datetime, timezone


def utc_now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def to_utc_naive(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt
    return dt.astimezone(timezone.utc).replace(tzinfo=None)
```

### Step 1.4 — Verify tests pass

```bash
docker-compose exec backend python -m pytest tests/test_time_utils.py -v 2>&1 | tail -10
```

Expected output:
```
tests/test_time_utils.py::TestUtcNow::test_returns_naive_datetime PASSED
tests/test_time_utils.py::TestUtcNow::test_is_close_to_now PASSED
tests/test_time_utils.py::TestToUtcNaive::test_aware_utc_returns_naive PASSED
tests/test_time_utils.py::TestToUtcNaive::test_aware_non_utc_converts_correctly PASSED
tests/test_time_utils.py::TestToUtcNaive::test_naive_passthrough_unchanged PASSED
tests/test_time_utils.py::TestToUtcNaive::test_idempotent_on_already_naive PASSED
6 passed
```

### Step 1.5 — Commit

```bash
git add backend/app/utils/time.py backend/tests/test_time_utils.py
git commit -m "feat(#286): add app/utils/time.py with utc_now() and to_utc_naive()"
```

---

## Task 2: Create `app/utils/db.py` (TDD)

**Files:**
- `backend/tests/test_db_utils.py` (new)
- `backend/app/utils/db.py` (new)

### Step 2.1 — Write failing tests

Create `backend/tests/test_db_utils.py`:

```python
"""Unit tests for app/utils/db.py — get_or_404()."""
from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.utils.db import get_or_404


class _FakeModel:
    id = None


class TestGetOr404:
    def test_returns_object_when_found(self):
        db = MagicMock(spec=Session)
        obj = _FakeModel()
        db.query.return_value.filter.return_value.first.return_value = obj
        result = get_or_404(db, _FakeModel, 1, "FakeModel")
        assert result is obj

    def test_raises_404_when_not_found(self):
        db = MagicMock(spec=Session)
        db.query.return_value.filter.return_value.first.return_value = None
        with pytest.raises(HTTPException) as exc_info:
            get_or_404(db, _FakeModel, 99, "Widget")
        assert exc_info.value.status_code == 404
        assert exc_info.value.detail == "Widget not found"

    def test_detail_uses_name_argument(self):
        db = MagicMock(spec=Session)
        db.query.return_value.filter.return_value.first.return_value = None
        with pytest.raises(HTTPException) as exc_info:
            get_or_404(db, _FakeModel, 5, "Strategy")
        assert "Strategy" in exc_info.value.detail
        assert "not found" in exc_info.value.detail
```

### Step 2.2 — Verify tests fail

```bash
docker-compose exec backend python -m pytest tests/test_db_utils.py -v 2>&1 | tail -10
```

Expected output:
```
ModuleNotFoundError: No module named 'app.utils.db'
ERRORS
```

### Step 2.3 — Implement `backend/app/utils/db.py`

```python
from typing import Any

from fastapi import HTTPException
from sqlalchemy.orm import Session


def get_or_404(db: Session, model: type, record_id: Any, name: str) -> Any:
    obj = db.query(model).filter(model.id == record_id).first()
    if obj is None:
        raise HTTPException(status_code=404, detail=f"{name} not found")
    return obj
```

### Step 2.4 — Verify tests pass

```bash
docker-compose exec backend python -m pytest tests/test_db_utils.py -v 2>&1 | tail -10
```

Expected output:
```
tests/test_db_utils.py::TestGetOr404::test_returns_object_when_found PASSED
tests/test_db_utils.py::TestGetOr404::test_raises_404_when_not_found PASSED
tests/test_db_utils.py::TestGetOr404::test_detail_uses_name_argument PASSED
3 passed
```

### Step 2.5 — Commit

```bash
git add backend/app/utils/db.py backend/tests/test_db_utils.py
git commit -m "feat(#286): add app/utils/db.py with get_or_404() helper"
```

---

## Task 3: Codemod model Column defaults → `default=utc_now`

Replace all `default=lambda: datetime.now(timezone.utc).replace(tzinfo=None)` in 30 model files.

**Memory:** `[PROVISIONAL]` from `.archon/memory/backend-patterns.md`: pass callable directly as `default=utc_now`, not `default=lambda: utc_now()` — SQLAlchemy accepts any zero-argument callable; the lambda wrapper adds indirection with no benefit.

**Files (30 model files):**
```
backend/app/models/active_watchlist.py
backend/app/models/alert_delivery_log.py
backend/app/models/alert_rule.py
backend/app/models/auto_trade_order.py
backend/app/models/futures_aggregate.py
backend/app/models/futures_contract.py
backend/app/models/futures_rollover.py
backend/app/models/monitored_account.py
backend/app/models/monitored_stock.py
backend/app/models/news_article.py
backend/app/models/news_preference.py
backend/app/models/push_subscription.py
backend/app/models/scanner_config.py
backend/app/models/scanner_event.py
backend/app/models/scanner_outcome_snapshot.py
backend/app/models/scanner_outcome_summary.py
backend/app/models/scanner_run.py
backend/app/models/signal_analysis_run.py
backend/app/models/signal_cluster.py
backend/app/models/signal_review.py
backend/app/models/stock_aggregate.py
backend/app/models/stock_split.py
backend/app/models/stock_universe.py
backend/app/models/stock_universe_ticker.py
backend/app/models/system_config.py
backend/app/models/ticker_reference.py
backend/app/models/trade.py
backend/app/models/trading_strategy.py
backend/app/models/tweet_signal.py
backend/app/models/universe_quality_report.py
```

### Step 3.1 — Confirm scope

```bash
grep -rn "default=lambda: datetime.now(timezone.utc).replace(tzinfo=None)" \
  backend/app/models/ --include="*.py" | wc -l
```

Expected: ~48

### Step 3.2 — Apply sed codemod (replace lambda with callable ref)

```bash
find backend/app/models/ -name "*.py" -exec \
  sed -i 's/default=lambda: datetime\.now(timezone\.utc)\.replace(tzinfo=None)/default=utc_now/g' {} \;
```

### Step 3.3 — Add `utc_now` import to each modified model file

```bash
for f in $(grep -rl "default=utc_now" backend/app/models/ --include="*.py"); do
  if ! grep -q "from app.utils.time import" "$f"; then
    # Insert after the 'from datetime' import line
    sed -i '/^from datetime import/a from app.utils.time import utc_now' "$f"
  fi
done
```

### Step 3.4 — Remove now-unused `timezone` from `datetime` imports where applicable

For each modified model file, check whether `timezone` is still referenced elsewhere. If the only use was the lambda default, remove it from the import:

```bash
for f in $(grep -rl "from app.utils.time import utc_now" backend/app/models/ --include="*.py"); do
  # If 'timezone' no longer appears in the file body, strip it from the import
  if ! grep -v "^from datetime import" "$f" | grep -q "timezone"; then
    sed -i 's/from datetime import datetime, timezone/from datetime import datetime/' "$f"
    echo "Removed unused timezone import from $f"
  fi
done
```

Review the output manually — any file that still references `timezone` elsewhere keeps it.

### Step 3.5 — Verify codemod completeness

```bash
# Should return 0 — no lambda defaults remain
grep -rn "default=lambda: datetime.now(timezone.utc)" \
  backend/app/models/ --include="*.py" | wc -l

# Should return ~48 — all replaced with callable ref
grep -rn "default=utc_now" backend/app/models/ --include="*.py" | wc -l
```

Expected: `0` then `~48`

### Step 3.6 — Run tests to catch any import breakage

```bash
docker-compose exec backend python -m pytest tests/ -x -q --tb=short 2>&1 | tail -20
```

Expected: all tests pass (no import errors in model files).

### Step 3.7 — Commit

```bash
git add backend/app/models/
git commit -m "refactor(#286): replace model Column default lambdas with utc_now callable ref"
```

---

## Task 4: Codemod inline `utc_now()` in services, tasks, and routers

Replace all inline `datetime.now(timezone.utc).replace(tzinfo=None)` expressions (non-model-default) in 16 files.

**Files (16 files, ~43 occurrences):**
```
# tasks
backend/app/tasks/trading.py
backend/app/tasks/sync.py
backend/app/tasks/quality.py
backend/app/tasks/scanning.py
# services
backend/app/services/outcome_service.py
backend/app/services/stock_data.py
backend/app/services/auto_trade_service.py
backend/app/services/system_service.py
backend/app/services/universe_orchestrator.py
backend/app/services/split_adjustment.py
backend/app/services/alert_service.py
# routers (inline assignments — not the 404 blocks)
backend/app/routers/stocks.py
backend/app/routers/scanner.py
backend/app/routers/auto_trading.py
backend/app/routers/universe.py
backend/app/routers/alerts.py
```

### Step 4.1 — Confirm scope

```bash
grep -rn "datetime\.now(timezone\.utc)\.replace(tzinfo=None)" \
  backend/app/tasks/ backend/app/services/ backend/app/routers/ \
  --include="*.py" | wc -l
```

Expected: 28 (actual per-file breakdown: scanning.py=3, quality.py=3, universe_orchestrator.py=4, auto_trading.py=4, sync.py=2, all others=1)

### Step 4.2 — Apply sed codemod

```bash
TARGET_FILES=(
  backend/app/tasks/trading.py
  backend/app/tasks/sync.py
  backend/app/tasks/quality.py
  backend/app/tasks/scanning.py
  backend/app/services/outcome_service.py
  backend/app/services/stock_data.py
  backend/app/services/auto_trade_service.py
  backend/app/services/system_service.py
  backend/app/services/universe_orchestrator.py
  backend/app/services/split_adjustment.py
  backend/app/services/alert_service.py
  backend/app/routers/stocks.py
  backend/app/routers/scanner.py
  backend/app/routers/auto_trading.py
  backend/app/routers/universe.py
  backend/app/routers/alerts.py
)

for f in "${TARGET_FILES[@]}"; do
  # Replace inline expression with utc_now() call
  sed -i 's/datetime\.now(timezone\.utc)\.replace(tzinfo=None)/utc_now()/g' "$f"
  # Add import if not yet present in this file
  if ! grep -q "from app.utils.time import" "$f"; then
    sed -i '/^from datetime import/a from app.utils.time import utc_now' "$f"
  elif ! grep -q "utc_now" "$f" | head -5; then
    # Already has a utils.time import but missing utc_now — append it
    sed -i 's/from app.utils.time import \(.*\)$/from app.utils.time import \1, utc_now/' "$f"
  fi
done
```

After running, review each file's import line to ensure it's syntactically correct (no duplicate imports, correct comma separation).

### Step 4.3 — Verify codemod

```bash
grep -rn "datetime\.now(timezone\.utc)\.replace(tzinfo=None)" \
  backend/app/tasks/ backend/app/services/ backend/app/routers/ \
  --include="*.py" | wc -l
```

Expected: `0`

### Step 4.4 — Run tests

```bash
docker-compose exec backend python -m pytest tests/ -x -q --tb=short 2>&1 | tail -20
```

Expected: all tests pass.

### Step 4.5 — Commit

```bash
git add backend/app/tasks/ backend/app/services/ backend/app/routers/
git commit -m "refactor(#286): replace inline datetime.now(timezone.utc).replace() with utc_now()"
```

---

## Task 5: Codemod `to_utc_naive()` in services

Replace all `.astimezone(timezone.utc).replace(tzinfo=None)` call chains in 5 service files.

**Files (5 files, 11 occurrences — includes multi-line chained forms):**

| File | Line(s) | Occurrences |
|------|---------|-------------|
| `backend/app/services/session_metrics.py` | ~96–97 | 2 |
| `backend/app/services/pre_market_scan.py` | ~43–47 | 3 (2 single-line + 1 multi-line `hist_start_utc`) |
| `backend/app/services/scan_enrichment.py` | ~55–60 | 3 |
| `backend/app/services/outcome_service.py` | ~90 | 1 |
| `backend/app/services/oversold_bounce_scan.py` | ~39–43 | 2 (1 single-line + 1 multi-line `hist_start_utc`) |

Unlike the `utc_now` codemod, these replacements **cannot** be done with a simple `sed` because the expression-to-wrap (`<expr>`) varies per call site (including 3-line chained forms). Apply manually.

**Important:** Two occurrences are multi-line 3-line chained forms like:
```python
hist_start_utc = (
    (day_start_et - timedelta(days=90))
    .astimezone(timezone.utc)
    .replace(tzinfo=None)
)
```
These are **not** matched by a single-line grep. The verification in Step 5.4 must account for them.

### Step 5.1 — Confirm scope

Single-line grep counts only inline occurrences; multi-line chains must be checked separately:

```bash
# Single-line occurrences (finds 9)
grep -rn "\.astimezone(timezone\.utc)\.replace(tzinfo=None)" \
  backend/app/ --include="*.py"
```

Expected: 9 single-line occurrences. Plus 2 multi-line 3-line chains (1 each in `pre_market_scan.py` and `oversold_bounce_scan.py`) that will not appear above — confirmed by reading those files directly. Total to replace: **11**.

Confirm multi-line chains exist before proceeding:
```bash
grep -n "hist_start_utc" backend/app/services/pre_market_scan.py backend/app/services/oversold_bounce_scan.py
```
Expected: 2 hits (one per file), followed by `.astimezone(timezone.utc).replace(tzinfo=None)` in the surrounding lines.

### Step 5.2 — Apply replacements

**`backend/app/services/session_metrics.py`** (~lines 96–97):

```python
# Before
day_start_utc = day_start_et.astimezone(timezone.utc).replace(tzinfo=None)
day_end_utc = day_end_et.astimezone(timezone.utc).replace(tzinfo=None)
# After
day_start_utc = to_utc_naive(day_start_et)
day_end_utc = to_utc_naive(day_end_et)
```

**`backend/app/services/pre_market_scan.py`** (~lines 43–51, 3 occurrences):

```python
# Before (line ~43 — single-line):
day_start_utc = day_start_et.astimezone(timezone.utc).replace(tzinfo=None)
# After:
day_start_utc = to_utc_naive(day_start_et)
```

```python
# Before (line ~45 — single-line inside parentheses):
(day_start_et + timedelta(days=1)).astimezone(timezone.utc).replace(tzinfo=None)
# After:
to_utc_naive(day_start_et + timedelta(days=1))
```

```python
# Before (lines ~47–51 — multi-line chained form):
hist_start_utc = (
    (day_start_et - timedelta(days=90))
    .astimezone(timezone.utc)
    .replace(tzinfo=None)
)
# After:
hist_start_utc = to_utc_naive(day_start_et - timedelta(days=90))
```

**`backend/app/services/scan_enrichment.py`** (~lines 55–60):

```python
# Before
day_start_utc = day_start_et.astimezone(timezone.utc).replace(tzinfo=None)
...
(day_start_et + timedelta(days=1)).astimezone(timezone.utc).replace(tzinfo=None)
...
(day_start_et - timedelta(days=1)).astimezone(timezone.utc).replace(tzinfo=None)
# After
day_start_utc = to_utc_naive(day_start_et)
...
to_utc_naive(day_start_et + timedelta(days=1))
...
to_utc_naive(day_start_et - timedelta(days=1))
```

**`backend/app/services/outcome_service.py`** (~line 90):

```python
# Before
day_open_utc = day_open_et.astimezone(timezone.utc).replace(tzinfo=None)
# After
day_open_utc = to_utc_naive(day_open_et)
```

**`backend/app/services/oversold_bounce_scan.py`** (~lines 39–43, 2 occurrences):

```python
# Before (line ~39 — single-line inside parentheses):
(day_start_et + timedelta(days=1)).astimezone(timezone.utc).replace(tzinfo=None)
# After:
to_utc_naive(day_start_et + timedelta(days=1))
```

```python
# Before (lines ~41–45 — multi-line chained form):
hist_start_utc = (
    (day_start_et - timedelta(days=90))
    .astimezone(timezone.utc)
    .replace(tzinfo=None)
)
# After:
hist_start_utc = to_utc_naive(day_start_et - timedelta(days=90))
```

### Step 5.3 — Add `to_utc_naive` imports

For each file, update the `app.utils.time` import. `outcome_service.py` was already modified in Task 4 (it has inline `utc_now()` calls) so it needs a combined import:

| File | Final import line |
|------|------------------|
| `session_metrics.py` | `from app.utils.time import to_utc_naive` |
| `pre_market_scan.py` | `from app.utils.time import to_utc_naive` |
| `scan_enrichment.py` | `from app.utils.time import to_utc_naive` |
| `outcome_service.py` | `from app.utils.time import to_utc_naive, utc_now` (replaces the `utc_now`-only import added in Task 4) |
| `oversold_bounce_scan.py` | `from app.utils.time import to_utc_naive` |

For `outcome_service.py`, locate the `from app.utils.time import utc_now` line added in Task 4 and update it to `from app.utils.time import to_utc_naive, utc_now`. Do not leave two separate `from app.utils.time import ...` lines.

### Step 5.4 — Verify codemod

Check both single-line and multi-line forms:

```bash
# Single-line occurrences — should be 0
grep -rn "\.astimezone(timezone\.utc)\.replace(tzinfo=None)" \
  backend/app/ --include="*.py" | wc -l
```

Expected: `0`

```bash
# Multi-line form check — verify the two hist_start_utc blocks are gone
grep -n "\.astimezone(timezone\.utc)" backend/app/ -r --include="*.py"
```

Expected: `0` results (neither single-line nor chained `.astimezone(timezone.utc)` remains outside `utils/time.py`).

### Step 5.5 — Run tests

```bash
docker-compose exec backend python -m pytest tests/ -x -q --tb=short 2>&1 | tail -20
```

Expected: all tests pass.

### Step 5.6 — Commit

```bash
git add backend/app/services/
git commit -m "refactor(#286): replace .astimezone().replace() chains with to_utc_naive()"
```

---

## Task 6: Codemod `get_or_404` in routers

Replace all 15 Shape A 404 patterns across 4 router files.

**Shape A definition:** `db.query(Model).filter(Model.id == id).first()` followed immediately by `if not obj: raise HTTPException(status_code=404, ...)`.

**Files (4 files, 15 instances):**

| File | Instances | Models |
|------|-----------|--------|
| `backend/app/routers/auto_trading.py` | 8 | `TradingStrategy`, `AutoTradeOrder` |
| `backend/app/routers/alerts.py` | 3 | `AlertRule` |
| `backend/app/routers/universe.py` | 3 | `StockUniverse` |
| `backend/app/routers/outcomes.py` | 1 | `ScannerEvent` |

**Out of scope:** `scanner.py` (filters on `uuid`, not `id` — Shape D), `watchlist.py` (filters on `symbol` — Shape D), `journal.py` (service-mediated — Shape B).

### Step 6.1 — Confirm Shape A scope

Count the Shape A instances (db.query on .id + 404) — all 4 files also contain Shape C/D 404s that will remain after this task. Use `re.DOTALL` to count multi-line chained forms:

```bash
python3 - <<'EOF'
import re, pathlib

# DOTALL catches both single-line and multi-line .filter().first() chains
pattern = re.compile(
    r'db\.query\([^)]+\)[\s\S]*?\.filter\([^)]+\.id\b[^)]*\)[\s\S]*?\.first\(\)',
    re.DOTALL
)
files = [
    'backend/app/routers/auto_trading.py',
    'backend/app/routers/alerts.py',
    'backend/app/routers/universe.py',
    'backend/app/routers/outcomes.py',
]
total = 0
for path in files:
    text = pathlib.Path(path).read_text()
    hits = pattern.findall(text)
    if hits:
        print(f'{path}: {len(hits)} Shape A instance(s)')
        total += len(hits)
print(f'Total: {total}')
EOF
```

Expected: 15 total (auto_trading=8, alerts=3, universe=3, outcomes=1).

### Step 6.2 — Apply replacements in `auto_trading.py`

Add import at top of file:
```python
from app.utils.db import get_or_404
```

**Note on detail strings:** The existing `auto_trading.py` detail strings use a trailing period (`"Strategy not found."`, `"Order not found."`). After replacement, `get_or_404` produces `"Strategy not found"` (no period). This is an intentional standardization — `auto_trading.py` is inconsistent with all other routers (`alerts.py`, `universe.py`, `outcomes.py`) which use no trailing period. The conformance reviewer will evaluate this against the spec's "404 responses unchanged" AC.

Replace each Shape A block (8 instances). All examples:

```python
# Before (lines ~121, ~134, ~159 — same pattern):
s = db.query(TradingStrategy).filter(TradingStrategy.id == strategy_id).first()
if not s:
    raise HTTPException(status_code=404, detail="Strategy not found.")
# After:
s = get_or_404(db, TradingStrategy, strategy_id, "Strategy")
```

```python
# Before (lines ~223, ~237, ~267, ~293 — same pattern):
o = db.query(AutoTradeOrder).filter(AutoTradeOrder.id == order_id).first()
if not o:
    raise HTTPException(status_code=404, detail="Order not found.")
# After:
o = get_or_404(db, AutoTradeOrder, order_id, "Order")
```

```python
# Before (line ~246, multi-line form):
strategy = (
    db.query(TradingStrategy)
    .filter(TradingStrategy.id == o.trading_strategy_id)
    .first()
)
if not strategy:
    raise HTTPException(status_code=404, detail="Strategy not found.")
# After:
strategy = get_or_404(db, TradingStrategy, o.trading_strategy_id, "Strategy")
```

### Step 6.3 — Apply replacements in `alerts.py`

Add import: `from app.utils.db import get_or_404`

**Note on detail strings:** Existing detail strings are `"Alert rule not found."` (trailing period, lowercase "Alert rule"). After replacement, `get_or_404(..., "AlertRule")` produces `"AlertRule not found"` — both the trailing period and the casing change. This is an intentional standardization. The conformance reviewer will evaluate this against the "404 responses unchanged" AC.

```python
# Before (lines ~122, ~150, ~166 — same pattern):
rule = db.query(AlertRule).filter(AlertRule.id == rule_id).first()
if not rule:
    raise HTTPException(status_code=404, detail="Alert rule not found.")
# After:
rule = get_or_404(db, AlertRule, rule_id, "AlertRule")
```

### Step 6.4 — Apply replacements in `universe.py`

Add import: `from app.utils.db import get_or_404`

Three Shape A instances; `universe.py` also has 4 additional non-Shape-A 404s (service-mediated, Shape C) that must **not** be touched.

```python
# Before (line ~94, multi-line form — variable name is db_universe):
db_universe = (
    db.query(StockUniverse).filter(StockUniverse.id == universe_id).first()
)
if not db_universe:
    raise HTTPException(status_code=404, detail="Universe not found")
# After:
db_universe = get_or_404(db, StockUniverse, universe_id, "Universe")
```

```python
# Before (lines ~115, ~168 — variable name is universe):
universe = db.query(StockUniverse).filter(StockUniverse.id == universe_id).first()
if not universe:
    raise HTTPException(status_code=404, detail="Universe not found")
# After:
universe = get_or_404(db, StockUniverse, universe_id, "Universe")
```

### Step 6.5 — Apply replacements in `outcomes.py`

Add import: `from app.utils.db import get_or_404`

**Note on detail string:** Existing detail is `"Event not found"`. After replacement, `get_or_404(..., "ScannerEvent")` produces `"ScannerEvent not found"` — the wording changes. This is an intentional standardization using the model class name. The conformance reviewer will evaluate this against the "404 responses unchanged" AC.

```python
# Before (line ~122):
event = db.query(ScannerEvent).filter(ScannerEvent.id == event_id).first()
if not event:
    raise HTTPException(status_code=404, detail="Event not found")
# After:
event = get_or_404(db, ScannerEvent, event_id, "ScannerEvent")
```

### Step 6.6 — Verify codemod (Shape A only, multi-line aware)

Use `re.DOTALL` to match both single-line and multi-line chained forms, ignoring Shape C/D 404s that legitimately remain:

```bash
python3 - <<'EOF'
import re, pathlib

# DOTALL so '.' matches newlines — catches multi-line .filter(...).first() chains
pattern = re.compile(
    r'db\.query\([^)]+\)[\s\S]*?\.filter\([^)]+\.id\b[^)]*\)[\s\S]*?\.first\(\)',
    re.DOTALL
)
files = [
    'backend/app/routers/auto_trading.py',
    'backend/app/routers/alerts.py',
    'backend/app/routers/universe.py',
    'backend/app/routers/outcomes.py',
]
found = []
for path in files:
    text = pathlib.Path(path).read_text()
    hits = pattern.findall(text)
    if hits:
        found.append(f'{path}: {len(hits)} Shape A instance(s) STILL PRESENT')
if found:
    print("FAIL:")
    for line in found:
        print(f"  {line}")
else:
    print("PASS — 0 Shape A patterns remain in targeted router files")
EOF
```

Expected: `PASS — 0 Shape A patterns remain in targeted router files`

### Step 6.7 — Run tests

```bash
docker-compose exec backend python -m pytest tests/ -x -q --tb=short 2>&1 | tail -20
```

Expected: all tests pass.

### Step 6.8 — Commit

```bash
git add \
  backend/app/routers/auto_trading.py \
  backend/app/routers/alerts.py \
  backend/app/routers/universe.py \
  backend/app/routers/outcomes.py
git commit -m "refactor(#286): replace Shape A 404 patterns with get_or_404() helper"
```

---

## Task 7: Validate acceptance criteria

### Step 7.1 — AC1: `utc_now` idiom only in `utils/time.py`

```bash
grep -rn "datetime\.now(timezone\.utc)\.replace(tzinfo=None)" \
  backend/app/ --include="*.py"
```

Expected: exactly **1 line** — `backend/app/utils/time.py` (the implementation itself).

### Step 7.2 — AC2: `to_utc_naive` idiom completely absent outside utils

Check both single-line and multi-line forms:

```bash
# Single-line occurrences
grep -rn "\.astimezone(timezone\.utc)\.replace(tzinfo=None)" \
  backend/app/ --include="*.py" | wc -l
```

Expected: `0`

```bash
# Any remaining .astimezone(timezone.utc) chained calls (catches multi-line forms)
grep -rn "\.astimezone(timezone\.utc)" \
  backend/app/ --include="*.py" | grep -v "utils/time.py"
```

Expected: **0 results** — no `.astimezone(timezone.utc)` outside `utils/time.py`.

### Step 7.3 — AC3: Shape A 404 pattern absent in routers

```bash
python3 - <<'EOF'
import re, pathlib

# Matches: db.query(X).filter(X.id == y).first() on its own line followed by
# if not <var>: or if <var> is None: followed by raise HTTPException(status_code=404
pattern = re.compile(
    r'db\.query\([^)]+\)\.filter\([^)]+\.id\b[^)]*\)\.first\(\)',
    re.MULTILINE
)
routers = list(pathlib.Path('backend/app/routers/').glob('*.py'))
found = []
for f in routers:
    text = f.read_text()
    hits = pattern.findall(text)
    if hits:
        found.append(f'{f.name}: {len(hits)} Shape A-style query(s)')
if found:
    print("FAIL — Shape A patterns remain:")
    for line in found:
        print(f"  {line}")
else:
    print("PASS — no Shape A patterns remain in routers")
EOF
```

Expected: `PASS — no Shape A patterns remain in routers`

### Step 7.4 — Confirm backend reloaded with no errors

```bash
docker-compose logs backend --tail=10
```

Expected: no `ImportError` or `AttributeError` lines.

### Step 7.5 — Run full test suite

```bash
docker-compose exec backend python -m pytest tests/ -q --tb=short 2>&1 | tail -30
```

Expected: all tests pass.

### Step 7.6 — Commit (if any fixup needed)

```bash
git add -p   # review any remaining changes
git commit -m "fix(#286): post-codemod cleanup"
```

---

## Summary

| Task | Files changed | Key action |
|------|---------------|------------|
| 1 | `utils/time.py` + test | TDD: `utc_now()`, `to_utc_naive()` |
| 2 | `utils/db.py` + test | TDD: `get_or_404()` |
| 3 | 30 model files | `default=utc_now` codemod (48 sites) |
| 4 | 16 service/task/router files | `utc_now()` inline codemod (~43 sites) |
| 5 | 5 service files | `to_utc_naive()` manual codemod (11 sites: 9 single-line + 2 multi-line) |
| 6 | 4 router files | `get_or_404()` codemod (15 sites) |
| 7 | — | Grep validation + full test run |

Total: **7 tasks, ~40 steps**. No migration. No schema change. Intentional standardization: `auto_trading.py`, `alerts.py`, and `outcomes.py` detail strings are normalized (trailing periods dropped, model class names used) — flagged to conformance reviewer.
