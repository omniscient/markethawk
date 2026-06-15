# Plan: F-INPUT-01 — Unbounded Pagination + Reflective Sort Hardening

**Date:** 2026-06-15  
**Issue:** #376  
**Spec:** docs/superpowers/specs/2026-06-13-unbounded-pagination-sort-allowlist-design.md  
**Goal:** Cap `limit` on three API endpoints and replace the reflective `getattr` sort on `/scanner/results` with an explicit allowlist dict, eliminating CWE-770 and CWE-915 exposures.

---

## Architecture

No model changes, no migration. All changes are in two router files and their test modules:
- `backend/app/routers/scanner.py` — sort dict + `Query` constraints on `/history` and `/results`
- `backend/app/routers/outcomes.py` — `Query` constraint on `/signals/{scanner_type}`
- Tests for each change co-located with the existing test files

The fix matches the established pattern:
- `Query(N, ge=1, le=200)` — identical to `routers/tweets.py:59`
- Column allowlist dict — identical to `StatsService.get_signals()` in `stats.py:463`

---

## Tech Stack

FastAPI `Query` (already imported in `scanner.py`; needs `Query` added to `outcomes.py` imports). No new dependencies.

---

## File Structure

| File | Change |
|------|--------|
| `backend/app/routers/scanner.py` | Add `SCANNER_RESULTS_SORT_COLUMNS` dict; replace `try/except getattr` with dict lookup + 422 guard; `Query(100, ge=1, le=200)` on `/results`; `Query(20, ge=1, le=200)` on `/history` |
| `backend/app/routers/outcomes.py` | Add `Query` import; `Query(100, ge=1, le=200)` on `/signals/{scanner_type}` |
| `backend/tests/api/test_scanner.py` | 4 new tests: limit cap 422 on `/results` and `/history`; `sort_by=__class__` 422; valid `sort_by` 200 |
| `backend/tests/api/test_outcomes.py` | 1 new test: limit cap 422 on `/signals/{scanner_type}` |

---

## Task 1: Add `SCANNER_RESULTS_SORT_COLUMNS` dict and replace reflective sort in `/scanner/results`

**Files:** `backend/app/routers/scanner.py`, `backend/tests/api/test_scanner.py`

### TDD

**Step 1 — Write failing tests**

Add at the end of `backend/tests/api/test_scanner.py`:

```python
# ---------------------------------------------------------------------------
# Sort allowlist validation (F-INPUT-01)
# ---------------------------------------------------------------------------


def test_results_invalid_sort_by_rejected(db: Session):
    response = client.get("/api/v1/scanner/results?sort_by=__class__")
    assert response.status_code == 422


def test_results_valid_sort_by_accepted(db: Session):
    seed_scanner_events(db)
    response = client.get("/api/v1/scanner/results?sort_by=signal_quality_score")
    assert response.status_code == 200
```

**Step 2 — Verify the tests currently fail**

```bash
docker-compose exec backend python -m pytest backend/tests/api/test_scanner.py \
  -k "test_results_invalid_sort_by_rejected or test_results_valid_sort_by_accepted" -v
```

Expected output:
```
FAILED backend/tests/api/test_scanner.py::test_results_invalid_sort_by_rejected
  AssertionError: assert 200 == 422   ← currently passes bad input silently
PASSED backend/tests/api/test_scanner.py::test_results_valid_sort_by_accepted
```
(One fail, one pass — `test_results_invalid_sort_by_rejected` is the failing gate.)

**Step 3 — Implement**

After the `router = APIRouter(...)` line (line 53 of `backend/app/routers/scanner.py`), add the module-level dict:

```python
# Explicit allowlist — mirrors StatsService.get_signals() sort_col_map pattern.
# Extending sort options requires adding an entry here (intentional).
SCANNER_RESULTS_SORT_COLUMNS = {
    "signal_quality_score": ScannerEvent.signal_quality_score,
    "event_date": ScannerEvent.event_date,
    "ticker": ScannerEvent.ticker,
    "severity": ScannerEvent.severity,
    "created_at": ScannerEvent.created_at,
}
```

