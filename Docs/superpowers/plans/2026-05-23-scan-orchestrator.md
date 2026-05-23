# Scan Orchestrator with Registry — Implementation Plan

**Date:** 2026-05-23
**Issue:** [#60 — Deepen the Scanner module into a Scan Orchestrator with registry](https://github.com/omniscient/markethawk/issues/60)
**Spec:** [2026-05-23-scan-orchestrator-registry-design.md](../specs/2026-05-23-scan-orchestrator-registry-design.md)

## Goal

Introduce `scan_orchestrator.py` with a `ScannerDescriptor` registry to replace the three-way if/elif dispatch in `tasks.py:run_universe_scan`. Extract shared scanner event persistence out of `ScannerService`, break the circular import between `scanner.py` and `tasks.py`, and expose `GET /api/scanner/types`. The refactor is incremental: `ScannerService` is preserved as a thin delegate shell until Task 8, so no callers break mid-refactor.

## Architecture

```
tasks.py:run_universe_scan
    └── scan_orchestrator.run(scanner_type, tickers, db, event_date)
            ├── pre_market_scan._run()       (registered as "pre_market_volume_spike")
            ├── oversold_bounce_scan._run()  (registered as "oversold_bounce")
            └── liquidity_hunt._run()        (registered as "liquidity_hunt", "liquidity_hunt_pre", "liquidity_hunt_post")

Persistence (all scanner _run() functions call):
    alert_service.save_event()
        └── alert_service.trigger_scanner_alert(event_id)
                └── (deferred) tasks.evaluate_scanner_alerts.delay(event_id)
```

## Tech Stack

Backend only: FastAPI, SQLAlchemy 2.0 (sync Session in Celery tasks), Celery, pytest

## File Structure

| Action | File |
|--------|------|
| Modify | `backend/app/services/alert_service.py` |
| **Create** | `backend/app/services/scan_orchestrator.py` |
| **Create** | `backend/app/services/pre_market_scan.py` |
| **Create** | `backend/app/services/oversold_bounce_scan.py` |
| Modify | `backend/app/services/liquidity_hunt.py` |
| Modify | `backend/app/services/scanner.py` |
| Modify | `backend/app/services/__init__.py` |
| Modify | `backend/app/tasks.py` |
| Modify | `backend/app/routers/scanner.py` |
| **Create** | `backend/tests/services/test_scan_orchestrator.py` |
| Modify | `backend/tests/services/test_liquidity_hunt.py` |
| Modify | `backend/tests/api/test_scanner.py` |

---

## Task 1: Extract `save_event()` and `trigger_scanner_alert()` to `alert_service.py`

**Goal**: Move shared scanner event persistence out of `ScannerService._save_event()` into standalone functions in `alert_service.py`, eliminating the deferred `from app.tasks import evaluate_scanner_alerts` inside `scanner.py`.

**Files**: `backend/app/services/alert_service.py`, `backend/app/services/scanner.py`, `backend/tests/services/test_scanner_refactor.py`

### Step 1.1 — Write the failing tests

Add to `backend/tests/services/test_scanner_refactor.py`:

```python
def test_save_event_importable_from_alert_service():
    from app.services.alert_service import save_event
    assert callable(save_event)


def test_trigger_scanner_alert_importable_from_alert_service():
    from app.services.alert_service import trigger_scanner_alert
    assert callable(trigger_scanner_alert)
```

Run and confirm failure:
```bash
cd backend && python -m pytest tests/services/test_scanner_refactor.py::test_save_event_importable_from_alert_service -xvs
```
Expected: `FAILED` — `ImportError: cannot import name 'save_event' from 'app.services.alert_service'`

### Step 1.2 — Add `trigger_scanner_alert()` to `alert_service.py`

Append to `backend/app/services/alert_service.py`:

```python
def trigger_scanner_alert(event_id: int) -> None:
    """Enqueue alert evaluation for a newly persisted ScannerEvent."""
    from app.tasks import evaluate_scanner_alerts
    evaluate_scanner_alerts.delay(event_id)
```

### Step 1.3 — Add `save_event()` to `alert_service.py`

First, add these imports at the top of `alert_service.py` (after existing imports):

```python
from datetime import date
from typing import Any, Dict, Optional
from sqlalchemy.orm import Session
```

Then add the following standalone function, copying the body of `ScannerService._save_event` (lines 308–376 of `scanner.py`) verbatim, with one change: replace the two lines:

```python
from app.tasks import evaluate_scanner_alerts
evaluate_scanner_alerts.delay(new_event.id)
```

with:

```python
trigger_scanner_alert(new_event.id)
```

The complete function signature in `alert_service.py`:

```python
def save_event(
    db: Session,
    ticker: str,
    event_date: date,
    scanner_type: str,
    indicators: Dict[str, Any],
    criteria_met: Dict[str, Any],
    enrichment: Dict[str, Any],
    previous_close: float = None,
    opening_price: float = None,
    closing_price: float = None,
    ranker_config: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Persist a ScannerEvent and enqueue alert evaluation for new events."""
    # body copied from ScannerService._save_event lines 323–376
    # only change: trigger_scanner_alert(new_event.id) replaces the deferred tasks import
```

### Step 1.4 — Delegate `ScannerService._save_event` to `save_event()`

Replace the body of `ScannerService._save_event` in `backend/app/services/scanner.py` with a thin delegate. The method signature stays identical; only the body changes:

```python
@staticmethod
def _save_event(
    db: Session,
    ticker: str,
    event_date: date,
    scanner_type: str,
    indicators: Dict[str, Any],
    criteria_met: Dict[str, Any],
    enrichment: Dict[str, Any],
    previous_close: float = None,
    opening_price: float = None,
    closing_price: float = None,
    ranker_config: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    from app.services.alert_service import save_event
    return save_event(
        db=db, ticker=ticker, event_date=event_date, scanner_type=scanner_type,
        indicators=indicators, criteria_met=criteria_met, enrichment=enrichment,
        previous_close=previous_close, opening_price=opening_price,
        closing_price=closing_price, ranker_config=ranker_config,
    )
```

The old deferred `from app.tasks import evaluate_scanner_alerts` line that was inside `_save_event` is now gone. The circular import is broken.

### Step 1.5 — Verify and commit

```bash
cd backend && python -m pytest tests/services/test_scanner_refactor.py tests/services/test_liquidity_hunt.py -x
```
Expected: all pass. The 7 `test_liquidity_hunt.py` patches target `app.services.scanner.ScannerService._save_event` — this still intercepts correctly **in Tasks 1–4 only**, because `liquidity_hunt.py` still calls through `ScannerService._save_event`. Once Task 5.2 changes `liquidity_hunt.py` to call `alert_service.save_event` directly, these patches must be updated (Task 5.3). Do not skip Task 5.3.

```bash
git add backend/app/services/alert_service.py backend/app/services/scanner.py backend/tests/services/test_scanner_refactor.py
git commit -m "refactor: extract save_event and trigger_scanner_alert to alert_service, break circular import"
```

---

## Task 2: Create `scan_orchestrator.py`

**Goal**: Implement the orchestrator shell with `_REGISTRY`, `register()`, `get_all()`, and `run()`.

**Files**: `backend/app/services/scan_orchestrator.py` (new), `backend/tests/services/test_scan_orchestrator.py` (new)

### Step 2.1 — Write the failing tests

Create `backend/tests/services/test_scan_orchestrator.py`:

```python
import asyncio
import pytest
from unittest.mock import AsyncMock
from datetime import date

import app.services.scan_orchestrator as orchestrator
from app.services.scan_orchestrator import ScannerDescriptor, register, get_all, run


@pytest.fixture(autouse=True)
def isolated_registry():
    """Snapshot and restore the registry between tests."""
    original = dict(orchestrator._REGISTRY)
    yield
    orchestrator._REGISTRY.clear()
    orchestrator._REGISTRY.update(original)


def test_register_adds_descriptor():
    fn = AsyncMock(return_value=[])
    desc = ScannerDescriptor(key="test", display_name="Test", description="d", run=fn)
    register(desc)
    assert "test" in orchestrator._REGISTRY
    assert orchestrator._REGISTRY["test"] is desc


def test_get_all_includes_registered():
    fn = AsyncMock(return_value=[])
    register(ScannerDescriptor(key="s1", display_name="S1", description="d", run=fn))
    assert any(d.key == "s1" for d in get_all())


def test_run_dispatches_to_registered_fn():
    expected = [{"ticker": "AAPL", "score": 90}]
    fn = AsyncMock(return_value=expected)
    register(ScannerDescriptor(key="mock_scan", display_name="Mock", description="m", run=fn))
    today = date(2026, 5, 23)
    result = asyncio.run(run("mock_scan", ["AAPL"], db=None, event_date=today))
    assert result == expected
    fn.assert_awaited_once_with(["AAPL"], None, today)


def test_run_raises_for_unknown_type():
    with pytest.raises(ValueError, match="Unknown scanner type: 'does_not_exist'"):
        asyncio.run(run("does_not_exist", [], db=None, event_date=date.today()))


def test_scanner_descriptor_is_frozen():
    fn = AsyncMock(return_value=[])
    desc = ScannerDescriptor(key="k", display_name="D", description="d", run=fn)
    with pytest.raises(Exception):  # frozen dataclass raises FrozenInstanceError
        desc.key = "changed"  # type: ignore[misc]


def test_register_returns_descriptor():
    fn = AsyncMock(return_value=[])
    desc = ScannerDescriptor(key="ret", display_name="R", description="d", run=fn)
    returned = register(desc)
    assert returned is desc
```

> The test suite uses the pattern `def test_X(): asyncio.run(coroutine())` rather than `@pytest.mark.asyncio` — confirmed by `test_scanner_refactor.py`, `test_liquidity_hunt.py`, and `test_feature_enrichment.py`. The tests above follow this convention. Do not add `pytest-asyncio` markers.

Run and confirm failure:
```bash
cd backend && python -m pytest tests/services/test_scan_orchestrator.py -xvs
```
Expected: `FAILED` — `ModuleNotFoundError: No module named 'app.services.scan_orchestrator'`

### Step 2.2 — Implement `scan_orchestrator.py`

Create `backend/app/services/scan_orchestrator.py`:

```python
from dataclasses import dataclass
from datetime import date
from typing import Any, Awaitable, Callable

ScannerFn = Callable[[list[str], Any, date], Awaitable[list[dict]]]

_REGISTRY: dict[str, "ScannerDescriptor"] = {}


@dataclass(frozen=True)
class ScannerDescriptor:
    key: str
    display_name: str
    description: str
    run: ScannerFn
    supports_date_range: bool = True


def register(descriptor: ScannerDescriptor) -> ScannerDescriptor:
    _REGISTRY[descriptor.key] = descriptor
    return descriptor


def get_all() -> list[ScannerDescriptor]:
    return list(_REGISTRY.values())


async def run(
    scanner_type: str,
    tickers: list[str],
    db: Any,
    event_date: date,
) -> list[dict]:
    descriptor = _REGISTRY.get(scanner_type)
    if descriptor is None:
        raise ValueError(
            f"Unknown scanner type: {scanner_type!r}. Registered: {list(_REGISTRY)}"
        )
    return await descriptor.run(tickers, db, event_date)
```

### Step 2.3 — Verify and commit

```bash
cd backend && python -m pytest tests/services/test_scan_orchestrator.py -xvs
```
Expected: `6 passed`.

```bash
git add backend/app/services/scan_orchestrator.py backend/tests/services/test_scan_orchestrator.py
git commit -m "feat: add scan_orchestrator with ScannerDescriptor registry"
```

---

## Task 3: Register the pre-market scanner via `pre_market_scan.py`

**Goal**: Create a new module that self-registers the pre-market scanner. The `_run` function delegates to `ScannerService.run_pre_market_scan` for now (body inlined in Task 8).

**Files**: `backend/app/services/pre_market_scan.py` (new), `backend/tests/services/test_scan_orchestrator.py`

### Step 3.1 — Write the failing test

Add to `backend/tests/services/test_scan_orchestrator.py`:

```python
def test_pre_market_scanner_registered():
    import app.services.pre_market_scan  # noqa: F401 — triggers registration
    assert "pre_market_volume_spike" in orchestrator._REGISTRY
    desc = orchestrator._REGISTRY["pre_market_volume_spike"]
    assert desc.display_name == "Pre-Market Volume Spike"
    assert desc.supports_date_range is True
```

Run:
```bash
cd backend && python -m pytest tests/services/test_scan_orchestrator.py::test_pre_market_scanner_registered -xvs
```
Expected: `FAILED` — `ModuleNotFoundError: No module named 'app.services.pre_market_scan'`

### Step 3.2 — Create `pre_market_scan.py`

Create `backend/app/services/pre_market_scan.py`:

```python
from datetime import date
from typing import Any

from app.services.scan_orchestrator import ScannerDescriptor, register


async def _run(tickers: list[str], db: Any, event_date: date) -> list[dict]:
    from app.services.scanner import ScannerService
    return await ScannerService.run_pre_market_scan(tickers, db, event_date=event_date)


register(
    ScannerDescriptor(
        key="pre_market_volume_spike",
        display_name="Pre-Market Volume Spike",
        description="Detects stocks with >4x average volume in the pre-market window.",
        run=_run,
        supports_date_range=True,
    )
)
```

The deferred `from app.services.scanner import ScannerService` inside `_run` prevents a circular import at module load time. In Task 8 this import is eliminated entirely by inlining the function body.

### Step 3.3 — Verify and commit

```bash
cd backend && python -m pytest tests/services/test_scan_orchestrator.py -xvs
```
Expected: all tests pass.

```bash
git add backend/app/services/pre_market_scan.py backend/tests/services/test_scan_orchestrator.py
git commit -m "feat: register pre_market_volume_spike scanner in orchestrator"
```

---

## Task 4: Register the oversold bounce scanner via `oversold_bounce_scan.py`

**Goal**: Mirror Task 3 for the oversold bounce scanner.

**Files**: `backend/app/services/oversold_bounce_scan.py` (new), `backend/tests/services/test_scan_orchestrator.py`

### Step 4.1 — Write the failing test

Add to `backend/tests/services/test_scan_orchestrator.py`:

```python
def test_oversold_bounce_scanner_registered():
    import app.services.oversold_bounce_scan  # noqa: F401
    assert "oversold_bounce" in orchestrator._REGISTRY
    desc = orchestrator._REGISTRY["oversold_bounce"]
    assert desc.display_name == "Oversold Bounce"
    assert desc.supports_date_range is True
```

Run:
```bash
cd backend && python -m pytest tests/services/test_scan_orchestrator.py::test_oversold_bounce_scanner_registered -xvs
```
Expected: `FAILED`

### Step 4.2 — Create `oversold_bounce_scan.py`

Create `backend/app/services/oversold_bounce_scan.py`:

```python
from datetime import date
from typing import Any

from app.services.scan_orchestrator import ScannerDescriptor, register


async def _run(tickers: list[str], db: Any, event_date: date) -> list[dict]:
    from app.services.scanner import ScannerService
    return await ScannerService.run_oversold_bounce_scan(tickers, db, event_date=event_date)


register(
    ScannerDescriptor(
        key="oversold_bounce",
        display_name="Oversold Bounce",
        description="Identifies oversold stocks showing early reversal signals.",
        run=_run,
        supports_date_range=True,
    )
)
```

### Step 4.3 — Verify and commit

```bash
cd backend && python -m pytest tests/services/test_scan_orchestrator.py -xvs
```
Expected: all tests pass.

```bash
git add backend/app/services/oversold_bounce_scan.py backend/tests/services/test_scan_orchestrator.py
git commit -m "feat: register oversold_bounce scanner in orchestrator"
```

---

## Task 5: Migrate `liquidity_hunt.py` to `alert_service.save_event()` and self-register

**Goal**: Replace the `ScannerService._save_event()` calls in `liquidity_hunt.py` with the standalone `save_event()` function (eliminating the `from app.services.scanner import ScannerService` import), then self-register all three liquidity hunt variants. Update the 7 test patches that reference the old path.

**Files**: `backend/app/services/liquidity_hunt.py`, `backend/tests/services/test_liquidity_hunt.py`, `backend/tests/services/test_scan_orchestrator.py`

### Step 5.1 — Write the failing test

Add to `backend/tests/services/test_scan_orchestrator.py`:

```python
def test_liquidity_hunt_variants_registered():
    import app.services.liquidity_hunt  # noqa: F401
    for key in ("liquidity_hunt", "liquidity_hunt_pre", "liquidity_hunt_post"):
        assert key in orchestrator._REGISTRY, f"Expected {key!r} in registry"
```

Run:
```bash
cd backend && python -m pytest tests/services/test_scan_orchestrator.py::test_liquidity_hunt_variants_registered -xvs
```
Expected: `FAILED`

### Step 5.2 — Replace `ScannerService` import in `liquidity_hunt.py`

In `backend/app/services/liquidity_hunt.py`, replace line 29:

```python
# Before
from app.services.scanner import ScannerService

# After
from app.services.alert_service import save_event as _save_event
```

Then do a global find-and-replace throughout the file:

```
ScannerService._save_event(  →  _save_event(
```

All argument names and values remain identical — only the callable prefix changes.

### Step 5.3 — Update the 7 mock patches in `test_liquidity_hunt.py`

In `backend/tests/services/test_liquidity_hunt.py`, replace all 7 occurrences of:

```python
@patch("app.services.scanner.ScannerService._save_event", ...)
```

with:

```python
@patch("app.services.alert_service.save_event", ...)
```

Affected lines: 436, 455, 474, 492, 512, 535, 564.

### Step 5.4 — Self-register all three liquidity hunt variants

Append to the end of `backend/app/services/liquidity_hunt.py`:

```python
from datetime import date
from typing import Any

from app.services.scan_orchestrator import ScannerDescriptor, register


async def _orchestrator_run(tickers: list[str], db: Any, event_date: date) -> list[dict]:
    """Adapter: maps the standard ScannerFn signature to run_liquidity_hunt_scan."""
    return await run_liquidity_hunt_scan(
        tickers=tickers,
        db=db,
        start_date=event_date,
        end_date=event_date,
    )


for _key, _display, _desc in [
    ("liquidity_hunt", "Liquidity Hunt", "Intraday liquidity concentration scanner."),
    ("liquidity_hunt_pre", "Liquidity Hunt (Pre-Market)", "Pre-market liquidity concentration scanner."),
    ("liquidity_hunt_post", "Liquidity Hunt (Post-Market)", "Post-market liquidity concentration scanner."),
]:
    # All three keys share the same _orchestrator_run function object.
    # run_liquidity_hunt_scan emits all three event types regardless of the key passed —
    # the key only affects which ScannerDescriptor the orchestrator dispatches to.
    register(ScannerDescriptor(key=_key, display_name=_display, description=_desc, run=_orchestrator_run, supports_date_range=True))
```

> **Note on `diagnostics_out`**: The old dispatch in `tasks.py` passed `diagnostics_out=day_diag` to `run_liquidity_hunt_scan`. The `ScannerFn` interface does not carry this parameter, so the diagnostics dict will not be populated via the orchestrator path. This is an accepted trade-off per the spec (§Assumptions: "a wrapper function at registration time handles the adaptation").

> **Note on variant behavior**: All three keys (`liquidity_hunt`, `liquidity_hunt_pre`, `liquidity_hunt_post`) invoke the same underlying `run_liquidity_hunt_scan` with `start_date=end_date=event_date`. This matches the previous if/elif behavior (all three dispatched to the same function). The variant keys are distinguished at the DB storage level inside `run_liquidity_hunt_scan`, not at dispatch time.

### Step 5.5 — Verify and commit

```bash
cd backend && python -m pytest tests/services/test_liquidity_hunt.py tests/services/test_scan_orchestrator.py -x
```
Expected: all green.

```bash
git add backend/app/services/liquidity_hunt.py backend/tests/services/test_liquidity_hunt.py backend/tests/services/test_scan_orchestrator.py
git commit -m "refactor: liquidity_hunt uses alert_service.save_event and self-registers in orchestrator"
```

---

## Task 6: Replace if/elif dispatch in `tasks.py:run_universe_scan` with `orchestrator.run()`

**Goal**: Unify the three-way if/elif block (lines 1472–1483) into a single `asyncio.run(orchestrator.run(...))` call. Import scanner modules at the top of `tasks.py` to ensure the registry is populated before any task runs.

**Files**: `backend/app/tasks.py`

### Step 6.1 — Import scanner modules at top of `tasks.py`

After the existing service imports (around line 1359 area, near where `ScannerService` is imported), add:

```python
# Trigger scanner self-registration in the orchestrator registry
import app.services.pre_market_scan  # noqa: F401
import app.services.oversold_bounce_scan  # noqa: F401
import app.services.liquidity_hunt  # noqa: F401
import app.services.scan_orchestrator as _orchestrator
```

These lines are at module level so they run exactly once when the Celery worker loads.

### Step 6.2 — Replace the if/elif block in `run_universe_scan`

Find lines 1472–1483 of `backend/app/tasks.py`:

```python
if scanner_type in ("liquidity_hunt", "liquidity_hunt_pre", "liquidity_hunt_post"):
    day_events = asyncio.run(run_liquidity_hunt_scan(
        tickers, db, start_date=day, end_date=day, diagnostics_out=day_diag,
    ))
elif scanner_type == "oversold_bounce":
    day_events = asyncio.run(
        ScannerService.run_oversold_bounce_scan(tickers, db, event_date=day)
    )
else:
    day_events = asyncio.run(
        ScannerService.run_pre_market_scan(tickers, db, event_date=day)
    )
```

Replace with:

```python
day_events = asyncio.run(
    _orchestrator.run(scanner_type, tickers, db=db, event_date=day)
)
```

### Step 6.2b — Remove the now-empty `day_diag` accumulation block

The old dispatch populated `day_diag` (e.g. `diagnostics_out=day_diag`) so that the accumulation block following the dispatch could total per-day counts for WebSocket progress events. After the replacement, `day_diag` is never written and the accumulation block silently produces all-zero counts.

Find the accumulation block immediately after the dispatch (roughly lines 1491–1496, now just after the new one-liner):

```python
for k in ("evaluated", "no_data", "no_prior_close", "no_baseline", "errors", "fired_pre", "fired_post"):
    cum[k] += int(day_diag.get(k, 0))
```

Remove **only** the `day_diag.get(k, 0)` accumulation loop, not the entire `cum` dict or all references to it. Specifically:

1. **Keep** `cum["errors"] += 1` in the `except` block — this is a direct write that fires on per-day exceptions; it does NOT read from `day_diag` and must not be removed.
2. **Remove** the loop:
   ```python
   for k in ("evaluated", "no_data", "no_prior_close", "no_baseline", "errors", "fired_pre", "fired_post"):
       cum[k] += int(day_diag.get(k, 0))
   ```
3. **Keep** all remaining `cum` spread-unpacks into WebSocket messages (e.g. `_write_state`, `day_completed`, `completed`). The keys `evaluated`, `no_data`, `no_prior_close`, `no_baseline`, `fired_pre`, `fired_post` will always be zero — that is acceptable per the spec trade-off. Do not strip `cum` entirely, as the `errors` key is still live.
4. Remove `day_diag = {}` initialization line if it now has no writers.

> **Known regression**: scanner progress WebSocket events will show zero for `evaluated`, `fired_pre`, `fired_post`, etc. for all scanner types. Only `errors` (from exceptions) will be non-zero. This is an accepted consequence of dropping `diagnostics_out` from the `ScannerFn` interface.

> **Note — `run_liquidity_hunt_scheduled`**: A separate Celery beat task (`run_liquidity_hunt_scheduled`, around line 1283 in `tasks.py`) calls `run_liquidity_hunt_scan` directly without going through `run_universe_scan`. This task is **not** affected by Task 6 and does not route through the orchestrator. It remains a direct call to `liquidity_hunt.py` and continues to work correctly because `liquidity_hunt.py` still exposes `run_liquidity_hunt_scan`. This is acceptable scope per the spec — Task 6 only unifies `run_universe_scan` dispatch.

### Step 6.3 — Verify and commit

```bash
cd backend && python -m pytest tests/ -x --ignore=tests/api
```
Expected: all service tests pass.

```bash
docker-compose logs backend --tail=10
```
Expected: backend reloaded without import errors.

```bash
git add backend/app/tasks.py
git commit -m "refactor: replace if/elif scanner dispatch in run_universe_scan with orchestrator.run()"
```

---

## Task 7: Add `GET /api/scanner/types` endpoint

**Goal**: Expose all registry entries to the frontend via a new read-only endpoint.

**Files**: `backend/app/routers/scanner.py`, `backend/app/main.py`, `backend/tests/api/test_scanner.py`

### Step 7.1 — Ensure scanner modules are imported on FastAPI startup

In `backend/app/main.py`, add the three side-effect imports **after all `app.include_router(...)` calls** (at the bottom of module-level setup, not inside `lifespan` or any function). Placing them after router includes avoids circular-import risk since routers import from services:

```python
# Populate scan_orchestrator registry — must be after router includes
import app.services.pre_market_scan  # noqa: F401
import app.services.oversold_bounce_scan  # noqa: F401
import app.services.liquidity_hunt  # noqa: F401
```

### Step 7.2 — Write the failing test

`test_scanner.py` uses a module-level `client = TestClient(app)` variable, not a fixture. The new test must match this convention (no `client` parameter):

Add to `backend/tests/api/test_scanner.py`:

```python
def test_list_scanner_types():
    # Import to trigger registration in test process (main.py does this in production)
    import app.services.pre_market_scan  # noqa: F401
    import app.services.oversold_bounce_scan  # noqa: F401
    import app.services.liquidity_hunt  # noqa: F401

    response = client.get("/api/scanner/types")
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list)
    keys = [item["key"] for item in data]
    assert "pre_market_volume_spike" in keys
    assert "oversold_bounce" in keys
    assert "liquidity_hunt" in keys
    assert "liquidity_hunt_pre" in keys
    assert "liquidity_hunt_post" in keys
    for item in data:
        assert {"key", "display_name", "description", "supports_date_range"} == set(item)
        assert isinstance(item["supports_date_range"], bool)
```

Run:
```bash
cd backend && python -m pytest tests/api/test_scanner.py::test_list_scanner_types -xvs
```
Expected: `FAILED` — 404 Not Found (endpoint doesn't exist yet)

### Step 7.3 — Add the endpoint to `routers/scanner.py`

Add to `backend/app/routers/scanner.py`, before the `/run` endpoint:

```python
@router.get("/types")
def list_scanner_types():
    """Return all registered scanner types for frontend scanner pickers."""
    from app.services.scan_orchestrator import get_all
    return [
        {
            "key": d.key,
            "display_name": d.display_name,
            "description": d.description,
            "supports_date_range": d.supports_date_range,
        }
        for d in get_all()
    ]
```

### Step 7.4 — Verify and commit

```bash
cd backend && python -m pytest tests/api/test_scanner.py::test_list_scanner_types -xvs
```
Expected: `PASSED`.

```bash
docker-compose logs backend --tail=10
curl -s http://localhost:8000/api/scanner/types | python -m json.tool
```
Expected output (5 entries):
```json
[
  {"key": "pre_market_volume_spike", "display_name": "Pre-Market Volume Spike", ...},
  {"key": "oversold_bounce", "display_name": "Oversold Bounce", ...},
  {"key": "liquidity_hunt", "display_name": "Liquidity Hunt", ...},
  {"key": "liquidity_hunt_pre", "display_name": "Liquidity Hunt (Pre-Market)", ...},
  {"key": "liquidity_hunt_post", "display_name": "Liquidity Hunt (Post-Market)", ...}
]
```

```bash
git add backend/app/routers/scanner.py backend/app/main.py backend/tests/api/test_scanner.py
git commit -m "feat: add GET /api/scanner/types endpoint exposing orchestrator registry"
```

---

## Task 8: Remove delegated methods from `ScannerService` (own PR)

**Goal**: Inline the scanner logic into `pre_market_scan.py` and `oversold_bounce_scan.py`, then delete the now-delegating methods from `ScannerService`. This is a cleanup-only PR with no behaviour change; all tests should pass unchanged.

**Files**: `backend/app/services/pre_market_scan.py`, `backend/app/services/oversold_bounce_scan.py`, `backend/app/services/scanner.py`, `backend/app/services/__init__.py`, `backend/tests/services/test_scanner_refactor.py`, `backend/tests/services/test_feature_enrichment.py`

> Ship Tasks 1–7 as one or more PRs first. **Do not ship Task 8 until `run_range_scan`'s dispatch map (lines 1238–1244 in `tasks.py`) has been migrated or confirmed not to call `ScannerService.run_pre_market_scan` / `run_oversold_bounce_scan` — those methods are referenced in the `run_range_scan` scanner_map as `ScannerService.run_pre_market_scan_for_date` and `ScannerService.run_oversold_bounce_scan_for_date`. Deleting those methods before migrating `run_range_scan` will break it at runtime.** Open a separate PR for Task 8 after confirming this dependency.

### Step 8.0 — Audit `ScannerService` helper method dependencies

Before inlining, read `backend/app/services/scanner.py` lines 379–757 and list every call to a private helper method on `ScannerService` or on `self`:
- `ScannerService._get_batch_enrichment_data()` — if called by `run_pre_market_scan` or `run_oversold_bounce_scan`, it must either be inlined into the scanner module or kept on a trimmed `ScannerService` and imported by the scanner modules.
- `ScannerService.calculate_day_metrics()` — same check.
- Any other `@staticmethod` or instance method on `ScannerService` referenced within the bodies being extracted.

Decision rule: if the helper is **only** called by the two methods being extracted, move it into the scanner module. If it is called by other remaining `ScannerService` methods, leave it on `ScannerService` and import it.

### Step 8.1 — Inline `run_pre_market_scan` body into `pre_market_scan.py`

Replace the delegating `_run` body in `backend/app/services/pre_market_scan.py`:

```python
# Before (delegate from Task 3):
async def _run(tickers: list[str], db: Any, event_date: date) -> list[dict]:
    from app.services.scanner import ScannerService
    return await ScannerService.run_pre_market_scan(tickers, db, event_date=event_date)
```

With the actual implementation — move the body of `ScannerService.run_pre_market_scan` (lines 379–616 of `scanner.py`) directly into `_run`. Then:
1. Replace every `ScannerService._save_event(...)` call with `_save_event(...)` (imported as `from app.services.alert_service import save_event as _save_event`).
2. For any helper methods identified in Step 8.0 that are moving into this module, paste them above `_run` and adjust calls accordingly.
3. Add all required imports (models, utils, type annotations) from `scanner.py` to the top of `pre_market_scan.py`.

Run:
```bash
cd backend && python -m pytest tests/ -x
```
Expected: all green (same behaviour, different call path).

### Step 8.2 — Inline `run_oversold_bounce_scan` body into `oversold_bounce_scan.py`

Mirror Step 8.1 for `backend/app/services/oversold_bounce_scan.py`, using lines 617–757 (or wherever `run_oversold_bounce_scan` ends in `scanner.py`). Apply the same helper-method rules from Step 8.0.

Run:
```bash
cd backend && python -m pytest tests/ -x
```
Expected: all green.

### Step 8.3 — Update test files that patch `ScannerService` methods being deleted

`test_scanner_refactor.py` and `test_feature_enrichment.py` contain patches targeting methods that will be removed. Update each category:

**a) `_save_event` patches in `test_scanner_refactor.py`** — `test_liquidity_hunt.py`'s patches were updated in Task 5.3, but `test_scanner_refactor.py` uses `patch.object(ScannerService, '_save_event', ...)` at lines 86, 106, 162, 188, 233, 281, and 322. Replace all 7 with:
```python
@patch("app.services.alert_service.save_event", ...)
```

**b) `_get_batch_enrichment_data` patches** — `@patch("app.services.scanner.ScannerService._get_batch_enrichment_data", ...)` → update to the new module path (e.g. `app.services.pre_market_scan._get_batch_enrichment_data` if moved there, or keep targeting `scanner.ScannerService._get_batch_enrichment_data` if the method remains on the class).

