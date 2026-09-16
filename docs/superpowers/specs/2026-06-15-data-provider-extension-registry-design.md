# Data Provider Extension Registry Design

**Date:** 2026-06-15  
**Issue:** #441 — Unify data provider registration under extension registry  
**Revised:** 2026-09-16 (operator amendment after spec-gate review; original 2026-06-15)  
**Parent epic:** #438 — Formal module extension points for MarketHawk  
**Depends on:** #439 — Add extension loader and shared registry primitives (merged on `main`: `ExtensionRegistry[T]` and `load_extension_modules` in `app.core.extensions`; `ExtensionDuplicateError` and `ExtensionDescriptorError` in `app.exceptions`)  
**Relation to #440:** #440 migrates the scanner registry onto the same `ExtensionRegistry` primitive. The two tickets share no files (#440: `scan_orchestrator.py`, the five scanner modules, `routers/scanner.py` and their tests; #441: `providers/base.py`, `providers/__init__.py`, `tests/fixtures/providers.py`, one new test file), so this ticket does not depend on #440; landing after it merely lets the tests reuse #440's isolation-fixture pattern.  
**Status:** Spec pending review

## Overview

`DataProviderFactory` currently stores providers in a plain class-level dict (`_providers: Dict[str, BaseDataProvider]`, `backend/app/providers/__init__.py:43`) and silently overwrites duplicate names (`:46-49`). This is incompatible with the extension registry introduced in #439, which validates descriptors and rejects duplicate registrations with structured errors.

This spec migrates `DataProviderFactory` to wrap an `ExtensionRegistry[BaseDataProvider]` instance from #439, so that extension-loaded providers (private modules registered via `MARKETHAWK_EXTENSION_MODULES`) appear through the same factory surface as built-in providers, and duplicate names produce an `ExtensionDuplicateError` instead of a silent overwrite. The factory's public API (`get`, `get_or_none`, `get_available`, `get_all_with_classes`, `all`, `register`) is unchanged; `register` gains a keyword-only `replace: bool = False`.

### Current state on main

Registration: `backend/app/providers/__init__.py:43` (`_providers` dict), `:46-49` (`register()` overwrites silently), `:102-106` (built-ins register at import, order `massive` → `ibkr`). Selection is by string literal at the call site, not by settings — `backend/app/core/config.py` has no data-provider knob (only `LLM_PROVIDER`, `:168`): `backend/app/services/stock_data.py:488` (`provider: str = "massive"` default) → `:499` `DataProviderFactory.get(provider)`; `services/futures_aggregates.py:36`, `services/futures_contracts.py:54`, `scripts/download_futures.py:57` (`get("ibkr")`); `routers/futures.py:168`, `tasks/sync.py:588` (`get_or_none("ibkr")`); `tasks/trading.py:407` (`get_or_none("massive")`); listing at `routers/futures.py:184-187`. There is no cross-provider failover path (the only "fallback" hits, `providers/ibkr.py:741,753`, are date-format parsing inside IBKR). Every one of these call sites is unchanged by this issue.

## Requirements

From the acceptance criteria:

