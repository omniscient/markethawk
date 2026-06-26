# Plan: QualityGatePolicy Protocol Interface (#633)

**Date:** 2026-06-26  
**Issue:** #633 — architecture-v4: QualityGatePolicy interface to decouple gate evidence  
**Spec:** `docs/superpowers/specs/2026-06-26-quality-gate-policy-interface-design.md`  
**Branch:** `refine/issue-633-architecture-v4--qualitygatepolicy-inter`

---

## Goal

Add a `QualityGateServiceProtocol` (`typing.Protocol`) so consumers depend on a structural interface, not the concrete `QualityGateService` class. Once merged, adding a new evidence type requires editing only `quality_gate.py` and `quality_gate_evidence.py` — no consumer edit needed.

---

## Architecture

- **Protocol lives in `schemas/quality_gate.py`** (co-located with its return type `QualityGateAssessment`).
- **Concrete class** (`QualityGateService`) satisfies the Protocol structurally; no inheritance required.
- **Singleton** `quality_gate_service: QualityGateServiceProtocol` exported from `services/quality_gate.py` — single stable import target for all consumers.
- **Three consumers** migrated: `services/auto_trade_service.py`, `tasks/scanning.py`, `routers/data_quality.py`.
- `_build_assessment` internal logic is **untouched**.

---

## Tech Stack

Backend: FastAPI + SQLAlchemy (sync) + Pydantic v2 + pytest

---

## File Structure

| File | Change |
|---|---|
| `backend/app/schemas/quality_gate.py` | Add `QualityGateServiceProtocol` |
| `backend/app/services/quality_gate.py` | Remove `@staticmethod`, add singleton |
| `backend/app/services/auto_trade_service.py` | Swap import + call site |
| `backend/app/tasks/scanning.py` | Swap import + call site |
| `backend/app/routers/data_quality.py` | Swap import + call site |
| `backend/tests/services/test_quality_gate_service.py` | Update 8 direct `QualityGateService.assess(...)` calls to use singleton |
| `backend/tests/services/test_auto_trade_service.py` | Update `GATE_PATCH` constant |
| `backend/tests/api/test_data_quality.py` | Update 5 patch targets |

---

## Implementation Notes

**Re: spec requirement 6 ("existing tests must continue to pass without modification")**  
Three test files need patch-target updates as a direct consequence of the consumer migration
(requirements 2 and 4):

- `test_quality_gate_service.py`: 8 calls like `QualityGateService.assess(db=..., request=...)` — after removing `@staticmethod`, Python raises `TypeError: missing 1 required argument: 'self'`. Fix: use `quality_gate_service.assess(...)`.
- `test_data_quality.py` (5 sites) and `test_auto_trade_service.py` (1 site): patch `QualityGateService.assess` at the consumer's module namespace — after consumer migration, `QualityGateService` is no longer imported there. Fix: update to patch `quality_gate_service.assess` at the consumer namespace.
- `test_scanning_tasks.py` patches `"app.services.quality_gate.QualityGateService.assess"` at the *source* module, which still works after the migration because patching the class attribute is resolved via the instance's MRO — **no change needed** there.

These test changes preserve exact test behavior; only the import-path strings and method binding change.

---

## Task 1: Protocol + singleton in `schemas/` and `services/quality_gate.py`

**Files:** `schemas/quality_gate.py`, `services/quality_gate.py`, `tests/services/test_quality_gate_service.py`

### Step 1.1 — Write the failing protocol test

Add to `backend/tests/services/test_quality_gate_service.py` (after existing imports, before first test):

```python
def test_quality_gate_service_satisfies_protocol():
    """Verify the singleton is an instance of the Protocol (runtime_checkable)."""
    from app.schemas.quality_gate import QualityGateServiceProtocol
    from app.services.quality_gate import quality_gate_service

    assert isinstance(quality_gate_service, QualityGateServiceProtocol)
```

### Step 1.2 — Verify it fails