Then replace the sorting block in `get_scanner_results` (lines 407–421 of `scanner.py`):

**Before:**
```python
    # Sorting logic
    try:
        if sort_by:
            sort_attr = getattr(ScannerEvent, sort_by, ScannerEvent.created_at)
            if sort_order.lower() == "desc":
                order_expr = sort_attr.desc().nulls_last()
            else:
                order_expr = sort_attr.asc().nulls_last()
            query = query.order_by(order_expr)
        else:
            query = query.order_by(
                ScannerEvent.signal_quality_score.desc().nulls_last()
            )
    except Exception:
        query = query.order_by(ScannerEvent.created_at.desc())
```

**After:**
```python
    # Sort validation and application
    if sort_by and sort_by not in SCANNER_RESULTS_SORT_COLUMNS:
        raise HTTPException(status_code=422, detail=f"Invalid sort field: {sort_by}")
    sort_attr = SCANNER_RESULTS_SORT_COLUMNS.get(
        sort_by, ScannerEvent.signal_quality_score
    )
    if sort_order and sort_order.lower() == "asc":
        query = query.order_by(sort_attr.asc().nulls_last())
    else:
        query = query.order_by(sort_attr.desc().nulls_last())
```

**Step 4 — Verify tests pass**

```bash
docker-compose exec backend python -m pytest backend/tests/api/test_scanner.py \
  -k "test_results_invalid_sort_by_rejected or test_results_valid_sort_by_accepted" -v
```

Expected output:
```
PASSED backend/tests/api/test_scanner.py::test_results_invalid_sort_by_rejected
PASSED backend/tests/api/test_scanner.py::test_results_valid_sort_by_accepted
2 passed in ...
```

Also verify the full scanner test suite is green:
```bash
docker-compose exec backend python -m pytest backend/tests/api/test_scanner.py -v --tb=short
```

**Step 5 — Commit**

```bash
git add backend/app/routers/scanner.py backend/tests/api/test_scanner.py
git commit -m "security(scanner): replace reflective getattr sort with explicit allowlist (#376)"
```

---

## Task 2: Cap `limit` on `/scanner/history` and `/scanner/results`

**Files:** `backend/app/routers/scanner.py`, `backend/tests/api/test_scanner.py`

`Query` is already imported in `scanner.py` (line 14) — no import change needed.

### TDD

**Step 1 — Write failing tests**

Add to `backend/tests/api/test_scanner.py` (below the sort tests from Task 1):

```python
# ---------------------------------------------------------------------------
# Limit cap validation (F-INPUT-01)
# ---------------------------------------------------------------------------


def test_results_limit_too_large_rejected(db: Session):
    response = client.get("/api/v1/scanner/results?limit=10000000")
    assert response.status_code == 422


def test_history_limit_too_large_rejected(db: Session):
    response = client.get("/api/v1/scanner/history?limit=10000000")
    assert response.status_code == 422
```

**Step 2 — Verify the tests currently fail**

```bash
docker-compose exec backend python -m pytest backend/tests/api/test_scanner.py \
  -k "test_results_limit_too_large_rejected or test_history_limit_too_large_rejected" -v
```

Expected output:
```
FAILED backend/tests/api/test_scanner.py::test_results_limit_too_large_rejected
FAILED backend/tests/api/test_scanner.py::test_history_limit_too_large_rejected
  AssertionError: assert 200 == 422   ← currently accepts unbounded limit
```

**Step 3 — Implement**

In `backend/app/routers/scanner.py`:

**Change 1** — `/history` endpoint signature (line 338):

```python
# Before:
    limit: int = 20,

# After:
    limit: int = Query(20, ge=1, le=200),
```

**Change 2** — `/results` endpoint signature (line 370):

```python
# Before:
    limit: int = 100,

# After:
    limit: int = Query(100, ge=1, le=200),
```

**Step 4 — Verify tests pass**

```bash
docker-compose exec backend python -m pytest backend/tests/api/test_scanner.py \
  -k "test_results_limit_too_large_rejected or test_history_limit_too_large_rejected" -v
```

