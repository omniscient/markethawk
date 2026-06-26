# Plan: universe_export.py — Remove HTTPException SoC Leak

**Issue:** #631
**Date:** 2026-06-26
**Branch:** `refine/issue-631-architecture-v4--universe-export-py-rais`
**Spec:** `docs/superpowers/specs/2026-06-26-universe-export-soc-fix-design.md`

## Goal

Remove `from fastapi import HTTPException` from `backend/app/services/universe_export.py` and replace the lone `raise HTTPException(400)` site with `raise UniverseValidationError(...)`. Add the corresponding `except UniverseValidationError` catch in the router. Add three unit tests.

## Architecture

Service-layer domain exception → router HTTP translation. The pattern is already established in `universe_orchestrator.py` and in the existing `except UniverseNotFoundError` handler in `routers/universe.py`.

## Tech Stack

Backend: FastAPI, SQLAlchemy 2.0 (sync), pytest + `unittest.mock.MagicMock`

## File Structure

| File | Action |
|------|--------|
| `backend/app/services/universe_export.py` | Modify — remove FastAPI import; raise domain exception; update docstring |
| `backend/app/routers/universe.py` | Modify — add `except UniverseValidationError` handler |
| `backend/tests/services/test_universe_export_service.py` | Create — three unit tests |

---

## Task 1 — Write failing tests (TDD: red)

**Files:** `backend/tests/services/test_universe_export_service.py`

### Steps

**Step 1.1 — Create the test file.**

```python
# backend/tests/services/test_universe_export_service.py
from unittest.mock import MagicMock

import pytest


class _Req:
    """Duck-typed stand-in for ExportAggregatesRequest (no FastAPI import needed)."""

    def __init__(
        self,
        tickers,
        timespan="minute",
        multiplier=1,
        from_date=None,
        to_date=None,
        zip_format="per_ticker",
    ):
        self.tickers = tickers
        self.timespan = timespan
        self.multiplier = multiplier
        self.from_date = from_date
        self.to_date = to_date
        self.zip_format = zip_format


def _make_db(first_result):
    """
    Mock Session whose first() returns first_result, all() returns [],
    and iteration yields nothing (empty aggregate rows).
    Follows the pattern in test_universe_stats_service.py.
    """
    db = MagicMock()
    mock_q = MagicMock()
    mock_q.filter.return_value = mock_q
    mock_q.order_by.return_value = mock_q
    mock_q.first.return_value = first_result
    mock_q.all.return_value = []
    mock_q.__iter__ = lambda self: iter([])
    db.query.return_value = mock_q
    return db


def _make_universe(name="TestUniverse"):
    u = MagicMock()
    u.name = name
    return u


class TestExportAggregates:
    def test_universe_not_found_raises_domain_error(self):
        from app.exceptions import UniverseNotFoundError
        from app.services.universe_export import export_aggregates

        with pytest.raises(UniverseNotFoundError):
            export_aggregates(999, _Req(["AAPL"]), _make_db(first_result=None))

    def test_empty_tickers_raises_universe_validation_error(self):
        from app.exceptions import UniverseValidationError
        from app.services.universe_export import export_aggregates

        with pytest.raises(UniverseValidationError):
            export_aggregates(1, _Req([]), _make_db(first_result=_make_universe()))

    def test_valid_request_returns_streaming_response(self):
        from fastapi.responses import StreamingResponse
        from app.services.universe_export import export_aggregates

        response = export_aggregates(
            1, _Req(["AAPL"]), _make_db(first_result=_make_universe())
        )
        assert isinstance(response, StreamingResponse)
```

**Step 1.2 — Verify the tests exist and two of three fail (pre-fix baseline).**

Run inside the backend container:

```bash
docker-compose exec backend python -m pytest backend/tests/services/test_universe_export_service.py -v 2>&1 | tail -20
```

Expected output: `test_universe_not_found_raises_domain_error` PASSED (already works), `test_empty_tickers_raises_universe_validation_error` FAILED (service raises `HTTPException` not `UniverseValidationError`), `test_valid_request_returns_streaming_response` PASSED (the happy path still works). Confirm at least one failure before proceeding.

**Step 1.3 — Commit the failing tests.**

```bash
git add backend/tests/services/test_universe_export_service.py
git commit -m "test(universe-export): add failing unit tests for SoC fix (#631)"
```

---

## Task 2 — Fix `universe_export.py` (TDD: green)

**Files:** `backend/app/services/universe_export.py`

### Steps

**Step 2.1 — Update imports: remove `HTTPException`, add `UniverseValidationError`.**

Current lines 11–15:

```python
from fastapi import HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.exceptions import UniverseNotFoundError
```

Replace with:

```python
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.exceptions import UniverseNotFoundError, UniverseValidationError
```