**c) `calculate_day_metrics` patches** — `@patch("app.services.scanner.ScannerService.calculate_day_metrics", ...)` → same decision as above.

**d) `test_for_date_wrappers_exist` in `test_scanner_refactor.py`** — lines 198–204 assert `ScannerService.run_pre_market_scan_for_date` and `ScannerService.run_oversold_bounce_scan_for_date` exist as coroutine functions. Resolution: keep these methods on `ScannerService` as one-line delegates to the new module functions. Update them to:

```python
@staticmethod
async def run_pre_market_scan_for_date(tickers, db, event_date):
    from app.services.pre_market_scan import _run
    return await _run(tickers, db, event_date)

@staticmethod
async def run_oversold_bounce_scan_for_date(tickers, db, event_date):
    from app.services.oversold_bounce_scan import _run
    return await _run(tickers, db, event_date)
```

The deferred `from app.services.pre_market_scan import _run` avoids any circular import at module load time. These wrappers also satisfy the `run_range_scan` scanner_map gate (PR-4 blocker) because the map references these `_for_date` methods, not `run_pre_market_scan`. **Do NOT delete these wrappers in Step 8.4.**

Run after each patch update:
```bash
cd backend && python -m pytest tests/services/test_scanner_refactor.py tests/services/test_feature_enrichment.py -x
```

