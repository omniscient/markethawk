# Scanner Extension Registration Design

**Date:** 2026-06-15  
**Status:** Spec — pending review  
**Issue:** #440 (parent epic #438)  
**Revised:** 2026-09-16 (operator amendment after spec-gate review; original 2026-06-15)  
**Depends on:** #439 (extension loader and shared registry primitives) — unconditional. This spec is written against #439's approved contract (`ExtensionRegistry[T]`, `ExtensionDuplicateError`, `load_extension_modules`) and cannot be implemented before #439 lands.

## Overview

`scan_orchestrator.py` already has a working `ScannerDescriptor` dataclass and `_REGISTRY` dict, but the descriptor is missing two metadata fields the frontend and private extension authors need: `asset_classes` (which asset types the scanner operates on) and `default_parameters` (canonical threshold defaults). The `register()` function silently overwrites on duplicate keys — a footgun when private modules ship beside built-ins. This spec adds those two fields, migrates `_REGISTRY` onto #439's `ExtensionRegistry[ScannerDescriptor]` (which supplies the duplicate-key guard and the `ExtensionDuplicateError`), and documents the import-time registration pattern that private extension modules follow through #439's loader. `discovery_service._SCREENER_REGISTRY` (`backend/app/services/discovery_service.py:16-20`) is a universe-screener registry keyed by asset class, not a scanner registry, and is explicitly out of scope for #440.

## Requirements

