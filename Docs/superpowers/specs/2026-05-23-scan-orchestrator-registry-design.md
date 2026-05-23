# Scan Orchestrator with Registry Design

**Date:** 2026-05-23  
**Issue:** [#60 — Deepen the Scanner module into a Scan Orchestrator with registry](https://github.com/omniscient/markethawk/issues/60)

## Overview

The Scanner module (`backend/app/services/scanner.py`) is the shallowest module in the system: 15 concerns in one class, scanner dispatch fragmented across three patterns in `tasks.py`, and a circular import with alert triggering. Adding a new scanner type currently requires editing at least three files.

This spec defines an incremental refactor that introduces a **Scan Orchestrator** (`scan_orchestrator.py`) with a single `run(scanner_type, universe_id, dates)` interface and a **scanner registry** based on a frozen `ScannerDescriptor` dataclass. The orchestrator takes ownership of enrichment, persistence, concurrency guarding, and progress reporting. A new `GET /api/scanner/types` endpoint exposes the registry to the frontend, replacing three inconsistent hardcoded type lists.

## Problem Statement

### Current friction

| Pain point | Location |
|---|---|
| 15 concerns in one class | `services/scanner.py` (757 lines) |
| Three-way dispatch via if/elif | `tasks.py` lines 1472–1483 |
| Circular import (deferred local) | `scanner.py:373` → `tasks.evaluate_scanner_alerts`; `tasks.py` → `ScannerService` |
| Adding a scanner type edits 3+ files | `scanner.py`, `tasks.py`, `routers/scanner.py` |
| Frontend scanner type lists hardcoded in 3 places | `ForceScanDialog.tsx`, `Alerts.tsx`, `Scanner.tsx` (already inconsistent) |

## Requirements

1. A single orchestrator entry point `run(scanner_type, tickers, db, event_date)` replaces all if/elif dispatch in `tasks.py`. The Celery task (`run_universe_scan`) continues to own ticker resolution and the date loop — it calls `orchestrator.run()` once per day instead of the current if/elif block.
2. Each scanner type is described by a `ScannerDescriptor` dataclass with `key`, `display_name`, `description`, `run`, and `supports_date_range` fields.
3. Scanner modules self-register via a top-level `register()` call at import time — no scanner logic lives in the orchestrator's module.
4. `_save_event()` is extracted out of `ScannerService` as the first step, because it is shared by both `scanner.py` and `liquidity_hunt.py`.
5. The circular import is eliminated: the orchestrator's persistence layer imports from `alert_service.py`, not `tasks.py`.
6. `GET /api/scanner/types` returns all registry entries (key, display_name, description, supports_date_range) for frontend consumption.
7. The refactor is incremental — `ScannerService` continues to exist until all callers are migrated. No big-bang rewrite.
8. Existing Celery task signatures (`run_universe_scan`, `run_range_scan`) are preserved; they become thin wrappers that call through the orchestrator.

## Architecture

### New file: `backend/app/services/scan_orchestrator.py`

```python
from dataclasses import dataclass
from typing import Callable, Awaitable, Any
from datetime import date

# Matches the signature already used by run_pre_market_scan / run_oversold_bounce_scan
ScannerFn = Callable[[list[str], Any, date], Awaitable[list[dict]]]

@dataclass(frozen=True)
class ScannerDescriptor:
    key: str                       # DB-stored scanner_type string
    display_name: str              # UI-facing label
    description: str               # shown in scanner picker
    run: ScannerFn                 # async def run(tickers, db, event_date) -> list[dict]
    supports_date_range: bool = True

_REGISTRY: dict[str, ScannerDescriptor] = {}

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
        raise ValueError(f"Unknown scanner type: {scanner_type!r}. Registered: {list(_REGISTRY)}")
    return await descriptor.run(tickers, db, event_date)
```

This pattern follows `DataProviderFactory` in `backend/app/providers/__init__.py` — an explicit `register()` call per module at import time, with enumeration via `get_all()`.

### Scanner self-registration

Each scanner module calls `register()` at module level after defining its `run` function:

```python
# services/pre_market_scan.py (extracted from scanner.py)
from app.services.scan_orchestrator import ScannerDescriptor, register

async def _run(tickers, db, event_date):
    ...

register(ScannerDescriptor(
    key="pre_market_volume_spike",
    display_name="Pre-Market Volume Spike",
    description="Detects stocks with >4x average volume in the pre-market window.",
    run=_run,
))
```

Adding a new scanner type is: create one file, call `register()`. No other files change.

### Breaking the circular import

**Current cycle:**
```
scanner.py:_save_event() --deferred--> tasks.evaluate_scanner_alerts
tasks.py ----------------deferred----> ScannerService
```

**Fix — Option A: `alert_service.py` thin function:**

```python
# services/alert_service.py  (existing file, add one function)
def trigger_scanner_alert(event_id: int) -> None:
    """Enqueue alert evaluation for a newly persisted ScannerEvent."""
    from app.tasks import evaluate_scanner_alerts   # deferred — tasks.py loads after services
    evaluate_scanner_alerts.delay(event_id)
```

The orchestrator's persistence layer imports `trigger_scanner_alert` from `alert_service` (not `tasks`). `tasks.py` keeps the `evaluate_scanner_alerts` task definition and imports only from `alert_service`. `ScannerService` and `scan_orchestrator` never appear in `tasks.py`'s module-level imports.

### Incremental migration steps

| Step | Change | Deliverable |
|---|---|---|
| 1 | Extract `_save_event()` + `trigger_scanner_alert()` into `alert_service.py` | Shared persistence works without `ScannerService` |
| 2 | Create `scan_orchestrator.py` with `_REGISTRY`, `register()`, `get_all()`, `run()` | Orchestrator shell |
| 3 | Extract pre-market scanner as `services/pre_market_scan.py`; self-register | First registry entry |
| 4 | Extract oversold bounce scanner as `services/oversold_bounce_scan.py`; self-register | Second registry entry |
| 5 | Migrate `liquidity_hunt.py` to use orchestrator persistence; self-register | Third registry entry; `liquidity_hunt.py` no longer imports `ScannerService` |
| 6 | Replace if/elif block in `tasks.py:run_universe_scan` with `orchestrator.run()` | Dispatch unified |
| 7 | Add `GET /api/scanner/types` to `routers/scanner.py` | Frontend-ready endpoint |
| 8 | Delete now-empty `ScannerService` shell; update `services/__init__.py` | Cleanup |

Steps 1–6 can be landed as one PR per step or grouped into 2–3 PRs. Step 8 (deletion) should be its own PR so reviewers can see the full cleanup clearly.

### New endpoint: `GET /api/scanner/types`

```python
# routers/scanner.py
@router.get("/types")
def list_scanner_types():
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

The frontend's `ForceScanDialog.tsx`, `Alerts.tsx`, and `Scanner.tsx` each hardcode scanner type lists that are already inconsistent with each other. This endpoint lets them all fetch from a single authoritative source.

## Alternatives Considered

### A: Big-bang rewrite of `scanner.py`

Replace the entire file in one PR, migrate all callers simultaneously. Rejected because `ScannerService` is imported by `services/__init__.py`, `liquidity_hunt.py`, two separate sites in `tasks.py`, and patched in five test files. A big-bang change produces a single enormous, hard-to-review diff and creates high rollback risk if a Celery worker regression surfaces in production.

### B: Keep `ScannerService` as the orchestrator

Add a `run(scanner_type, ...)` method to `ScannerService` that does a dict dispatch internally. Rejected because it doesn't solve the module-level bloat (all scanner implementations still live in the same class), doesn't allow new scanners to live in their own files, and preserves the circular import.

### C: Redis pub/sub for alert triggering

Replace `evaluate_scanner_alerts.delay()` with a Redis `PUBLISH` from the persistence layer; the task becomes a subscriber. Rejected as over-engineered — there is only one consumer (Celery alert evaluation), no fan-out requirement, and the existing Celery `.delay()` pattern is already correct for this case.

## Open Questions (non-blocking)

- Should scanner descriptors carry a `default_config` field that seeds a `ScannerConfig` row on first registration? This would allow new scanner types to appear in the config UI automatically. Not required for this issue.
- Should `run_range_scan` (per-ticker scan, also in `tasks.py`) be migrated to the orchestrator in the same PRs, or in a follow-up? It has a separate dispatch map (lines 1238–1244) and is lower-priority.

## Assumptions

- **`ScannerFn` signature is stable.** All three current scanner implementations accept `(tickers: list[str], db: Session, event_date: date)` and return `list[dict]`. If a scanner needs a different signature (e.g., additional config), a wrapper function at registration time handles the adaptation.
- **`chart_indicators.py` is out of scope.** The issue lists it as "involved" but its connection to the scanner dispatch problem is indirect. It is not touched in this spec.
- **No frontend PR in this issue.** Replacing the three hardcoded type lists is a follow-up once `GET /api/scanner/types` is live and stable.
- **`size: L` means multiple PRs.** The eight migration steps above are expected to land as 3–4 PRs over multiple sessions, not a single large commit.
