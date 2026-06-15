# Scanner Extension Registration Design

**Date:** 2026-06-15  
**Status:** Spec — pending review  
**Issue:** #440 (parent epic #438)  
**Blocked by:** #439 (extension loader and shared registry primitives)

## Overview

`scan_orchestrator.py` already has a working `ScannerDescriptor` dataclass and `_REGISTRY` dict, but the descriptor is missing two metadata fields the frontend and private extension authors need: `asset_classes` (which asset types the scanner operates on) and `default_parameters` (canonical threshold defaults). The `register()` function silently overwrites on duplicate keys — a footgun when private modules ship beside built-ins. This spec adds those two fields, hardens registration against accidental shadowing, and documents the import-time registration pattern that private extension modules follow once #439's loader is in place.

## Requirements

1. `ScannerDescriptor` exposes `asset_classes: tuple[str, ...]` (default `("stocks",)`) using the canonical values already in the codebase (`"stocks"`, `"futures"`).
2. `ScannerDescriptor` exposes `default_parameters: dict[str, Any]` (default `{}`) — the canonical thresholds for that scanner.
3. All five built-in scanners update their `register()` call to supply both fields; where a module-level `DEFAULT_CONFIG` dict exists, its value becomes `default_parameters` (single source of truth).
4. `register()` raises a structured duplicate-key error rather than silently overwriting. Intentional override requires `replace=True` — aligned with #439's registry primitive contract.
5. `/api/v1/scanner/types` response includes `asset_classes` and `default_parameters` alongside existing fields.
6. A private extension module that calls `scan_orchestrator.register(ScannerDescriptor(...))` at import time is resolved and executed by the orchestrator identically to a built-in.
7. Tests cover: all built-in scanners load without duplicate-key errors; a dynamically registered mock scanner is resolvable and runnable; a second `register()` for the same key raises without `replace=True`; `replace=True` succeeds.

## Architecture / Approach

### ScannerDescriptor changes (`scan_orchestrator.py`)

```python
from dataclasses import dataclass, field
from typing import Any

@dataclass(frozen=True)
class ScannerDescriptor:
    key: str
    display_name: str
    description: str
    run: ScannerFn
    supports_date_range: bool = True
    asset_classes: tuple[str, ...] = ("stocks",)
    default_parameters: dict[str, Any] = field(default_factory=dict)
```

`frozen=True` is preserved. `tuple[str, ...]` for `asset_classes` is hashable. `field(default_factory=dict)` is required for a mutable default on a frozen dataclass.

### register() hardening

```python
def register(descriptor: ScannerDescriptor, *, replace: bool = False) -> ScannerDescriptor:
    if descriptor.key in _REGISTRY and not replace:
        raise ExtensionRegistrationError(
            f"Scanner key {descriptor.key!r} is already registered. "
            f"Pass replace=True to intentionally override."
        )
    _REGISTRY[descriptor.key] = descriptor
    return descriptor
```

`ExtensionRegistrationError` is imported from the shared error module introduced by #439. Until #439 ships, a plain `ValueError` with the same message is acceptable; the spec declares the final type so the implement agent wires it correctly once #439 is merged.

### Built-in registration updates

Each built-in scanner adds `asset_classes` and moves its `DEFAULT_CONFIG` value into `default_parameters`:

```python
# pocket_pivot.py — before
DEFAULT_CONFIG: dict[str, Any] = {"lookback_days": 10, "min_lookback_days": 5, ...}

register(ScannerDescriptor(key="pocket_pivot", display_name="Pocket Pivot", ...))

# pocket_pivot.py — after
_DEFAULT_PARAMS: dict[str, Any] = {"lookback_days": 10, "min_lookback_days": 5, ...}

register(ScannerDescriptor(
    key="pocket_pivot",
    display_name="Pocket Pivot",
    description="...",
    run=_run,
    supports_date_range=True,
    asset_classes=("stocks",),
    default_parameters=_DEFAULT_PARAMS,
))
```

The `DEFAULT_CONFIG` module-level name is renamed to `_DEFAULT_PARAMS` (or removed) to make the descriptor the authoritative source. The scanner's internal `_run`/config-merge code (`cfg = {**DEFAULT_CONFIG, **(config or {})}`) continues to work unchanged — it can reference `_DEFAULT_PARAMS` instead.

Scanners without tunable parameters (`pre_market_scan.py`, `oversold_bounce_scan.py`) pass `default_parameters={}` implicitly (the default).

### /api/v1/scanner/types update

```python
@router.get("/types")
@cache_response("mh:scanner:types", ttl=3600)
def list_scanner_types():
    from app.services.scan_orchestrator import get_all
    return [
        {
            "key": d.key,
            "display_name": d.display_name,
            "description": d.description,
            "supports_date_range": d.supports_date_range,
            "asset_classes": list(d.asset_classes),
            "default_parameters": d.default_parameters,
        }
        for d in get_all()
    ]
```

