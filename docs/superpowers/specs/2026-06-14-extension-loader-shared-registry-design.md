# Extension Loader and Shared Registry Primitives Design

**Date:** 2026-06-14  
**Issue:** #439 (parent: #438)  
**Revised:** 2026-09-15 (operator amendment after spec-gate review; original 2026-06-14)  
**Status:** Pending review

---

## Overview

MarketHawk needs a foundation for optional third-party extension modules — edge scanners, risk managers, and custom providers that live outside the core repo. This slice adds that foundation: a startup module loader, a generic typed registry primitive, structured extension errors, and unit tests. It makes **no behavioral change** to existing scanner/provider/trading execution; the built-in scan registries (`scan_orchestrator._REGISTRY`, `discovery_service._SCREENER_REGISTRY`) are untouched. Per the parent epic's design decisions, extension modules are loaded from an explicit module list; Python entry-point discovery is intentionally deferred and is out of scope for this slice.

---

## Requirements

1. **Setting**: `MARKETHAWK_EXTENSION_MODULES: Annotated[list[str], NoDecode] = []` in `app/core/config.py`. Accepts a comma-separated env var (`MARKETHAWK_EXTENSION_MODULES=myedge.scanners,myedge.risk`). The `NoDecode` annotation (pydantic-settings >= 2.7) is required: without it `EnvSettingsSource`/`DotEnvSettingsSource` JSON-decode a `list[str]` value *before* any validator runs, so a bare comma-separated string (and the empty string) raises `SettingsError` at startup — verified on pydantic-settings 2.5.2 and 2.15.0. Parsed at Settings load time via a `mode="before"` field_validator — not at use-site: whitespace around entries is stripped, empty entries are dropped, and both `""` and unset yield `[]`. A JSON-array value is not supported (contrast with `CORS_ORIGINS`). Requires raising the lower bound in `backend/requirements.txt` to `pydantic-settings>=2.7,<3.0`.

