# Consolidate Time-Normalization + get_or_404 Helper — Design

**Date:** 2026-06-11  
**Status:** Pending review  
**Issue:** [#286](https://github.com/omniscient/markethawk/issues/286)  
**Author:** Brainstormed with Claude (Opus 4.8)

## Problem

Two time-normalization idioms with no owning module spread across the entire backend:

- `datetime.now(timezone.utc).replace(tzinfo=None)` — 53 files (~100 occurrences)
- `<aware_dt>.astimezone(timezone.utc).replace(tzinfo=None)` — ~96 occurrences in services and tasks

Plus a 404 boilerplate pattern — `db.query(Model).filter(Model.id == id).first(); if not: raise HTTPException(404)` — repeated at ~20 router endpoints across 5+ files.

None of these idioms have an owning module. Any new file that touches timestamps or ID-based lookups must re-invent them. The v3 architecture review flagged both as growth-trend duplications.

## Non-Goals (v1)

- Migrating `TIMESTAMP WITHOUT TIME ZONE` columns to `TIMESTAMPTZ` (addressed separately in ADR-0009 future work)
- Creating a generic `get_or_404` that handles non-PK lookups, service-mediated lookups, or domain-exception-based 404s — those remain as-is
- Adding type-stub or Protocol abstractions beyond what the issue requires

## Requirements

1. **`app/utils/time.py`** — new module with two public functions:
   - `utc_now() -> datetime` — returns current naive-UTC datetime
   - `to_utc_naive(dt: datetime) -> datetime` — converts aware datetime to naive-UTC; passes naive input through unchanged (assumed already UTC per ADR-0009)

2. **`app/utils/db.py`** — new module with one public function:
   - `get_or_404(db: Session, model: type, record_id: Any, name: str) -> Any` — queries `db.query(model).filter(model.id == record_id).first()`, raises `HTTPException(status_code=404, detail=f"{name} not found")` if None

3. **Codemod — `utc_now()`**: Replace all `datetime.now(timezone.utc).replace(tzinfo=None)` occurrences:
   - In model `default=lambda: ...` forms: use `default=utc_now` (pass callable, not call it)
   - In inline expressions (task code, service code): use `utc_now()`

4. **Codemod — `to_utc_naive()`**: Replace all `<expr>.astimezone(timezone.utc).replace(tzinfo=None)` occurrences with `to_utc_naive(<expr>)` in services and tasks

5. **Codemod — `get_or_404`**: Replace all Shape A 404 patterns in routers:
   ```python
   # Before
   obj = db.query(Model).filter(Model.id == id).first()
   if not obj:
       raise HTTPException(status_code=404, detail="Model not found")
   # After
   obj = get_or_404(db, Model, id, "Model")
   ```
   Shapes B (service-mediated), C (domain-exception), D (non-id field) are **out of scope**.

6. **Acceptance criteria** (from issue):
   - `grep -r "datetime.now(timezone.utc).replace(tzinfo=None)" backend/app/ --include="*.py"` returns only `app/utils/time.py` (no call sites remain)
   - `grep -r "\.astimezone(timezone\.utc)\.replace(tzinfo=None)" backend/app/ --include="*.py"` returns 0 results outside `app/utils/time.py`
   - Every Shape A instance (`db.query(Model).filter(Model.id == id).first()` + `if not: raise HTTPException(404)`) in routers is replaced; the compound grep pattern for that two-line idiom returns 0 hits in routers
   - No behavior change — timestamps remain naive-UTC in DB, 404 responses unchanged

## Architecture / Approach

### New files

**`backend/app/utils/time.py`**
```python
from datetime import datetime, timezone


def utc_now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def to_utc_naive(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt
    return dt.astimezone(timezone.utc).replace(tzinfo=None)
```

**`backend/app/utils/db.py`**
```python
from typing import Any
from sqlalchemy.orm import Session
from fastapi import HTTPException


def get_or_404(db: Session, model: type, record_id: Any, name: str) -> Any:
    obj = db.query(model).filter(model.id == record_id).first()
    if obj is None:
        raise HTTPException(status_code=404, detail=f"{name} not found")
    return obj
```

### Codemod strategy

All replacements are mechanical search-and-replace. No logic changes.

**Pattern 1 — model `default=` lambda:**
```
# Before
default=lambda: datetime.now(timezone.utc).replace(tzinfo=None)
# After
default=utc_now
```
Import `from app.utils.time import utc_now` at file top; remove `lambda:` and the expression.

**Pattern 2 — inline `utc_now` call:**
```
# Before
now = datetime.now(timezone.utc).replace(tzinfo=None)
# After
now = utc_now()
```

**Pattern 3 — `to_utc_naive` call:**
```
# Before
day_start_utc = day_start_et.astimezone(timezone.utc).replace(tzinfo=None)
# After
day_start_utc = to_utc_naive(day_start_et)
```

**Pattern 4 — `get_or_404`:**
```
# Before
s = db.query(TradingStrategy).filter(TradingStrategy.id == strategy_id).first()
if not s:
    raise HTTPException(status_code=404, detail="Strategy not found.")
# After
s = get_or_404(db, TradingStrategy, strategy_id, "Strategy")
```
Note: the detail string trailing period (`.`) and capitalization should match the existing text converted to `"{name} not found"`.

### Files affected (estimated)

| Category | Files | Notes |
|----------|-------|-------|
| Models with `utc_now` default | ~12 model files | `default=utc_now` replacement |
| Services / tasks with inline calls | ~25+ files | `utc_now()` / `to_utc_naive()` |
| Routers with Shape A 404 | 5 files | `auto_trading.py`, `alerts.py`, `universe.py`, `outcomes.py` + 1 more |
| New files | 2 | `utils/time.py`, `utils/db.py` |

No database migration required (no schema changes).

## Alternatives Considered

### Alt 1 — Single `app/utils/time.py` for both helpers + an `app/utils/db.py`

This is the chosen approach. Two files with focused responsibilities, consistent with the existing `app/utils/session.py` pattern.

### Alt 2 — Add helpers to existing `app/utils/session.py`

Rejected. `session.py` covers trading-session classification (pre/regular/post-market detection for America/New_York). Time-normalization is a separate concern. Mixing them makes the file ambiguous and harder to discover.

### Alt 3 — Inline-only replacement (no owning module, just remove duplication)

Rejected. Without an owning module, new callers will re-introduce the pattern within months. The architectural review flagged this as growth-trend; the fix requires ownership.

### Alt 4 — Generalize `get_or_404` to cover all 28 instances (including Shapes B/C/D)

Rejected (per Q&A). Shapes B/C/D don't use the inline `db.query().first()` pattern and can't be cleanly unified under a single signature without adding leaky abstraction. Narrow the helper to Shape A only; other shapes keep their existing handling.

## Open Questions (non-blocking)

- Should `app/utils/__init__.py` re-export `utc_now`, `to_utc_naive`, and `get_or_404` for convenience? Likely yes, but implementor can decide based on import ergonomics in the codemod.
- Should we add unit tests for `utc_now()` and `to_utc_naive()`? These are pure functions — minimal tests would be fast and give confidence during the codemod.

## Assumptions

- **[ASSUMPTION]** The ~100 `utc_now` occurrences and ~96 `to_utc_naive` occurrences can all be replaced mechanically without context-specific exceptions. If any call site requires special handling (e.g., a deliberately naive non-UTC datetime), the implementor flags it.
- **[ASSUMPTION]** `model.id` is the primary key column on every model class targeted by `get_or_404`. All Shape A patterns in routers filter on the PK.
- **[ASSUMPTION]** Shape A 404 instances number ~20 (not all 28); the remainder are Shapes B/C/D. Implementor should grep to confirm before replacing.