**Step 2.2 — Replace the raise site (line 59).**

Current:

```python
    if not tickers:
        raise HTTPException(status_code=400, detail="No tickers selected")
```

Replace with:

```python
    if not tickers:
        raise UniverseValidationError("No tickers selected", universe_id=universe_id)
```

**Step 2.3 — Update the docstring on `export_aggregates` to reflect the new exception.**

Current line 51:

```
    Raises HTTPException(400) if no tickers are provided.
```

Replace with:

```
    Raises UniverseValidationError if no tickers are provided.
```

**Step 2.4 — Verify the file has zero FastAPI imports.**

```bash
grep -n "from fastapi import\|import fastapi" backend/app/services/universe_export.py
```

Expected output: empty (no matches). If any match appears, the SoC violation is still present — fix before continuing.

**Step 2.5 — Run the tests; all three must pass.**

```bash
docker-compose exec backend python -m pytest backend/tests/services/test_universe_export_service.py -v
```

Expected: `3 passed`.

**Step 2.6 — Confirm the backend reloaded without errors.**

```bash
docker-compose logs backend --tail=10
```

Expected: hot-reload message; no `ImportError` or `AttributeError`.

**Step 2.7 — Commit.**

```bash
git add backend/app/services/universe_export.py
git commit -m "fix(universe-export): remove HTTPException SoC leak; raise UniverseValidationError (#631)"
```

---

## Task 3 — Update the router to catch `UniverseValidationError`

**Files:** `backend/app/routers/universe.py`

### Steps

**Step 3.1 — Add the `except UniverseValidationError` handler.**

Current `export_universe_aggregates` handler (lines 340–343):

```python
    try:
        return universe_export.export_aggregates(universe_id, request, db)
    except UniverseNotFoundError:
        raise HTTPException(status_code=404, detail="Universe not found")
```

Replace with:

```python
    try:
        return universe_export.export_aggregates(universe_id, request, db)
    except UniverseNotFoundError:
        raise HTTPException(status_code=404, detail="Universe not found")
    except UniverseValidationError as e:
        raise HTTPException(status_code=400, detail=str(e))
```

Note: `UniverseValidationError` is already imported at line 14 of `routers/universe.py` (`from app.exceptions import UniverseNotFoundError, UniverseValidationError`) — no import change needed.

**Step 3.2 — Verify import is present (no change needed but confirm).**

```bash
grep "UniverseValidationError" backend/app/routers/universe.py
```

Expected: two matches — the import line and the new `except` clause.

**Step 3.3 — Smoke-test the endpoint with `curl`.**

```bash
# Should return 400 with "No tickers selected"
curl -s -X POST http://localhost:8000/api/universes/1/export-aggregates \
  -H "Content-Type: application/json" \
  -d '{"tickers": [], "timespan": "minute", "multiplier": 1, "from_date": null, "to_date": null, "zip_format": "per_ticker"}' \
  | python -m json.tool
```

Expected response body: `{"detail": "No tickers selected [universe_id=1]"}` with HTTP 400.
(Note: `MarketHawkError.__str__` appends context fields, so `str(e)` renders as `"No tickers selected [universe_id=1]"` — this is intentional and matches the existing handler behavior at line 486 of the same router.)

```bash
# Should return 404 for a non-existent universe
curl -s -o /dev/null -w "%{http_code}" -X POST \
  http://localhost:8000/api/universes/99999/export-aggregates \
  -H "Content-Type: application/json" \
  -d '{"tickers": ["AAPL"], "timespan": "minute", "multiplier": 1, "from_date": null, "to_date": null, "zip_format": "per_ticker"}'
```

Expected: `404`.

**Step 3.4 — Confirm backend still healthy.**

```bash
docker-compose logs backend --tail=10
```

Expected: no errors; hot-reload completed.

**Step 3.5 — Run the full service test suite one final time.**

```bash
docker-compose exec backend python -m pytest backend/tests/services/test_universe_export_service.py -v
```

Expected: `3 passed`.

**Step 3.6 — Commit.**

```bash
git add backend/app/routers/universe.py
git commit -m "fix(universe-router): catch UniverseValidationError → HTTP 400 in export handler (#631)"
```

---

## Memory Notes (baked in from `.archon/memory/backend-patterns.md`)

- The `[AVOID]` about never importing `HTTPException` in service modules (`app/services/`) is the exact violation this plan fixes. Zero FastAPI imports must remain after Task 2.
- Unit tests here use `MagicMock` (following `test_universe_stats_service.py`). The `[AVOID]` about transaction-rollback fixtures applies to full-pipeline integration tests, not these pure service-unit tests.
- The `[AVOID]` about SQLite in-memory confirms `MagicMock` is the right choice here (several models use JSONB columns incompatible with SQLite).