2. **Loader**: `load_extension_modules(module_names: list[str]) -> None` in `app/core/extensions.py`. Imports each module via `importlib.import_module()`. The loader is **idempotent by contract**: calling it any number of times with the same names executes each module body exactly once (Python's `sys.modules` cache), so it is safe to call from more than one process entry point. It logs the configured module list at INFO on every call (`Loading extension modules: ['myedge.scanners', 'myedge.risk']`, or `No extension modules configured` when the list is empty). **Any** exception raised while importing a configured module — `ModuleNotFoundError`, `SyntaxError`, or an arbitrary exception from the module body — is wrapped in `ExtensionImportError` (a structured `MarketHawkError` subclass) carrying the failing module name and original error, chained with `from exc`; a raw traceback never escapes the loader. **Process scope**: the loader is called (a) from `create_app()` in `app/main.py` immediately after the existing built-in scanner imports — the uvicorn API process — **and** (b) from a `worker_init` signal handler in `app/core/celery_app.py`, which covers `celery-worker`, `forecast-worker`, `celery-beat` and `flower`, because scans execute in the Celery worker, not in the API process. The `live-scanner` process (`python -m live_scanner.main`) does **not** load extension modules in this slice; live-scanner support is explicitly deferred to a follow-up ticket.

3. **Generic registry**: `ExtensionRegistry[T]` class in `app/core/extensions.py`. At `register(descriptor, *, replace=False)`:
   - Validates `descriptor.key` is a non-empty `str`; raises `ExtensionDescriptorError` if not.
   - Rejects duplicate keys by raising `ExtensionDuplicateError` unless `replace=True` is passed.
   - Returns the registered descriptor.
   - Provides `get(key) -> T | None` and `get_all() -> list[T]`.
   - Provides `clear() -> None`, which empties the registry. This exists for test setup/teardown of module-level registry instances (consumers such as #443 declare registries at module scope); it is not a runtime API and production code must not call it.

4. **Structured errors** in `app/exceptions.py` (following the existing `MarketHawkError` hierarchy):
   - `ExtensionImportError` — `module_name: str`, `original_error: str`; `is_retryable=False`
   - `ExtensionDescriptorError` — `descriptor_repr: str`, `field: str`; `is_retryable=False`
   - `ExtensionDuplicateError` — `key: str`; `is_retryable=False`
   - `ExtensionRuntimeError` — `key: str`, `original_error: str`; `is_retryable=True`

5. **Unit tests** in `backend/tests/core/test_extensions.py`:
   - Successful module import: a `types.ModuleType` carrying a side-effect counter is injected into `sys.modules` (or a temporary package is placed on `sys.path`) — not a mocked `importlib`, which would only test the mock
   - Exactly-once: calling the loader twice with the same module name executes the module body once (counter == 1)
   - Import failure (`ModuleNotFoundError`) → `ExtensionImportError` with `module_name` set and `__cause__` being the original exception
   - Module body raising a non-`ImportError` exception (e.g. `ValueError`) → `ExtensionImportError` (not a raw `ValueError`)
   - Empty module list → no-op (no error; `No extension modules configured` logged)
   - `ExtensionRegistry.register()` success path
   - Duplicate key → `ExtensionDuplicateError`
   - `replace=True` → silent overwrite, no error
   - Descriptor with missing/non-string key → `ExtensionDescriptorError`
   - `ExtensionRegistry.get()` and `get_all()`
   - `ExtensionRegistry.clear()` empties the registry
   - `worker_init` handler: with the loader patched, the handler in `app/core/celery_app.py` calls it with `settings.MARKETHAWK_EXTENSION_MODULES`; with the loader raising `ExtensionImportError`, the handler raises `SystemExit`

   **Settings tests** in `backend/tests/core/test_config.py` (house style: `Settings(...)` kwargs / `monkeypatch.setenv`, cf. the existing `JWT_SECRET_KEY` and `REDIS_PASSWORD` tests):
   - `MARKETHAWK_EXTENSION_MODULES="a, b,,c"` → `["a", "b", "c"]`
   - `MARKETHAWK_EXTENSION_MODULES=""` → `[]`
   - unset → `[]`

---

## Architecture

### Files changed

| File | Change |
|------|--------|
| `backend/app/core/extensions.py` | **New** — `ExtensionRegistry[T]` (incl. `clear()`), `load_extension_modules()` |
| `backend/app/exceptions.py` | **Add** four new `MarketHawkError` subclasses |
| `backend/app/core/config.py` | **Add** `MARKETHAWK_EXTENSION_MODULES` field (`Annotated[list[str], NoDecode]`) + `mode="before"` validator |
| `backend/app/main.py` | **1 line** — call `load_extension_modules()` after built-in imports |
| `backend/app/core/celery_app.py` | **Add** `worker_init` signal handler calling `load_extension_modules()` (fail-fast via `SystemExit`) |
| `backend/requirements.txt` | **Bound bump** — `pydantic-settings>=2.7,<3.0` (was `>=2.0,<3.0`; `NoDecode` needs 2.7) |
| `.env.example` | **1 commented line** documenting `MARKETHAWK_EXTENSION_MODULES` |
| `backend/tests/core/test_extensions.py` | **New** — 12+ unit tests (Requirement 5) |
| `backend/tests/core/test_config.py` | **Add** 3 Settings parsing tests (Requirement 5) |

### `app/core/extensions.py` sketch

```python
import importlib
import logging
from typing import Generic, TypeVar

from app.exceptions import ExtensionDescriptorError, ExtensionDuplicateError, ExtensionImportError

logger = logging.getLogger(__name__)

T = TypeVar("T")


class ExtensionRegistry(Generic[T]):
    def __init__(self) -> None:
        self._entries: dict[str, T] = {}

    def register(self, descriptor: T, *, replace: bool = False) -> T:
        key = getattr(descriptor, "key", None)
        if not isinstance(key, str) or not key.strip():
            # descriptor_repr goes in the context only; MarketHawkError.__str__ appends context.
            raise ExtensionDescriptorError(
                "Descriptor must have a non-empty str .key",
                descriptor_repr=repr(descriptor),
                field="key",
            )
        if key in self._entries and not replace:
            raise ExtensionDuplicateError(
                f"Key {key!r} already registered; use replace=True to override",
                key=key,
            )
        self._entries[key] = descriptor
        return descriptor

    def get(self, key: str) -> T | None:
        return self._entries.get(key)

    def get_all(self) -> list[T]:
        return list(self._entries.values())

    def clear(self) -> None:
        """Empty the registry. Test setup/teardown support only — not a runtime API."""
        self._entries.clear()


def load_extension_modules(module_names: list[str]) -> None:
    """Import each configured extension module.

    Idempotent by contract: sys.modules makes repeat calls no-ops, so this may be
    invoked from every process entry point (create_app, Celery worker_init).
    """
    if not module_names:
        logger.info("No extension modules configured")
        return
    logger.info("Loading extension modules: %s", module_names)
    for name in module_names:
        try:
            importlib.import_module(name)
        except Exception as exc:  # ModuleNotFoundError, SyntaxError, or anything the module body raises
            # original_error goes in the context only; MarketHawkError.__str__ appends context,
            # so repeating {exc} in the message would print it twice.
            raise ExtensionImportError(
                f"Failed to import extension module {name!r}",
                module_name=name,
                original_error=str(exc),
            ) from exc
```

### `app/exceptions.py` additions

```python
class ExtensionImportError(MarketHawkError):
    def __init__(self, message: str, *, module_name: str, original_error: str, **ctx):
        super().__init__(message, is_retryable=False,
                         module_name=module_name, original_error=original_error, **ctx)
        self.module_name = module_name
        self.original_error = original_error


class ExtensionDescriptorError(MarketHawkError):
    def __init__(self, message: str, *, descriptor_repr: str, field: str, **ctx):
        super().__init__(message, is_retryable=False,
                         descriptor_repr=descriptor_repr, field=field, **ctx)
        self.descriptor_repr = descriptor_repr
        self.field = field


class ExtensionDuplicateError(MarketHawkError):
    def __init__(self, message: str, *, key: str, **ctx):
        super().__init__(message, is_retryable=False, key=key, **ctx)
        self.key = key


class ExtensionRuntimeError(MarketHawkError):
    def __init__(self, message: str, *, key: str, original_error: str, **ctx):
        super().__init__(message, is_retryable=True,
                         key=key, original_error=original_error, **ctx)
        self.key = key
        self.original_error = original_error
```

### `app/core/config.py` addition

```python
from typing import Annotated

from pydantic_settings import NoDecode  # pydantic-settings >= 2.7

# Extension modules — comma-separated; NOT a JSON array (contrast with CORS_ORIGINS).
# NoDecode stops pydantic-settings from JSON-decoding the raw env/.env value before
# validation; without it the comma-separated form raises SettingsError at startup.
# Example: MARKETHAWK_EXTENSION_MODULES=myedge.scanners,myedge.risk
MARKETHAWK_EXTENSION_MODULES: Annotated[list[str], NoDecode] = []

@field_validator("MARKETHAWK_EXTENSION_MODULES", mode="before")
@classmethod
def split_extension_modules(cls, v):
    if isinstance(v, str):
        return [m.strip() for m in v.split(",") if m.strip()]
    return v
```

### `app/main.py` change

```python
# Populate scan_orchestrator registry — must be after router includes.
importlib.import_module("app.services.pre_market_scan")
importlib.import_module("app.services.oversold_bounce_scan")
importlib.import_module("app.services.liquidity_hunt")

# Load user-configured extension modules (MARKETHAWK_EXTENSION_MODULES env var).
# Must come after built-in imports so built-in registrations are already present
# when extension modules attempt to build on top of them.
from app.core.extensions import load_extension_modules
load_extension_modules(settings.MARKETHAWK_EXTENSION_MODULES)
```

### `app/core/celery_app.py` change

```python
from celery.signals import worker_init  # celery.signals is already imported in this module


@worker_init.connect
def _load_extension_modules(**_kwargs):
    from app.core.extensions import load_extension_modules
    from app.exceptions import ExtensionImportError

    try:
        load_extension_modules(settings.MARKETHAWK_EXTENSION_MODULES)
    except ExtensionImportError as exc:
        logging.getLogger(__name__).critical(
            "Extension load failed; worker will not start: %s", exc
        )
        raise SystemExit(1) from exc
```

Celery's signal dispatcher (`celery.utils.dispatch.Signal.send`) catches and logs any `Exception` raised by a handler and carries on, so raising `ExtensionImportError` alone would leave the worker running silently without its extensions. Converting it to `SystemExit` (a `BaseException`) after a CRITICAL log is what gives the worker the same fail-fast semantics `create_app()` gets for free.

### `backend/requirements.txt` change

`pydantic-settings>=2.0,<3.0` → `pydantic-settings>=2.7,<3.0` (lower bound only; `NoDecode` was added in 2.7.0).

### `.env.example` change

One commented line, placed with the other optional settings:

```
# MARKETHAWK_EXTENSION_MODULES=myedge.scanners,myedge.risk  # comma-separated extension modules (host-operator-only; default: none)
```

### Call-site placement rationale

The loader runs at two process entry points — `create_app()` in the API process and `worker_init` in the Celery processes — and in neither case in `lifespan()`:
1. **Fail-fast semantics**: an unhandled exception in `create_app()` prevents the ASGI app from being returned at all — stronger than `lifespan()`, which the codebase wraps in `try/except` with graceful-degrade semantics. The `worker_init` handler reproduces this with `SystemExit(1)` (see above).
2. **Consistency**: all registry population (built-ins + extensions) happens in one place per process, after the built-in imports.
3. **Import ordering**: extension modules that register scanners can rely on built-in registrations already being present.
4. **Process scope**: `create_app()` is reached only by `uvicorn app.main:app`; `celery-worker`, `forecast-worker`, `celery-beat` and `flower` load `app.core.celery_app` (`include=["app.tasks"]`) and never call it. Scans execute in the worker, so an API-only loader would list a private scanner in the API while the worker reported it unknown. `live-scanner` (`python -m live_scanner.main`) is a third entry point and is deferred: it gets no loader call in this slice, and a follow-up ticket owns it.

### Trust boundary

`MARKETHAWK_EXTENSION_MODULES` causes arbitrary Python to be imported with the full privileges of the backend and worker processes — database, Redis, IBKR credentials, `JWT_SECRET_KEY`. That is acceptable only because of where it can be set:

- The sole input path is the host `.env` file consumed by `docker-compose.yml` (`${VAR}` interpolation / `env_file`) and by `deploy.yml` on the host — the same trust boundary as `JWT_SECRET_KEY` and `DATABASE_URL`. Only host operators with write access to `.env` may set it.
- It MUST never become settable through any HTTP endpoint, database row, scanner-config JSON surface, or other runtime API. Any future ticket that proposes such a surface is a security change and needs its own review.
- The loader logs the configured module list at INFO on every startup so that an unexpected entry is visible in Seq without reading `.env`.
- The default is empty (`[]`): a deployment that does not set the variable has no changed code path.

---

## Alternatives Considered

### Alt 1: Put primitives in `app/services/extensions.py`

Rejected. The loader and registry are infrastructure (startup wiring, no domain knowledge), consistent with `app/core/`. Placing them in `services/` would make a sibling-level dependency where `scan_orchestrator.py` (a service) depends on `extensions.py` (also a service), blurring the core/services boundary.

### Alt 2: `required_fields` list at registry construction

Rejected (YAGNI). `ExtensionRegistry(required_fields=["key", "display_name"])` adds configurability for descriptor shapes that don't exist yet. Each concrete descriptor is a `@dataclass(frozen=True)` — constructing one without required fields already raises `TypeError`. The registry's only genuine responsibility is `.key` uniqueness and non-emptiness.

### Alt 3: Call loader in `lifespan()`

Rejected. `lifespan()` in `main.py` wraps DB and Redis startup in `try/except` that logs and continues. Placing a hard-failure requirement in a context manager whose established convention is "degrade gracefully" would be inconsistent and easy to accidentally neuter.

### Alt 4: Extension errors in `app/core/extensions.py` (co-located)

Viable but rejected in favor of consistency. All existing domain errors (`ScanError`, `ProviderError`, `DataFetchError`, `UniverseNotFoundError`) live in `app/exceptions.py`. Extension errors are also domain errors that callers catch; placing them in `app/exceptions.py` follows the house pattern and keeps the import graph simple.

---

## Open Questions (non-blocking)

1. **Replacement semantics**: should `replace=True` on `register()` log a warning? Not specified in the issue — default to silent replacement (same behavior as the existing `scan_orchestrator.register()` which silently overwrites today). Can be added later.

2. **Extension module ordering**: does registration order matter when multiple extension modules register to the same point? Not relevant until a concrete extension point exists. The current spec preserves insertion order via `dict` (Python 3.7+).

3. **`pocket_pivot` and `trend_pullback` imports**: the existing `create_app()` block imports `pre_market_scan`, `oversold_bounce_scan`, and `liquidity_hunt` but not `pocket_pivot` or `trend_pullback` — those are imported via Celery task wiring. The new loader does not change this; it is orthogonal.

---

## Assumptions

- **[ASSUMPTION]** `ExtensionRuntimeError` (runtime execution failure) is defined in this slice for completeness (AC specifies it), but is not raised anywhere in this slice since no extension execution path exists yet. It will be wired up when extension point dispatch is added.
- **[ASSUMPTION]** The `MARKETHAWK_EXTENSION_MODULES` default is `[]` (empty), which means `load_extension_modules([])` is a no-op — no behavior change to the default deployment. Because the default is a valid value that never reaches the validator, no `os.environ.setdefault(...)` line in `tests/conftest.py` is needed; the earlier assumption to add one is withdrawn (with the original un-annotated field, `""` would itself have raised `SettingsError` in every test).
- **[ASSUMPTION]** Once the bound is bumped, the pydantic-settings resolved into the image is >= 2.7 (2.15.0 resolves today under `<3.0`); `NoDecode` is imported from `pydantic_settings` directly.
- **[ASSUMPTION]** Celery's `worker_init` fires once per worker before tasks are consumed and is the documented hook for one-time worker setup; if a pool variant is found to skip it, `worker_process_init` is the fallback, and the loader's idempotency makes double-firing harmless.

---

## Consumers (sibling tickets under #438)

The names below are the contract; sibling specs written before this amendment are reconciled to them at their plan stage.

- **#440** scanner registration — duplicate scanner keys raise `ExtensionDuplicateError`; its spec's `ExtensionRegistrationError` does not exist and must not be introduced.
- **#441** data providers — duplicate provider names → `ExtensionDuplicateError`; the registry is `ExtensionRegistry[T]`.
- **#442** alert channels — `get()` returns `None` for unknown keys; the dispatcher supplies its own structured unknown-channel handling.
- **#443** broker adapter — already written against `ExtensionRegistry[BrokerAdapterDescriptor]`, `ExtensionDuplicateError` and `ExtensionDescriptorError` from `app.core.extensions`; exact match. Its module-level `BROKER_REGISTRY` is why `clear()` exists.
- **#444** sizing/risk rules — keyed registration in deterministic order; `get_all()` preserves insertion order.
- **#445** outcome analyzer — its spec's `DescriptorRegistry` base class maps to `ExtensionRegistry[T]`; there is no separate base class.
- **#446** documentation — imports come from `app.core.extensions`, not `app.extensions`; the startup log line is `Loading extension modules: [...]` at INFO; live-scanner support is deferred (Requirement 2).