Expected output:
```
PASSED backend/tests/api/test_scanner.py::test_results_limit_too_large_rejected
PASSED backend/tests/api/test_scanner.py::test_history_limit_too_large_rejected
2 passed in ...
```

Verify existing limit tests are unaffected:
```bash
docker-compose exec backend python -m pytest backend/tests/api/test_scanner.py \
  -k "limit" -v --tb=short
```

Expected: all passing (the existing `test_history_respects_limit` tests with `?limit=2` are within bounds).

**Step 5 — Commit**

```bash
git add backend/app/routers/scanner.py backend/tests/api/test_scanner.py
git commit -m "security(scanner): cap limit with Query(ge=1, le=200) on /history and /results (#376)"
```

---

## Task 3: Cap `limit` on `/outcomes/signals/{scanner_type}`

**Files:** `backend/app/routers/outcomes.py`, `backend/tests/api/test_outcomes.py`

`Query` is **not** currently imported in `outcomes.py` — must be added.

### TDD

**Step 1 — Write failing test**

Add to `backend/tests/api/test_outcomes.py`:

```python
# ---------------------------------------------------------------------------
# Limit cap validation (F-INPUT-01)
# ---------------------------------------------------------------------------


def test_signals_limit_too_large_rejected(db: Session):
    response = client.get(
        "/api/v1/outcomes/signals/pre_market_volume_spike?limit=10000000"
    )
    assert response.status_code == 422
```

**Step 2 — Verify the test currently fails**

```bash
docker-compose exec backend python -m pytest backend/tests/api/test_outcomes.py \
  -k "test_signals_limit_too_large_rejected" -v
```

Expected output:
```
FAILED backend/tests/api/test_outcomes.py::test_signals_limit_too_large_rejected
  AssertionError: assert 200 == 422
```

**Step 3 — Implement**

In `backend/app/routers/outcomes.py`, change the fastapi import line (line 8):

```python
# Before:
from fastapi import APIRouter, Depends, HTTPException

# After:
from fastapi import APIRouter, Depends, HTTPException, Query
```

Change the `limit` parameter in `get_signals` (line 121):

```python
# Before:
    limit: int = 100,

# After:
    limit: int = Query(100, ge=1, le=200),
```

**Step 4 — Verify tests pass**

```bash
docker-compose exec backend python -m pytest backend/tests/api/test_outcomes.py \
  -k "test_signals_limit_too_large_rejected" -v
```

Expected output:
```
PASSED backend/tests/api/test_outcomes.py::test_signals_limit_too_large_rejected
1 passed in ...
```

Verify existing outcomes tests still pass:
```bash
docker-compose exec backend python -m pytest backend/tests/api/test_outcomes.py -v --tb=short
```

**Step 5 — Commit**

```bash
git add backend/app/routers/outcomes.py backend/tests/api/test_outcomes.py
git commit -m "security(outcomes): cap limit with Query(ge=1, le=200) on /signals/{scanner_type} (#376)"
```

---

## Final Validation

After all three tasks are committed:

```bash
# Full test suite for the two affected routers
docker-compose exec backend python -m pytest \
  backend/tests/api/test_scanner.py \
  backend/tests/api/test_outcomes.py \
  -v --tb=short
```

Expected: all existing + new tests pass.

Manually verify the attack vectors from the spec:
```bash
# CWE-770: unbounded limit
curl -s http://localhost:8000/api/v1/scanner/results?limit=10000000 | python -m json.tool
# Expected: 422 with validation error detail

curl -s http://localhost:8000/api/v1/scanner/history?limit=10000000 | python -m json.tool
# Expected: 422 with validation error detail

curl -s "http://localhost:8000/api/v1/outcomes/signals/pre_market_volume_spike?limit=10000000" | python -m json.tool
# Expected: 422 with validation error detail

# CWE-915: reflective sort
curl -s "http://localhost:8000/api/v1/scanner/results?sort_by=__class__" | python -m json.tool
# Expected: 422 {"detail": "Invalid sort field: __class__"}

# Happy path — default params still work
curl -s http://localhost:8000/api/v1/scanner/results | python -m json.tool | head -5
# Expected: 200 with scanner events array
```