1. `ScannerDescriptor` exposes `asset_classes: tuple[str, ...]` (default `("stocks",)`) using the canonical values already in the codebase (`"stocks"`, `"futures"`).
2. `ScannerDescriptor` exposes `default_parameters: dict[str, Any]` (default `{}`) — the canonical thresholds for that scanner.
3. All five built-in scanner modules — seven keys, because `liquidity_hunt.py` registers `liquidity_hunt`, `liquidity_hunt_pre` and `liquidity_hunt_post` sharing one `_orchestrator_run` and one `DEFAULT_CONFIG`, so all three get identical `default_parameters` — update their `register()` call to supply both fields; where a module-level `DEFAULT_CONFIG` dict exists, its value becomes `default_parameters` (single source of truth within that module).
4. `register()` delegates to `ExtensionRegistry.register()`, so a duplicate key raises `ExtensionDuplicateError` (from `app.exceptions`, per #439) rather than silently overwriting; a descriptor whose `key` is not a non-empty `str` raises `ExtensionDescriptorError`. Intentional override requires `replace=True`.
5. `/api/v1/scanner/types` response includes `asset_classes` and `default_parameters` alongside existing fields. The existing exact-key-set assertion in `backend/tests/api/test_scanner.py:472-474` is updated to the six-key set.
6. A private extension module that calls `scan_orchestrator.register(ScannerDescriptor(...))` at import time is resolved and executed by the orchestrator identically to a built-in.
7. Tests (see **Tests** below) cover: all built-in scanner modules load without duplicate-key errors and expose the seven expected keys with the new fields; a private module loaded through `load_extension_modules()` registers a scanner that is resolvable and runnable via `run()`; a second `register()` for the same key raises `ExtensionDuplicateError` without `replace=True`; `replace=True` succeeds; the `/types` response carries the two new keys.
8. The unknown-scanner `ValueError` raised by `run()` continues to list the registered scanner keys (issue AC "Unknown scanner errors include the registered scanner keys"); the list is now derived from `get_all()` rather than from the dict.

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
    default_parameters: dict[str, Any] = field(default_factory=dict, hash=False)
```

`frozen=True` is preserved. `field(default_factory=dict)` is required for a mutable default on a frozen dataclass; `hash=False` excludes the (unhashable) dict from the auto-generated `__hash__` so `ScannerDescriptor` stays hashable. No caller on `main` hashes descriptors (verified across `scan_orchestrator.py`, `routers/scanner.py`, `tasks/scanning.py`, `replay_diff_service.py`), so this is belt-and-braces rather than a compatibility requirement.

### Registry migration onto `ExtensionRegistry[ScannerDescriptor]`

`_REGISTRY` stops being a plain dict and becomes an instance of #439's generic registry; `register()`, `get_all()` and `run()` become thin wrappers. The duplicate guard, key validation and `replace=True` semantics live in `ExtensionRegistry.register()` — nothing is re-implemented here.

```python
from app.core.extensions import ExtensionRegistry

_REGISTRY: ExtensionRegistry["ScannerDescriptor"] = ExtensionRegistry()


def register(descriptor: "ScannerDescriptor", *, replace: bool = False) -> "ScannerDescriptor":
    # Raises ExtensionDuplicateError on a duplicate key (unless replace=True) and
    # ExtensionDescriptorError on a missing/non-str key — both from app.exceptions (#439).
    return _REGISTRY.register(descriptor, replace=replace)


def get_all() -> list["ScannerDescriptor"]:
    return _REGISTRY.get_all()


async def run(scanner_type, tickers, db, event_date, scanner_run=None, gate_metadata=None):
    descriptor = _REGISTRY.get(scanner_type)
    if descriptor is None:
        raise ValueError(
            f"Unknown scanner type: {scanner_type!r}. "
            f"Registered: {[d.key for d in _REGISTRY.get_all()]}"
        )
    return await descriptor.run(
        tickers, db, event_date, scanner_run=scanner_run, gate_metadata=gate_metadata
    )
```

`ExtensionDuplicateError` and `ExtensionDescriptorError` are defined in `app/exceptions.py` by #439; `ExtensionRegistry` is imported from `app.core.extensions`. The error name used by the original draft of this spec does not exist in #439 and is not introduced. Insertion order is preserved by `ExtensionRegistry` exactly as the dict preserved it (#439 open question 2), so the default deployment lists and runs the same seven keys in the same order.

**Ripple onto tests that treat `_REGISTRY` as a dict** (all break otherwise and are part of this ticket): `backend/tests/services/test_scan_orchestrator.py:13-16` (the `isolated_registry` fixture snapshots/`clear()`s/`update()`s the dict), `:23-24`, `:69-70`, `:78-79`, `:88`, and `backend/tests/services/test_trend_pullback_scan.py:149-151` (`"trend_pullback" in _REGISTRY`). The fixture becomes: snapshot `get_all()` before the test, `_REGISTRY.clear()` in teardown, then re-`register(..., replace=True)` each snapshotted descriptor; membership checks become `_REGISTRY.get(key) is not None` and identity checks use `_REGISTRY.get(key) is desc`.

**Blast radius of the fail-fast guard:** it can only fire if a scanner module body executes twice. Verified on `main`: no module is imported under two names (no `from services.` dual-path imports) and `importlib.reload` in tests touches only `app.core.config` (`backend/tests/test_config.py:9-29`), so the guard cannot fire in the default deployment.

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

Scanners without tunable parameters (`pre_market_scan.py`, `oversold_bounce_scan.py`) pass `default_parameters={}` implicitly (the default). The rename is safe: `DEFAULT_CONFIG` is referenced only inside its own module in each case (the hit at `backend/tests/services/test_liquidity_hunt.py:761` is a docstring), and `scanner_explanations.py:7` keeps its own `LIQUIDITY_HUNT_DEFAULT_CONFIG` copy — reconciling that copy is out of scope for #440.

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

The tuple is serialized to a JSON array. The cache TTL (1 hour) is unchanged since descriptors are static per process lifetime. The listing reflects whatever the API process has imported: `app/main.py:456-458` imports only `pre_market_scan`, `oversold_bounce_scan` and `liquidity_hunt`, so `pocket_pivot` and `trend_pullback` appear in `/types` only once something in that process imports them (pre-existing behaviour, #439 open question 3) — this ticket preserves that as-is and does not claim all seven keys are listed.

### Private module registration pattern

Once #439's `MARKETHAWK_EXTENSION_MODULES` loader is in place, a private scanner module registers at import time using the same call built-ins use:

```python
# myedge/scanners.py  — example private module
from app.services.scan_orchestrator import ScannerDescriptor, register

async def _run(tickers, db, event_date, scanner_run=None, gate_metadata=None):
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

The callable **must** accept both `scanner_run` and `gate_metadata` keyword arguments: `scan_orchestrator.run()` and `app/tasks/scanning.py:449-456` always pass `gate_metadata=`, and all five built-ins accept it (`liquidity_hunt.py:709-717`, `pocket_pivot.py:416-422`, `trend_pullback_scan.py:426-432`, `oversold_bounce_scan.py:250-256`, `pre_market_scan.py:623-629`). The `ScannerFn` alias (`Callable[[list[str], Any, date], Awaitable[list[dict]]]`) does not encode those keyword arguments and is left unchanged in this ticket; a comment next to the alias notes the two required kwargs.

`MARKETHAWK_EXTENSION_MODULES=myedge.scanners` in `.env` causes #439's `load_extension_modules()` to `import myedge.scanners`, which triggers the `register()` call. **Process scope (per #439 Requirement 2):** the loader runs in the API process (`create_app()` in `app/main.py`) **and** in the Celery processes (`worker_init` handler in `app/core/celery_app.py`). `/types` is served by the API process; `run()` executes in the Celery worker, where `run_universe_scan` imports the built-ins inside the task (`app/tasks/scanning.py:305-310`) — `worker_init` fires before any task, so extension registrations are already present. Both processes read the same `MARKETHAWK_EXTENSION_MODULES`. The `live-scanner` process does not load extension modules (deferred by #439), so private scanners are unavailable there. After load, `scan_orchestrator.run("myedge_momentum", ...)` resolves and executes identically to any built-in. `compute_next_run()` (`scan_orchestrator.py:52-57`) hard-codes four built-in keys, so a private scanner gets no beat schedule — it runs on demand via `/scanner/run` only; scheduling private scanners is a follow-on.

No special-casing exists between built-in and private registrations — this symmetry is intentional.

## Alternatives Considered

### Alt A: Separate metadata dict alongside registry

Keep `ScannerDescriptor` frozen at its current five fields; add a separate `_METADATA: dict[str, dict]` for `asset_classes` and `default_parameters` that lives outside the descriptor.

**Rejected.** Creates two sources of truth for the same scanner and requires callers to do two lookups. The descriptor is already the stable contract surface — extending it is the right move.

### Alt B: Require `asset_classes` and `default_parameters` (no defaults)

Force every `register()` call to supply both fields explicitly so private extension authors can't accidentally omit them.

**Rejected.** Would break all five existing built-in `register()` calls immediately. The "current built-in scanners still self-register" acceptance criterion requires backward-compatible extension, so sensible defaults (`("stocks",)` and `{}`) are the right design. The test for "built-in compatibility" validates that no existing registration silently drops data.

### Alt C: Keep a bespoke dict and re-implement the duplicate guard in `scan_orchestrator.py`

Leave `_REGISTRY` as a plain dict and add an inline `if key in _REGISTRY and not replace: raise ...` check (the original draft of this spec).

**Rejected.** #439 defines `ExtensionRegistry[T]` precisely so each extension point does not grow its own guard; epic #438 requires that "built-in and private capabilities use the same registry contracts where each extension point has been migrated". A second implementation of the same rule would drift from #439's (`ExtensionDescriptorError` on a bad key, `replace=True` semantics) and would need its own tests. Wrapping `ExtensionRegistry` is the same number of lines and inherits #439's test coverage.

## Tests

All tests run in the CI test job (`backend/`: `ruff check .`, `pip-audit`, `python -m pytest` with `--cov=app --cov-fail-under=60` from `backend/pyproject.toml`). No test uses `os.geteuid()` or any other environment-conditional skip.

`backend/tests/services/test_scan_orchestrator.py` (existing file, fixture updated per the ripple list above):
- new-field defaults: a descriptor built without the new fields has `asset_classes == ("stocks",)` and `default_parameters == {}`
- duplicate key → `ExtensionDuplicateError` (from `app.exceptions`); `replace=True` succeeds and `get(key)` returns the replacement
- built-in compatibility: importing the five built-in modules registers exactly the seven expected keys with no duplicate-key error; `pocket_pivot`, `trend_pullback` and the three `liquidity_hunt*` keys expose their module's former `DEFAULT_CONFIG` as `default_parameters`; every built-in has `asset_classes == ("stocks",)`
- unknown scanner: `run("does_not_exist", ...)` raises `ValueError` whose message contains every registered key (Requirement 8)
- private module through the real loader: inject a `types.ModuleType` into `sys.modules` whose body calls `register(ScannerDescriptor(...))` with an `AsyncMock` run callable, call `load_extension_modules([name])` from `app.core.extensions`, then `asyncio.run(run(key, ["AAPL"], db=None, event_date=...))` and assert the mock was awaited with `scanner_run=None, gate_metadata=None` — this exercises issue AC 3 through #439's loader rather than a bare `register()` call

`backend/tests/api/test_scanner.py::test_list_scanner_types` (existing test): the exact-key-set assertion at `:472-474` becomes the six-key set `{"key", "display_name", "description", "supports_date_range", "asset_classes", "default_parameters"}`, plus `isinstance(item["asset_classes"], list)` and `isinstance(item["default_parameters"], dict)`.

`backend/tests/services/test_trend_pullback_scan.py:149-151`: membership check becomes `_REGISTRY.get("trend_pullback") is not None`.

## Open Questions (non-blocking)

1. **Orchestrator parameter merge:** The `run()` function in `scan_orchestrator.py` currently never passes `ScannerConfig.parameters` to the scanner callable — each scanner reads its config internally via `DEFAULT_CONFIG`. A natural follow-on is to have `orchestrator.run()` merge `{**descriptor.default_parameters, **(config.parameters or {})}` and pass the merged dict as a keyword arg. This closes the existing gap where DB-seeded parameters are effectively ignored at the orchestrator layer. Deferred from #440 to avoid scope creep; tracked as a follow-on in epic #438.

2. **Futures scanners and asset_classes:** No built-in scanner currently targets `"futures"`. If a private module registers a futures scanner, the `("stocks", "futures")` combo should work correctly. The liquidity-hunt family (`liquidity_hunt`, `liquidity_hunt_pre`, `liquidity_hunt_post`) runs on equity universes only; leaving them as `("stocks",)` is correct.

3. **Cache invalidation on dynamic registration:** The `/types` cache TTL is 1 hour. If a dev environment restarts the backend, the cache key resets cleanly. This is not a problem for production (descriptors are fixed at deploy time) or tests (cache is bypassed or mocked). No action needed.

## Assumptions

- **[Dependency]** #439 lands before #440 is implemented — unconditional. The spec is written against #439's approved contract (`ExtensionRegistry[T]` and `load_extension_modules` in `app.core.extensions`; `ExtensionDuplicateError` and `ExtensionDescriptorError` in `app.exceptions`). There is no fallback path if #439 has not landed.
- **[Assumed]** `"stocks"` and `"futures"` are the only two valid asset class strings for v1. The spec makes no provision for arbitrary strings; if a new class (e.g., `"crypto"`) is needed later it requires a follow-on ticket.
- **[Assumed]** The frontend scanner picker is responsible for using `asset_classes` to filter the scanner type list when a user's selected universe has a known asset class. No backend filtering is added in this ticket.
- **[Assumed]** `oversold_bounce_scan.py` and `pre_market_scan.py` have no tunable `DEFAULT_CONFIG`; their `default_parameters` will be `{}`.