1. **API preservation** — `DataProviderFactory.get`, `get_or_none`, `get_available`, `get_all_with_classes`, and `all` behave identically from the perspective of callers: same two built-in providers in the same order (`massive`, `ibkr`), same return shapes, and the unknown-provider `ValueError` message byte-identical to today's (`backend/app/providers/__init__.py:60-64`). `register` keeps its positional signature and gains a keyword-only `replace: bool = False`. No existing call site changes.
2. **Extension visibility** — A provider registered from a configured extension module (loaded by the #439 extension loader at startup) is returned by `get`, listed by `get_available`, appears in `get_all_with_classes` and `all`, and is served by `GET /api/v1/futures/providers`.
3. **Descriptor fields** — Every registered provider exposes `name`, `supported_asset_classes`, and `is_available()`. These are already enforced by `BaseDataProvider`'s abstract interface; the only addition is a concrete `key` property (always equal to `name`) so the provider satisfies `ExtensionRegistry`'s descriptor contract.
4. **Duplicate rejection** — Registering a second provider under a name already in the registry raises `ExtensionDuplicateError` (from `app.exceptions`, per #439) unless `replace=True` is passed. A provider whose `name` is not a non-empty `str` raises `ExtensionDescriptorError`. Today's silent overwrite must not survive.
5. **Test coverage** — see **Tests** below: built-in providers registered at import time in the expected order; a private provider loaded through the real `load_extension_modules()`; duplicate name rejection and `replace=True`; descriptor validation; and every factory method plus the `/providers` endpoint after registration.

## Architecture

### Decision: DataProviderFactory wraps ExtensionRegistry (composition)

`DataProviderFactory` keeps its class structure and classmethods. Internally, the class-level `_providers: Dict` is replaced by `_registry: ExtensionRegistry[BaseDataProvider]` from #439 (`backend/app/core/extensions.py:27-57`). `ExtensionRegistry.register(descriptor, *, replace=False)` reads the registry key from `descriptor.key` and raises `ExtensionDescriptorError` when that attribute is missing or not a non-empty `str`; `BaseDataProvider` exposes `name` (`backend/app/providers/base.py:22-26`) but no `key`, so this ticket adds a **concrete** (non-abstract) `key` property to the ABC that returns `self.name`. Private providers subclass `BaseDataProvider` and inherit it; no existing subclass changes.

```python
# backend/app/providers/base.py — one concrete property added to BaseDataProvider

    @property
    def key(self) -> str:
        """Registry key required by ExtensionRegistry (#439); always equals name."""
        return self.name
```

```python
# backend/app/providers/__init__.py  (after the change)

from app.core.extensions import ExtensionRegistry


class DataProviderFactory:
    _registry: ExtensionRegistry[BaseDataProvider] = ExtensionRegistry()

    @classmethod
    def register(cls, provider: BaseDataProvider, *, replace: bool = False) -> None:
        # Raises ExtensionDuplicateError (app.exceptions) on a duplicate name unless
        # replace=True, and ExtensionDescriptorError if provider.key is not a
        # non-empty str — both from #439; nothing is re-implemented here.
        cls._registry.register(provider, replace=replace)
        logger.debug(f"DataProviderFactory: Registered provider '{provider.name}'.")

    @classmethod
    def get(cls, name: str) -> BaseDataProvider:
        provider = cls._registry.get(name)
        if provider is None:
            raise ValueError(
                f"DataProviderFactory: Unknown provider '{name}'. "
                f"Registered: {[p.name for p in cls._registry.get_all()]}"
            )
        return provider

    @classmethod
    def get_or_none(cls, name: str) -> Optional[BaseDataProvider]:
        return cls._registry.get(name)

    @classmethod
    def get_available(cls) -> List[str]:
        return [p.name for p in cls._registry.get_all() if p.is_available()[0]]

    @classmethod
    def get_all_with_classes(cls) -> List[Dict[str, Any]]:
        return [
            {
                "name": p.name,
                "classes": p.supported_asset_classes,
                "available": p.is_available()[0],
                "status_message": p.is_available()[1],
            }
            for p in cls._registry.get_all()
        ]

    @classmethod
    def all(cls) -> Dict[str, BaseDataProvider]:
        return {p.name: p for p in cls._registry.get_all()}


# Built-in auto-registration — unchanged from today
DataProviderFactory.register(MassiveDataProvider())
DataProviderFactory.register(IBKRDataProvider())
```

**Byte-identical default behaviour.** `ExtensionRegistry` stores entries in an insertion-ordered `dict` (`backend/app/core/extensions.py:31,46`) and `register(..., replace=True)` on an existing key reassigns in place, keeping that key's position, so the default deployment lists and resolves the same two providers in the same order (`massive` → `ibkr`) as today (`backend/app/providers/__init__.py:105-106`). The unknown-provider `ValueError` keeps today's exact message including the `Registered: [...]` suffix (`__init__.py:60-64`), `register()` keeps its debug log (`__init__.py:49`), `all()` still returns a fresh `dict` keyed by name (`__init__.py:93`), and `get_all_with_classes()` keeps its four-key shape (`__init__.py:80-88`). `get()` tests `is None` rather than truthiness so a mock provider is never mis-reported as unknown.

**Files changed by this issue** (the whole implementation surface):

| File | Change |
|---|---|
| `backend/app/providers/base.py` | Add the concrete `key` property to `BaseDataProvider` |
| `backend/app/providers/__init__.py` | Replace `_providers` dict with `_registry: ExtensionRegistry[BaseDataProvider]`; add keyword-only `replace` to `register()`; update the module docstring (`:20-24`, "Adding a new provider") to mention `MARKETHAWK_EXTENSION_MODULES` |
| `backend/tests/fixtures/providers.py` | Rewrite the two fixtures that poke `_providers` (see **Test fixture update**) |
| `backend/tests/providers/test_data_provider_factory.py` | **New** (see **Tests**) |

**Files explicitly not touched:** `backend/app/providers/ibkr.py`, `backend/app/providers/ibkr_orders.py`, `backend/app/providers/massive.py`, `backend/app/core/config.py`, `backend/app/main.py`, `backend/app/core/celery_app.py`, every router/service/task call site listed under **Current state on main**, and `backend/tests/tasks/test_paper_exit.py:97,144` (those `patch("app.providers.DataProviderFactory")` calls replace the whole class and are unaffected). No credential, settings or IBKR connection handling changes.

### How extension providers register

Extension modules (loaded by the #439 extension loader from `MARKETHAWK_EXTENSION_MODULES`) call `DataProviderFactory.register(MyProvider())` as an import side-effect — identical to how built-ins register. The factory routes through `ExtensionRegistry.register(provider, replace=replace)`, which enforces duplicate rejection automatically.

```python
# myedge/providers.py  — example private module
from app.providers import DataProviderFactory
from app.providers.base import BaseDataProvider


class MyEdgeProvider(BaseDataProvider):
    @property
    def name(self) -> str:
        return "myedge"

    @property
    def supported_asset_classes(self) -> list[str]:
        return ["stocks"]

    def is_available(self) -> tuple[bool, str]:
        return True, "Ready"

    # get_bars / get_snapshots / get_ticker_details per BaseDataProvider


DataProviderFactory.register(MyEdgeProvider())
```

### Process scope

The #439 loader runs in the API process (`create_app()`, `backend/app/main.py:463-465`) and in every Celery process (`worker_init` handler, `backend/app/core/celery_app.py:37-44`). In the API process `app.providers` is imported at module load by `backend/app/routers/futures.py:18` and `backend/app/services/stock_data.py:21`, i.e. during router setup and therefore before `load_extension_modules()` runs, so built-ins are registered first. In the Celery worker the tasks import the factory lazily (`backend/app/tasks/sync.py:586`, `backend/app/tasks/trading.py:405`), but a private module must itself `from app.providers import DataProviderFactory`, which executes the built-in registrations before the module's own `register()` call — there is no ordering hazard in either process. The `live-scanner` process (`backend/live_scanner/main.py:20-27`) never imports `app.providers`: it uses its own `LiveDataProvider` Protocol (`backend/live_scanner/provider.py`) with an `ib_insync` adapter, so the loader being deferred there (#439) has no effect on this ticket.

### Safety boundary

This ticket changes only how providers are stored, never what they do. `backend/app/providers/ibkr.py`, `ibkr_orders.py` and `massive.py` are not modified, and no credential or settings handling is touched (the built-in providers keep guarding their own configuration: "if its config is missing it still registers but `is_available()` returns False", `__init__.py:97-99`). A private module can shadow a built-in name such as `massive` or `ibkr` only by passing `replace=True`; that escape hatch exists for test fixtures and deliberate operator override, under #439's trust boundary (`MARKETHAWK_EXTENSION_MODULES` is host-`.env`-only and already runs arbitrary code with the process's full privileges). Because the issue text matches the adapter's `ibkr` sensitivity keyword, the implementation PR is expected to route to a human merge review; the not-touched list above is what the conformance gate should check.

### No separate ProviderDescriptor

`BaseDataProvider` is self-describing: `name`, `supported_asset_classes`, and `is_available()` are all abstract properties that cannot be omitted. A registration-time descriptor object would add no validation that the ABC does not already enforce, and would require changes to every call site. The only ABC addition is the concrete `key` property (returning `name`) that `ExtensionRegistry` requires; it is not abstract, so private subclasses inherit it. The existing `get_all_with_classes()` output is the "provider descriptor" the acceptance criteria references.

### GET /api/v1/futures/providers — no change

`backend/app/routers/futures.py:187` calls `DataProviderFactory.get_all_with_classes()`. Because the factory's public API is unchanged, the endpoint continues to return the same shape and automatically includes any extension-registered providers.

### Test fixture update

`mock_polygon_provider` and `mock_futures_provider` in `backend/tests/fixtures/providers.py` (`:49-57` and `:75-83`; consumed by `backend/tests/api/test_stocks.py`, `test_futures.py` and `test_news.py`) assign a `MagicMock` straight into `DataProviderFactory._providers`. They break as-is, and a bare `MagicMock` also fails registry validation because its auto-created `.key` attribute is a `MagicMock`, not a `str` (`ExtensionDescriptorError`). Both fixtures become:

```python
mock = MagicMock()
mock.name = "massive"  # or "ibkr"
mock.key = "massive"  # ExtensionRegistry reads .key; must be a non-empty str
...
original = DataProviderFactory.get_or_none("massive")
DataProviderFactory.register(mock, replace=True)  # keeps massive's position in the order

yield mock

DataProviderFactory.register(original, replace=True)
```

The `original is None` / `pop()` branch is dropped: built-ins always register at import, so `original` is never `None`. `backend/tests/tasks/test_paper_exit.py:97,144` patch the whole `DataProviderFactory` class and are unaffected — no change.

## Alternatives Considered

### B: DataProviderFactory extends ExtensionRegistry directly

`DataProviderFactory` inherits from `ExtensionRegistry[BaseDataProvider]`. Rejected because the factory's public surface uses classmethods with provider-specific projections (`get_available`, `get_all_with_classes`) that don't map cleanly onto `ExtensionRegistry`'s generic operations. Extending would force the factory to override most inherited methods anyway, removing the benefit of inheritance while coupling provider concepts into the shared primitive. Composition (Approach A) keeps `ExtensionRegistry` generic and reusable across all extension points in the epic.

### C: Global namespaced extension registry

One global registry holds all extension types keyed by `(type, name)`. Rejected because it couples unrelated subsystems (providers, scanners, channels) through a shared global, contradicting the per-domain pattern this epic establishes: #440 gives the scanner orchestrator its own `_REGISTRY: ExtensionRegistry[ScannerDescriptor]` instance in `scan_orchestrator.py`, and this ticket gives providers their own `ExtensionRegistry[BaseDataProvider]`. (`_SCREENER_REGISTRY` in `discovery_service.py` is a universe-screener dict keyed by asset class and is out of scope for the epic's v1.) The `ExtensionRegistry` from #439 is designed as a per-domain primitive, not a global singleton.

## Tests

All tests run in the CI test job (`backend/`: `ruff check .` with `line-length = 88`, `pip-audit`, `python -m pytest` with `--cov=app --cov-fail-under=60` from `backend/pyproject.toml`). No test uses `os.geteuid()` or any other environment-conditional skip.

`backend/tests/providers/test_data_provider_factory.py` (new):
- isolation fixture, mirroring #440 and `backend/tests/core/test_extensions.py:110`: snapshot `DataProviderFactory.all()` before the test, `DataProviderFactory._registry.clear()` in teardown, then re-`register(p, replace=True)` each snapshotted provider in its original order
- built-ins: after `import app.providers`, `list(DataProviderFactory.all())` is exactly `["massive", "ibkr"]` (same providers, same order as today) and `get_all_with_classes()` has the four-key shape
- private provider through the real loader (issue AC 2): inject a `types.ModuleType` into `sys.modules` whose body defines a `BaseDataProvider` subclass and calls `DataProviderFactory.register(...)`, call `load_extension_modules([name])` from `app.core.extensions`, then assert the provider is returned by `get`/`get_or_none`, listed by `get_available` (when `is_available()` is `(True, ...)`), present in `get_all_with_classes()` and `all()`, and appears in `GET /api/v1/futures/providers` via the test client
- duplicate name: a second `register()` for `"massive"` raises `ExtensionDuplicateError` (from `app.exceptions`) and leaves the original in place; `register(..., replace=True)` succeeds and `get("massive")` returns the replacement at the same position
- descriptor validation: a provider whose `name` is `""` raises `ExtensionDescriptorError`
- unknown name: `get("nope")` raises `ValueError` whose message contains `"Unknown provider 'nope'"` and every registered name; `get_or_none("nope")` returns `None`

`backend/tests/fixtures/providers.py`: rewritten per **Test fixture update**; the existing consumers in `tests/api/test_stocks.py`, `test_futures.py`, `test_news.py` need no change.

## Resolved Questions

- **`ExtensionRegistry` key convention** — resolved by #439 (merged): `register(descriptor, *, replace=False)` reads `descriptor.key`; `get(key) -> T | None`; `get_all() -> list[T]`; `clear()` is test-only. The bridge is the concrete `key` property on `BaseDataProvider` described above.
- **Re-import guard** — none needed. `load_extension_modules()` is idempotent by contract (`backend/app/core/extensions.py:60-66`: `sys.modules` makes repeat calls no-ops), so a configured module body — and therefore its `register()` call — executes exactly once per process even though the loader runs from both `create_app()` and `worker_init`. `replace=True` on `DataProviderFactory.register()` exists for test fixtures and deliberate operator override only; it is not a re-import workaround.

## Assumptions

- **`ExtensionRegistry[T]`, `ExtensionDuplicateError` and `ExtensionDescriptorError` are on `main` from #439** (`backend/app/core/extensions.py`, `backend/app/exceptions.py:161-181`). This spec is written against that merged contract; there is no fallback path.
- **`BaseDataProvider.name` is stable per-provider** (not computed dynamically per call): `backend/app/providers/ibkr.py:161-162` and `backend/app/providers/massive.py:70-71` return string constants. `key` returns `name` and is therefore equally stable; it is the registry key.
- **Built-in auto-registration remains at module-import time** (bottom of `providers/__init__.py`). The extension loader from #439 is responsible only for loading external module paths — not for re-loading already-imported built-in modules.
- **No changes to `backend/app/routers/futures.py`**, `routers/scanner.py`, task files, or any other call site. The factory's public API contract is the sole migration surface.