### Step 8.4 — Delete delegated methods from `ScannerService`

Remove from `backend/app/services/scanner.py`:
1. `_save_event()` static method (the thin delegate from Task 1)
2. `run_pre_market_scan()` static method (lines 379–616)
3. `run_oversold_bounce_scan()` static method (lines 617–end of method)
4. Any helper methods confirmed in Step 8.0 to have moved to scanner modules.

**Do NOT remove** `run_pre_market_scan_for_date` or `run_oversold_bounce_scan_for_date` (updated to delegates in Step 8.3d). They are still referenced by `run_range_scan`'s scanner_map and the `test_for_date_wrappers_exist` test.

`ScannerService` will almost certainly still contain remaining methods (`calculate_day_metrics`, `enrich_event`, plus the `_for_date` wrappers). Retain the class and those methods. Only the three methods listed above are removed in this PR.

### Step 8.5 — Update `services/__init__.py`

`ScannerService` retains its `_for_date` wrappers and other methods after Step 8.4, so the class is not deleted. Leave the `from app.services.scanner import ScannerService` import and `__all__` entry in `backend/app/services/__init__.py` unchanged.

### Step 8.6 — Verify full test suite and commit

```bash
cd backend && python -m pytest tests/ -x
```
Expected: all pass.

```bash
docker-compose logs backend --tail=10
curl -s http://localhost:8000/api/health | python -m json.tool
curl -s http://localhost:8000/api/scanner/types | python -m json.tool
```
Expected: health OK, 5 scanner types returned.

