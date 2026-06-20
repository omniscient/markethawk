# Plan: Data Quality Gate Preflight API (#493)

**Date:** 2026-06-20
**Issue:** #493
**Spec:** docs/superpowers/specs/2026-06-19-data-quality-gate-preflight-api-design.md
**Blocked by:** #492 (Add reusable data quality gate contract and service)
**Goal:** Expose `QualityGateService` (from #492) via a thin `POST /api/v1/data-quality/gate` HTTP endpoint. Any caller — frontend, Celery task, or external tooling — can invoke it over the API to request a trust assessment before executing a workflow.

---

## Architecture

```
POST /api/v1/data-quality/gate
  └─ backend/app/routers/data_quality.py
       ├─ validate request (Pydantic, 422 on bad enum/structure)
       ├─ get_or_404(db, StockUniverse, body.universe_id, "Universe")  → 404 if missing
       └─ QualityGateService.assess(db, body)   ← imported from #492
            └─ returns QualityGateAssessment
```

**No Redis caching** — the operation is cheap (single indexed `UniverseQualityReport` read). Caching would require keying on `(universe_id, policy, consumer, serialized_requirements, date_range)` with invalidation wired to `tasks/quality.py`; deferred to a follow-up.

---

## Tech Stack

FastAPI router · Pydantic v2 schemas · SlowAPI rate limiting (`SCANNER_LIMIT = "5/minute"`) · `get_or_404` utility · pytest integration tests with transaction-rollback `db` fixture.

---

## Dependency Check (Pre-implementation)

Before starting Task 1, verify that #492 is merged:

```bash
ls backend/app/services/quality_gate.py
# Must exist with QualityGateService.assess()
```

If this file does not exist, **stop and wait for #492 to be merged**. Do not create stub implementations — that would duplicate #492's work.

Also locate the `QualityGateAssessment` schema from #492 (expected at `backend/app/schemas/quality_gate.py` or similar). Note the exact import path for use in Task 2.

---

## File Structure

| File | Change |
|------|--------|
| `backend/app/schemas/data_quality.py` | **New** — `TimespanRequirement`, `DataRequirements`, `GateRequest` |
| `backend/app/routers/data_quality.py` | **New** — `POST /api/v1/data-quality/gate` router |
| `backend/app/routers/__init__.py` | Add `data_quality_router` import and `__all__` entry |
| `backend/app/main.py` | Import `data_quality_router`; call `app.include_router(data_quality_router)` |
| `backend/tests/api/test_data_quality.py` | **New** — 8 integration tests covering all verdict paths and validation errors |

---

## Task 1: Pydantic request schemas

**Files:** `backend/app/schemas/data_quality.py`, `backend/tests/api/test_data_quality.py`

### Step 1 — Write failing import test

Create `backend/tests/api/test_data_quality.py` with a minimal import smoke-test:

```python
import os

os.environ.setdefault("RATE_LIMITING_ENABLED", "false")
os.environ.setdefault("DATABASE_URL", "postgresql://test:test@localhost/test")
os.environ.setdefault("POLYGON_API_KEY", "test-key-for-unit-tests-only")
os.environ.setdefault("JWT_SECRET_KEY", "test-secret-key-for-unit-tests-only-32chars!")

from app.core.config import get_settings

get_settings.cache_clear()

import importlib


def test_schemas_importable():
    mod = importlib.import_module("app.schemas.data_quality")
    assert hasattr(mod, "TimespanRequirement")
    assert hasattr(mod, "DataRequirements")
    assert hasattr(mod, "GateRequest")
```

### Step 2 — Verify failure

```bash
cd backend && python -m pytest tests/api/test_data_quality.py::test_schemas_importable -x
# Expected: ModuleNotFoundError — app.schemas.data_quality does not exist
```

### Step 3 — Implement schemas

Create `backend/app/schemas/data_quality.py`:

```python
from datetime import date
from typing import List, Literal, Optional

from pydantic import BaseModel, ConfigDict


class TimespanRequirement(BaseModel):
    model_config = ConfigDict(extra="forbid")
    timespan: Literal["minute", "hour", "day", "week", "month"]
    multiplier: int = 1


class DataRequirements(BaseModel):
    model_config = ConfigDict(extra="forbid")
    timespans: Optional[List[TimespanRequirement]] = None


class GateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    universe_id: int
    policy: Literal["strict", "advisory", "off"]
    consumer: Literal["scanner", "auto_trading", "backtesting", "scorecard", "ui"]
    scanner_type: Optional[str] = None
    ticker: Optional[str] = None
    start_date: Optional[date] = None
    end_date: Optional[date] = None
    requirements: Optional[DataRequirements] = None
```

`extra="forbid"` matches the existing `StockUniverseCreate` pattern and satisfies the spec's "invalid structure returns HTTP 422" requirement.

### Step 4 — Verify test passes

```bash
python -m pytest tests/api/test_data_quality.py::test_schemas_importable -x
# Expected: PASSED
```

### Step 5 — Commit

```bash
git add backend/app/schemas/data_quality.py backend/tests/api/test_data_quality.py
git commit -m "feat: add data quality gate request schemas (#493)"
```

---

## Task 2: Router — `POST /api/v1/data-quality/gate`

**Files:** `backend/app/routers/data_quality.py`, `backend/app/routers/__init__.py`, `backend/app/main.py`

### Step 1 — Write failing route test

Append to `backend/tests/api/test_data_quality.py`:

```python
import pytest
from fastapi.testclient import TestClient
from unittest.mock import patch
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.main import app
from app.models.stock_universe import StockUniverse

client = TestClient(app)


@pytest.fixture(autouse=True)
def override_get_db(db):
    app.dependency_overrides[get_db] = lambda: db
    yield
    app.dependency_overrides.clear()


def _seed_universe(db: Session) -> int:
    u = StockUniverse(name="Test Universe", criteria={}, is_active=True)
    db.add(u)
    db.flush()
    return u.id


def test_gate_route_registered(db: Session):
    """POST /api/v1/data-quality/gate is registered (not 404)."""
    uid = _seed_universe(db)
    with patch("app.routers.data_quality.QualityGateService") as mock_svc:
        mock_svc.assess.return_value = {"verdict": "skipped", "trusted": True}
        r = client.post(
            "/api/v1/data-quality/gate",
            json={"universe_id": uid, "policy": "off", "consumer": "scanner"},
        )
    assert r.status_code != 404
```

### Step 2 — Verify failure

```bash
python -m pytest tests/api/test_data_quality.py::test_gate_route_registered -x
# Expected: 404 — route not registered
```

### Step 3 — Create router

Create `backend/app/routers/data_quality.py`:

```python
from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.rate_limits import SCANNER_LIMIT, limiter
from app.models.stock_universe import StockUniverse
from app.schemas.data_quality import GateRequest
from app.services.quality_gate import QualityGateService  # from #492
from app.utils.db import get_or_404

router = APIRouter(prefix="/api/v1/data-quality", tags=["data-quality"])


@router.post("/gate")
@limiter.limit(SCANNER_LIMIT)
def preflight_gate(
    http_request: Request,
    body: GateRequest,
    db: Session = Depends(get_db),
):
    """Return a trust assessment for a universe before running a workflow."""
    get_or_404(db, StockUniverse, body.universe_id, "Universe")
    return QualityGateService.assess(db, body)
```

The `http_request: Request` parameter is required by SlowAPI — it must be the first positional argument for `@limiter.limit()` to extract the key. This matches the `analyze-quality` sibling in `universe.py`.

### Step 4 — Register in `routers/__init__.py`

In `backend/app/routers/__init__.py`, add after the existing imports:

```python
from app.routers.data_quality import router as data_quality_router
```

And add `"data_quality_router"` to `__all__`:

```python
__all__ = [
    "backtest_router",
    "data_quality_router",   # add this line
    "health_router",
    ...
]
```

### Step 5 — Register in `main.py`

In `backend/app/main.py`, add `data_quality_router` to the import from `app.routers`:

```python
from app.routers import (
    alerts_router,
    auth_router,
    auto_trading_router,
    backtest_router,
    data_quality_router,   # add this line
    futures_router,
    ...
)
```

Then add to the `include_router` block in `create_app()`:

```python
app.include_router(data_quality_router)
```

Place it near `universe_router` for logical grouping.

### Step 6 — Verify test passes

```bash
python -m pytest tests/api/test_data_quality.py::test_gate_route_registered -x
# Expected: PASSED
```

### Step 7 — Commit

```bash
git add backend/app/routers/data_quality.py backend/app/routers/__init__.py backend/app/main.py
git commit -m "feat: register POST /api/v1/data-quality/gate router (#493)"
```

---

## Task 3: Full integration test suite (8 tests)

**Files:** `backend/tests/api/test_data_quality.py`

Replace the contents of `backend/tests/api/test_data_quality.py` with the complete test suite. The `inject_auth_into_module_client` fixture in `tests/api/conftest.py` auto-injects the JWT cookie and `X-Requested-With: XMLHttpRequest` header on the module-level `client` — no per-test auth setup needed.

`QualityGateService.assess()` is patched at the router module's reference point (`app.routers.data_quality.QualityGateService`) so the router's thin delegation is tested without depending on #492's logic.

### Step 1 — Write all 8 tests

Replace `backend/tests/api/test_data_quality.py` with:

```python
"""
Integration tests for POST /api/v1/data-quality/gate.
Uses transaction-rollback db fixture (real PostgreSQL, no mocks for DB layer).
QualityGateService.assess() is patched to isolate router behavior from #492 logic.
"""
import os

os.environ.setdefault("RATE_LIMITING_ENABLED", "false")
os.environ.setdefault("DATABASE_URL", "postgresql://test:test@localhost/test")
os.environ.setdefault("POLYGON_API_KEY", "test-key-for-unit-tests-only")
os.environ.setdefault("JWT_SECRET_KEY", "test-secret-key-for-unit-tests-only-32chars!")

from app.core.config import get_settings

get_settings.cache_clear()

from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.main import app
from app.models.stock_universe import StockUniverse

client = TestClient(app)


@pytest.fixture(autouse=True)
def override_get_db(db):
    app.dependency_overrides[get_db] = lambda: db
    yield
    app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _seed_universe(db: Session) -> int:
    u = StockUniverse(name="Test Universe", criteria={}, is_active=True)
    db.add(u)
    db.flush()
    return u.id


def _assessment(verdict="trusted", trusted=True, policy="strict"):
    return {
        "schema_version": "quality_gate.v1",
        "policy": policy,
        "verdict": verdict,
        "trusted": trusted,
        "scope": {},
        "score": 95.0,
        "grade": "A",
        "issues": [],
        "warnings": [],
        "generated_at": "2026-06-20T00:00:00",
    }


# ---------------------------------------------------------------------------
# Verdict path tests
# ---------------------------------------------------------------------------


def test_gate_trusted(db: Session):
    uid = _seed_universe(db)
    with patch(
        "app.routers.data_quality.QualityGateService.assess",
        return_value=_assessment("trusted", True, "strict"),
    ):
        r = client.post(
            "/api/v1/data-quality/gate",
            json={"universe_id": uid, "policy": "strict", "consumer": "scanner"},
        )
    assert r.status_code == 200
    body = r.json()
    assert body["verdict"] == "trusted"
    assert body["trusted"] is True


def test_gate_warning(db: Session):
    uid = _seed_universe(db)
    with patch(
        "app.routers.data_quality.QualityGateService.assess",
        return_value=_assessment("warning", False, "advisory"),
    ):
        r = client.post(
            "/api/v1/data-quality/gate",
            json={"universe_id": uid, "policy": "advisory", "consumer": "ui"},
        )
    assert r.status_code == 200
    body = r.json()
    assert body["verdict"] == "warning"
    assert body["trusted"] is False


def test_gate_blocked(db: Session):
    uid = _seed_universe(db)
    with patch(
        "app.routers.data_quality.QualityGateService.assess",
        return_value=_assessment("blocked", False, "strict"),
    ):
        r = client.post(
            "/api/v1/data-quality/gate",
            json={"universe_id": uid, "policy": "strict", "consumer": "auto_trading"},
        )
    assert r.status_code == 200
    body = r.json()
    assert body["verdict"] == "blocked"
    assert body["trusted"] is False


def test_gate_skipped(db: Session):
    uid = _seed_universe(db)
    with patch(
        "app.routers.data_quality.QualityGateService.assess",
        return_value=_assessment("skipped", True, "off"),
    ):
        r = client.post(
            "/api/v1/data-quality/gate",
            json={"universe_id": uid, "policy": "off", "consumer": "backtesting"},
        )
    assert r.status_code == 200
    body = r.json()
    assert body["verdict"] == "skipped"
    assert body["trusted"] is True


# ---------------------------------------------------------------------------
# Validation error tests (no service mock needed — Pydantic rejects before route)
# ---------------------------------------------------------------------------


def test_gate_invalid_policy(db: Session):
    uid = _seed_universe(db)
    r = client.post(
        "/api/v1/data-quality/gate",
        json={"universe_id": uid, "policy": "invalid", "consumer": "scanner"},
    )
    assert r.status_code == 422


def test_gate_invalid_consumer(db: Session):
    uid = _seed_universe(db)
    r = client.post(
        "/api/v1/data-quality/gate",
        json={"universe_id": uid, "policy": "strict", "consumer": "unknown"},
    )
    assert r.status_code == 422


def test_gate_invalid_timespan(db: Session):
    uid = _seed_universe(db)
    r = client.post(
        "/api/v1/data-quality/gate",
        json={
            "universe_id": uid,
            "policy": "strict",
            "consumer": "scanner",
            "requirements": {"timespans": [{"timespan": "tick"}]},
        },
    )
    assert r.status_code == 422


# ---------------------------------------------------------------------------
# 404 test (no service mock needed — get_or_404 fires before assess())
# ---------------------------------------------------------------------------


def test_gate_universe_not_found(db: Session):
    r = client.post(
        "/api/v1/data-quality/gate",
        json={"universe_id": 999999, "policy": "strict", "consumer": "scanner"},
    )
    assert r.status_code == 404
    assert "Universe" in r.json()["detail"]
```

### Step 2 — Verify all tests fail before implementation (route is not yet registered)

```bash
python -m pytest tests/api/test_data_quality.py -x --tb=short 2>&1 | head -30
# Expected: tests fail because route is not registered or QualityGateService import fails
```

### Step 3 — Run full test suite after Tasks 1 and 2 are complete

After Tasks 1 and 2 are done (router created and registered):

```bash
python -m pytest tests/api/test_data_quality.py -v
```

Expected output:

```
tests/api/test_data_quality.py::test_gate_trusted PASSED
tests/api/test_data_quality.py::test_gate_warning PASSED
tests/api/test_data_quality.py::test_gate_blocked PASSED
tests/api/test_data_quality.py::test_gate_skipped PASSED
tests/api/test_data_quality.py::test_gate_invalid_policy PASSED
tests/api/test_data_quality.py::test_gate_invalid_consumer PASSED
tests/api/test_data_quality.py::test_gate_invalid_timespan PASSED
tests/api/test_data_quality.py::test_gate_universe_not_found PASSED

8 passed in ...
```

### Step 4 — Run adjacent test suites to verify no regressions

```bash
python -m pytest tests/api/test_scanner.py tests/api/test_outcomes.py -v --tb=short
# Expected: all previously passing tests still pass
```

### Step 5 — Commit

```bash
git add backend/tests/api/test_data_quality.py
git commit -m "test: integration tests for POST /api/v1/data-quality/gate (#493)"
```

---

## Validation Before Final Commit

1. Confirm the backend reloaded cleanly:
   ```bash
   docker-compose logs backend --tail=10
   # Expected: no import errors
   ```

2. Hit the endpoint with curl to verify correct routing:
   ```bash
   # This will 401 (no auth cookie) — confirms the route exists and is not 404
   curl -s -X POST http://localhost:8000/api/v1/data-quality/gate \
     -H "Content-Type: application/json" \
     -d '{"universe_id": 1, "policy": "off", "consumer": "scanner"}' | python -m json.tool
   # Expected: {"detail": "Not authenticated"} — route is live, auth middleware fires
   ```

3. Verify TypeScript frontend build is unaffected:
   ```bash
   cd frontend && npx tsc --noEmit
   # Expected: no errors (no frontend changes in this issue)
   ```

4. Run full test suite one final time:
   ```bash
   cd backend && python -m pytest tests/api/test_data_quality.py -v
   # Expected: 8 passed
   ```
