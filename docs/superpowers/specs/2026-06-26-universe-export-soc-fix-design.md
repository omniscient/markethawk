# universe_export.py — Remove HTTPException SoC Leak

**Date:** 2026-06-26
**Issue:** #631 (architecture-audit-v4, Low)
**Status:** Pending review

## Overview

`backend/app/services/universe_export.py` imports `fastapi.HTTPException` and raises it
directly from service code when no tickers are supplied. This is a separation-of-concerns
(SoC) violation: the service layer should speak domain exceptions; HTTP translation belongs
exclusively in the router. The fix is a three-line change that makes the service independently
unit-testable (no FastAPI import chain required).

## Requirements

1. Remove `from fastapi import HTTPException` from `universe_export.py` — the service must
   have zero FastAPI imports after this fix.
2. Replace the `HTTPException(status_code=400, detail="No tickers selected")` at line 59
   with `UniverseValidationError("No tickers selected", universe_id=universe_id)`.
3. Update `export_universe_aggregates` in `routers/universe.py` to catch
   `UniverseValidationError` and convert it to `HTTPException(status_code=400)`, consistent
   with every other handler in that router that raises the same domain error.
4. Add a service-level unit test in `backend/tests/services/test_universe_export_service.py`
   covering:
   - `UniverseNotFoundError` is raised when the universe does not exist.
   - `UniverseValidationError` is raised when `request.tickers` is empty.
   - A valid request returns a `StreamingResponse` (smoke assertion only — CSV/ZIP content
     verification is out of scope for this fix).

## Architecture

### Files changed

| File | Change |
|------|--------|
| `backend/app/services/universe_export.py` | Remove `HTTPException` import; add `UniverseValidationError` import; replace raise site |
| `backend/app/routers/universe.py` | Add `except UniverseValidationError` handler to `export_universe_aggregates` |
| `backend/tests/services/test_universe_export_service.py` | New file — three unit tests using `MagicMock` DB |

### Diff sketch

**`universe_export.py`** (lines 11–15):

```python
# Before
from fastapi import HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
from app.exceptions import UniverseNotFoundError

# After
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
from app.exceptions import UniverseNotFoundError, UniverseValidationError
```

Line 59 (inside `export_aggregates`):

```python
# Before
raise HTTPException(status_code=400, detail="No tickers selected")

# After
raise UniverseValidationError("No tickers selected", universe_id=universe_id)
```

**`routers/universe.py`** (`export_universe_aggregates`, lines 340–343):

```python
# Before
    try:
        return universe_export.export_aggregates(universe_id, request, db)
    except UniverseNotFoundError:
        raise HTTPException(status_code=404, detail="Universe not found")

# After
    try:
        return universe_export.export_aggregates(universe_id, request, db)
    except UniverseNotFoundError:
        raise HTTPException(status_code=404, detail="Universe not found")
    except UniverseValidationError as e:
        raise HTTPException(status_code=400, detail=str(e))
```

### Test template (`test_universe_export_service.py`)

Follows the exact pattern of `backend/tests/services/test_universe_stats_service.py`:
mock the `Session` with `MagicMock`, stub `.query().filter().first()`, and pass a duck-typed
request object so FastAPI is never imported in the test.

## Alternatives Considered

**A. Add a global `MarketHawkError` → HTTP mapping in `main.py` and remove per-handler catches**

Would eliminate boilerplate across all routers, but would change `UniverseValidationError`
from HTTP 400 to HTTP 422 (since `is_retryable=False` maps to 422 in the global handler) and
require auditing every call site. Larger blast radius than warranted for a Low-priority SoC fix.

**B. Raise `ValueError` instead of `UniverseValidationError`**

Keeps the service free of domain-exception imports, but `ValueError` is untyped and bypasses
the structured error context fields (`universe_id`, `is_retryable`) that Seq filtering and the
test suite rely on. `UniverseValidationError` is already the established pattern in
`universe_orchestrator.py`.

**Chosen: C — exact domain-exception swap (selected)**

Minimal diff, consistent with the existing convention in `universe_orchestrator.py`, and
achieves the stated goal (zero FastAPI in the service, HTTP translation in the router only).

## Assumptions

- `UniverseValidationError.__str__` returns the `message` argument unchanged — confirmed by
  reading `app/exceptions.py`: the base `MarketHawkError.__init__` calls `super().__init__(message)`.
- The docstring on `export_aggregates` that says `Raises HTTPException(400)` should be updated
  to say `Raises UniverseValidationError` as part of the same commit.

## Open Questions

- None blocking. The fix is fully specified by the issue and the existing codebase patterns.