```bash
docker-compose exec backend python -m pytest backend/tests/services/test_quality_gate_service.py::test_quality_gate_service_satisfies_protocol -x 2>&1 | tail -10
```

Expected: `ImportError: cannot import name 'QualityGateServiceProtocol'`

### Step 1.3 — Add `QualityGateServiceProtocol` to `schemas/quality_gate.py`

Locate the existing imports block and add `TYPE_CHECKING, Protocol, runtime_checkable` to the `typing` import. Then append the Protocol class after `QualityGateAssessment`:

```python
# At the top of backend/app/schemas/quality_gate.py — update the typing import:
from typing import TYPE_CHECKING, Any, Dict, List, Literal, Optional, Protocol, runtime_checkable

if TYPE_CHECKING:
    from sqlalchemy.orm import Session
```

```python
# Append after the QualityGateAssessment class definition:

@runtime_checkable
class QualityGateServiceProtocol(Protocol):
    """Structural interface for the quality gate service.

    Consumers import this from schemas/ and the singleton from services/quality_gate.py.
    No inheritance required — QualityGateService satisfies this structurally.
    runtime_checkable enables isinstance() guards in tests.
    """

    def assess(
        self,
        db: "Session",
        request: Any,
    ) -> "QualityGateAssessment": ...
```

### Step 1.4 — Convert `@staticmethod` to instance method and add singleton in `services/quality_gate.py`

In `backend/app/services/quality_gate.py`, change the class definition:

```python
# Before:
class QualityGateService:
    @staticmethod
    def assess(
        db: Session,
        request,
    ) -> QualityGateAssessment:
        ...

# After (remove @staticmethod, add self parameter — zero logic change):
class QualityGateService:
    def assess(
        self,
        db: Session,
        request,
    ) -> QualityGateAssessment:
        ...
```

Then append the module-level singleton at the **bottom** of `services/quality_gate.py` (after the class definition):

```python
# Module-level singleton — consumers import this, not QualityGateService.
quality_gate_service: "QualityGateServiceProtocol" = QualityGateService()
```

The type annotation uses a string literal to defer the forward reference (the Protocol is defined in schemas/).

### Step 1.5 — Update existing direct `QualityGateService.assess(...)` calls in `test_quality_gate_service.py`

Eight test functions call `QualityGateService.assess(db=mock_db, request=body)` as an unbound static call. After removing `@staticmethod`, these raise `TypeError`. Replace every occurrence with the singleton:

```python
# Before (8 occurrences — search: QualityGateService.assess(db=):
from app.services.quality_gate import QualityGateService
...
result = QualityGateService.assess(db=mock_db, request=body)

# After — use the singleton (already exported from services/quality_gate.py):
from app.services.quality_gate import quality_gate_service
...
result = quality_gate_service.assess(db=mock_db, request=body)
```

The affected tests are:
- `test_assess_wrapper_with_complete_report`
- `test_assess_wrapper_missing_report_strict`
- `test_assess_wrapper_incomplete_report_strict`
- `test_assess_backtesting_consumer_emits_survivorship_blocker`
- `test_assess_scorecard_consumer_emits_survivorship_blocker`
- `test_assess_scanner_consumer_no_survivorship`
- `test_assess_advisory_backtesting_consumer_is_warning`
- (any remaining occurrences — `grep -n 'QualityGateService.assess' backend/tests/services/test_quality_gate_service.py`)

Each test also has `from app.services.quality_gate import QualityGateService` at its top — change to `from app.services.quality_gate import quality_gate_service` (or add the singleton import alongside, since some tests may still reference `QualityGateService` for other reasons).

### Step 1.6 — Run the full quality-gate test file

```bash
docker-compose exec backend python -m pytest backend/tests/services/test_quality_gate_service.py -x -q 2>&1 | tail -20
```

Expected: All tests pass, including the new protocol test.

### Step 1.7 — Commit