The tuple is serialized to a JSON array. The cache TTL (1 hour) is unchanged since descriptors are static per process lifetime.

### Private module registration pattern

Once #439's `MARKETHAWK_EXTENSION_MODULES` loader is in place, a private scanner module registers at import time using the same call built-ins use:

```python
# myedge/scanners.py  — example private module
from app.services.scan_orchestrator import ScannerDescriptor, register

async def _run(tickers, db, event_date, scanner_run=None):
    ...

register(ScannerDescriptor(
    key="myedge_momentum",
    display_name="Momentum (Private)",
    description="Proprietary momentum breakout scanner.",
    run=_run,
    asset_classes=("stocks",),
    default_parameters={"lookback": 20, "threshold": 1.5},
))
```

`MARKETHAWK_EXTENSION_MODULES=myedge.scanners` in `.env` causes the loader to `import myedge.scanners` at startup, which triggers the `register()` call. After startup, `scan_orchestrator.run("myedge_momentum", ...)` resolves and executes identically to any built-in.

No special-casing exists between built-in and private registrations — this symmetry is intentional.

## Alternatives Considered

### Alt A: Separate metadata dict alongside registry

Keep `ScannerDescriptor` frozen at its current five fields; add a separate `_METADATA: dict[str, dict]` for `asset_classes` and `default_parameters` that lives outside the descriptor.

**Rejected.** Creates two sources of truth for the same scanner and requires callers to do two lookups. The descriptor is already the stable contract surface — extending it is the right move.

### Alt B: Require `asset_classes` and `default_parameters` (no defaults)

Force every `register()` call to supply both fields explicitly so private extension authors can't accidentally omit them.

**Rejected.** Would break all five existing built-in `register()` calls immediately. The "current built-in scanners still self-register" acceptance criterion requires backward-compatible extension, so sensible defaults (`("stocks",)` and `{}`) are the right design. The test for "built-in compatibility" validates that no existing registration silently drops data.

### Alt C: Move duplicate-key hardening entirely to #439

Leave `register()` as a silent overwrite in #440 and let #439's shared registry primitives own the duplicate guard.

**Rejected.** The scanner registry is the only registry that exists today, and #440 is the ticket that formalizes it. Deferring the guard to #439 means the footgun stays live through the entire #440 implementation window. Better to harden `register()` in #440 with a plain `ValueError` as a minimal stand-in, then swap to `ExtensionRegistrationError` when #439 ships. This is a two-line change at merge time.

## Open Questions (non-blocking)

1. **Orchestrator parameter merge:** The `run()` function in `scan_orchestrator.py` currently never passes `ScannerConfig.parameters` to the scanner callable — each scanner reads its config internally via `DEFAULT_CONFIG`. A natural follow-on is to have `orchestrator.run()` merge `{**descriptor.default_parameters, **(config.parameters or {})}` and pass the merged dict as a keyword arg. This closes the existing gap where DB-seeded parameters are effectively ignored at the orchestrator layer. Deferred from #440 to avoid scope creep; tracked as a follow-on in epic #438.

2. **Futures scanners and asset_classes:** No built-in scanner currently targets `"futures"`. If a private module registers a futures scanner, the `("stocks", "futures")` combo should work correctly. The liquidity-hunt family (`liquidity_hunt`, `liquidity_hunt_pre`, `liquidity_hunt_post`) runs on equity universes only; leaving them as `("stocks",)` is correct.

3. **Cache invalidation on dynamic registration:** The `/types` cache TTL is 1 hour. If a dev environment restarts the backend, the cache key resets cleanly. This is not a problem for production (descriptors are fixed at deploy time) or tests (cache is bypassed or mocked). No action needed.

## Assumptions

- **[Assumed]** #439 ships before #440 is implemented. The spec is written assuming the extension loader and `ExtensionRegistrationError` are available. If #440 must ship first, the implement agent uses `ValueError` as a stand-in and notes the swap in the commit message.
- **[Assumed]** `"stocks"` and `"futures"` are the only two valid asset class strings for v1. The spec makes no provision for arbitrary strings; if a new class (e.g., `"crypto"`) is needed later it requires a follow-on ticket.
- **[Assumed]** The frontend scanner picker is responsible for using `asset_classes` to filter the scanner type list when a user's selected universe has a known asset class. No backend filtering is added in this ticket.
- **[Assumed]** `oversold_bounce_scan.py` and `pre_market_scan.py` have no tunable `DEFAULT_CONFIG`; their `default_parameters` will be `{}`.