```bash
git add backend/app/services/ backend/tests/
git commit -m "refactor: remove delegated scanner methods from ScannerService"
```

---

## Explicit Out-of-Scope

- **`run_range_scan` dispatch map** (lines 1238–1244 in `tasks.py`): separate dispatch map for per-ticker scans (`run_pre_market_scan_for_date`, `run_oversold_bounce_scan_for_date`). These are **not** the same methods as `run_pre_market_scan` / `run_oversold_bounce_scan`. They must be migrated (or the `scanner_map` updated) before Task 8 can safely delete those methods. This is a **blocker for PR 4**.
- **Frontend type list replacement**: `ForceScanDialog.tsx`, `Alerts.tsx`, `Scanner.tsx` hardcoded lists — follow-up once `GET /api/scanner/types` is stable.
- **`chart_indicators.py`**: no changes per spec.
- **`ScannerConfig` auto-seeding on registration**: open question in spec, not required for this issue.
- **`run_liquidity_hunt_scheduled` Celery beat task**: continues to call `run_liquidity_hunt_scan` directly and is not routed through the orchestrator — acceptable per spec scope.

## PR Strategy

| Tasks | PR | Gate |
|-------|-----|------|
| 1–4 | PR 1: persistence extraction + orchestrator shell + first two scanner registrations | None |
| 5–6 | PR 2: liquidity hunt migration + unified dispatch | PR 1 merged |
| 7 | PR 3: `GET /api/scanner/types` endpoint | PR 2 merged |
| 8 | PR 4: `ScannerService` cleanup (deletion PR) | `run_range_scan` `scanner_map` migrated or confirmed safe |