```bash
git add \
  backend/app/schemas/quality_gate.py \
  backend/app/services/quality_gate.py \
  backend/tests/services/test_quality_gate_service.py
git commit -m "feat(#633): add QualityGateServiceProtocol and singleton to schemas+services"
```

---

## Task 2: Migrate `services/auto_trade_service.py`

**Files:** `services/auto_trade_service.py`, `tests/services/test_auto_trade_service.py`

### Step 2.1 — Update `GATE_PATCH` in `test_auto_trade_service.py` (TDD first)

In `backend/tests/services/test_auto_trade_service.py`, line 31:

```python
# Before:
GATE_PATCH = "app.services.auto_trade_service.QualityGateService.assess"

# After:
GATE_PATCH = "app.services.auto_trade_service.quality_gate_service.assess"
```

### Step 2.2 — Verify tests fail

```bash
docker-compose exec backend python -m pytest backend/tests/services/test_auto_trade_service.py -x -q 2>&1 | tail -15
```

Expected: `AttributeError: <module 'app.services.auto_trade_service'> does not have the attribute 'quality_gate_service'`

### Step 2.3 — Migrate import and call site in `auto_trade_service.py`

In `backend/app/services/auto_trade_service.py`:

```python
# Line 41 — before:
from app.services.quality_gate import QualityGateService

# Line 41 — after:
from app.services.quality_gate import quality_gate_service
```

```python
# Line 189 — before:
assessment = QualityGateService.assess(db, _gate_req)

# Line 189 — after:
assessment = quality_gate_service.assess(db, _gate_req)
```

### Step 2.4 — Verify tests pass

```bash
docker-compose exec backend python -m pytest backend/tests/services/test_auto_trade_service.py -x -q 2>&1 | tail -10
```

Expected: All tests pass.

### Step 2.5 — Commit

```bash
git add \
  backend/app/services/auto_trade_service.py \
  backend/tests/services/test_auto_trade_service.py
git commit -m "feat(#633): migrate auto_trade_service to quality_gate_service singleton"
```

---

## Task 3: Migrate `tasks/scanning.py`

**Files:** `tasks/scanning.py` only — no test changes needed (see note below)

> **Note:** `test_scanning_tasks.py` patches `"app.services.quality_gate.QualityGateService.assess"` at the *source* module. Patching the class attribute via `unittest.mock.patch` replaces it with a `MagicMock` (not a descriptor), so when the running code accesses `quality_gate_service.assess`, Python's MRO finds the mock on the class and returns it as-is. This means the existing test works unchanged after the consumer migration.

### Step 3.1 — Verify tests currently pass (baseline)

```bash
docker-compose exec backend python -m pytest backend/tests/tasks/test_scanning_tasks.py -x -q 2>&1 | tail -10
```

Expected: Pass.

### Step 3.2 — Migrate import and call site in `scanning.py`

In `backend/app/tasks/scanning.py`:

```python
# Line 16 — before:
from app.services.quality_gate import QualityGateService

# Line 16 — after:
from app.services.quality_gate import quality_gate_service
```

```python
# Line 312 — before:
_assessment = QualityGateService.assess(db, _gate_req)

# Line 312 — after:
_assessment = quality_gate_service.assess(db, _gate_req)
```

### Step 3.3 — Verify tests still pass

```bash
docker-compose exec backend python -m pytest backend/tests/tasks/test_scanning_tasks.py -x -q 2>&1 | tail -10
```

Expected: All tests pass (patch at source level resolves through MRO).

### Step 3.4 — Commit

```bash
git add backend/app/tasks/scanning.py
git commit -m "feat(#633): migrate tasks/scanning to quality_gate_service singleton"
```

---

## Task 4: Migrate `routers/data_quality.py`

**Files:** `routers/data_quality.py`, `tests/api/test_data_quality.py`

### Step 4.1 — Update patch targets in `test_data_quality.py` (TDD first)

In `backend/tests/api/test_data_quality.py`, there are 5 `patch(...)` calls:

```python
# Before (5 occurrences):
"app.routers.data_quality.QualityGateService.assess"

# After:
"app.routers.data_quality.quality_gate_service.assess"
```

Replace all 5 occurrences. They appear in:
- `test_gate_trusted`
- `test_gate_warning`
- `test_gate_blocked`
- `test_gate_skipped`
- `test_gate_unknown_universe` (or similar — check file for exact names)

Verify: `grep -c 'QualityGateService.assess' backend/tests/api/test_data_quality.py` → should return 0 after the replacement.

### Step 4.2 — Verify tests fail

```bash
docker-compose exec backend python -m pytest backend/tests/api/test_data_quality.py -x -q 2>&1 | tail -15
```

Expected: `AttributeError: <module 'app.routers.data_quality'> does not have the attribute 'quality_gate_service'`

### Step 4.3 — Migrate import and call site in `data_quality.py`

In `backend/app/routers/data_quality.py`:

```python
# Line 18 — before:
from app.services.quality_gate import QualityGateService

# Line 18 — after:
from app.services.quality_gate import quality_gate_service
```

```python
# Line 33 — before:
return QualityGateService.assess(db, body)

# Line 33 — after:
return quality_gate_service.assess(db, body)
```

Also update the module docstring to reference `quality_gate_service` instead of `QualityGateService.assess()`:

```python
# Before (line 7):
# delegates entirely to QualityGateService.assess() — no policy logic here.

# After:
# delegates entirely to quality_gate_service.assess() — no policy logic here.
```

### Step 4.4 — Verify tests pass

```bash
docker-compose exec backend python -m pytest backend/tests/api/test_data_quality.py -x -q 2>&1 | tail -10
```

Expected: All tests pass.

### Step 4.5 — Full backend test suite regression

```bash
docker-compose exec backend python -m pytest backend/tests/ -x -q 2>&1 | tail -20
```

Expected: All tests pass. No regressions.

### Step 4.6 — Verify structural conformance (smoke check)

```bash
docker-compose exec backend python - <<'EOF'
from app.schemas.quality_gate import QualityGateServiceProtocol
from app.services.quality_gate import quality_gate_service, QualityGateService
assert isinstance(quality_gate_service, QualityGateServiceProtocol), "singleton does not satisfy Protocol"
assert isinstance(quality_gate_service, QualityGateService), "singleton is not a QualityGateService"
print("OK — singleton satisfies QualityGateServiceProtocol structurally")
EOF
```

Expected output: `OK — singleton satisfies QualityGateServiceProtocol structurally`

### Step 4.7 — Confirm backend reloaded and hit the gate endpoint

```bash
docker-compose logs backend --tail=5
curl -s -X POST http://localhost:8000/api/v1/data-quality/gate \
  -H "Content-Type: application/json" \
  -d '{"universe_id": 1, "policy": "off", "consumer": "scanner"}' | python3 -m json.tool
```

Expected: JSON response with `"verdict": "skipped"` (policy=off short-circuits).

### Step 4.8 — Commit

```bash
git add \
  backend/app/routers/data_quality.py \
  backend/tests/api/test_data_quality.py
git commit -m "feat(#633): migrate data_quality router to quality_gate_service singleton"
```

---

## Verification Checklist

- [ ] `QualityGateServiceProtocol` in `schemas/quality_gate.py` with `runtime_checkable`
- [ ] `QualityGateService.assess` is an instance method (no `@staticmethod`)
- [ ] `quality_gate_service` singleton exported from `services/quality_gate.py`
- [ ] All 3 consumers import `quality_gate_service`, not `QualityGateService`
- [ ] `isinstance(quality_gate_service, QualityGateServiceProtocol)` is `True` at runtime
- [ ] `_build_assessment` body unchanged
- [ ] Full test suite green (`pytest backend/tests/ -x -q`)
- [ ] No new `QualityGateService.assess` call sites introduced
