# Extension Loader and Shared Registry Primitives Design

**Date:** 2026-06-14  
**Issue:** #439 (parent: #438)  
**Status:** Pending review

---

## Overview

MarketHawk needs a foundation for optional third-party extension modules — edge scanners, risk managers, and custom providers that live outside the core repo. This slice adds that foundation: a startup module loader, a generic typed registry primitive, structured extension errors, and unit tests. It makes **no behavioral change** to existing scanner/provider/trading execution; the built-in scan registries (`scan_orchestrator._REGISTRY`, `discovery_service._SCREENER_REGISTRY`) are untouched.

---

## Requirements

1. **Setting**: `MARKETHAWK_EXTENSION_MODULES: list[str] = []` in `app/core/config.py`. Accepts a comma-separated env var (`MARKETHAWK_EXTENSION_MODULES=myedge.scanners,myedge.risk`). Parsed at Settings load time via a `mode="before"` field_validator — not at use-site.

2. **Loader**: `load_extension_modules(module_names: list[str]) -> None` in `app/core/extensions.py`. Imports each module via `importlib.import_module()` exactly once (Python's `sys.modules` cache satisfies idempotency). On `ImportError`, raises `ExtensionImportError` (a structured `MarketHawkError` subclass) with the failing module name and original error. Called from `create_app()` in `app/main.py` immediately after the existing built-in scanner imports.

3. **Generic registry**: `ExtensionRegistry[T]` class in `app/core/extensions.py`. At `register(descriptor, *, replace=False)`:
   - Validates `descriptor.key` is a non-empty `str`; raises `ExtensionDescriptorError` if not.
   - Rejects duplicate keys by raising `ExtensionDuplicateError` unless `replace=True` is passed.
   - Returns the registered descriptor.
   - Provides `get(key) -> T | None` and `get_all() -> list[T]`.

4. **Structured errors** in `app/exceptions.py` (following the existing `MarketHawkError` hierarchy):
   - `ExtensionImportError` — `module_name: str`, `original_error: str`; `is_retryable=False`
   - `ExtensionDescriptorError` — `descriptor_repr: str`, `field: str`; `is_retryable=False`
   - `ExtensionDuplicateError` — `key: str`; `is_retryable=False`
   - `ExtensionRuntimeError` — `key: str`, `original_error: str`; `is_retryable=True`

5. **Unit tests** in `backend/tests/core/test_extensions.py`:
   - Successful module import (mock importlib)
   - Import failure → `ExtensionImportError` with module name
   - Empty module list → no-op (no error)
   - `ExtensionRegistry.register()` success path
   - Duplicate key → `ExtensionDuplicateError`
   - `replace=True` → silent overwrite, no error
   - Descriptor with missing/non-string key → `ExtensionDescriptorError`
   - `ExtensionRegistry.get()` and `get_all()`

---

## Architecture

### Files changed

| File | Change |
|------|--------|
| `backend/app/core/extensions.py` | **New** — `ExtensionRegistry[T]`, `load_extension_modules()` |
| `backend/app/exceptions.py` | **Add** four new `MarketHawkError` subclasses |
| `backend/app/core/config.py` | **Add** `MARKETHAWK_EXTENSION_MODULES` field + validator |
| `backend/app/main.py` | **1 line** — call `load_extension_modules()` after built-in imports |
| `backend/tests/core/test_extensions.py` | **New** — 8+ unit tests |

### `app/core/extensions.py` sketch

```python
import importlib
from typing import Generic, TypeVar

from app.exceptions import ExtensionDescriptorError, ExtensionDuplicateError, ExtensionImportError

T = TypeVar("T")


class ExtensionRegistry(Generic[T]):
    def __init__(self) -> None:
        self._entries: dict[str, T] = {}

    def register(self, descriptor: T, *, replace: bool = False) -> T:
        key = getattr(descriptor, "key", None)
        if not isinstance(key, str) or not key.strip():
            raise ExtensionDescriptorError(
                f"Descriptor must have a non-empty str .key; got {descriptor!r}",
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


def load_extension_modules(module_names: list[str]) -> None:
    for name in module_names:
        try:
            importlib.import_module(name)
        except ImportError as exc:
            raise ExtensionImportError(
                f"Failed to import extension module {name!r}: {exc}",
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
# Extension modules — comma-separated; NOT a JSON array (contrast with CORS_ORIGINS).
# Example: MARKETHAWK_EXTENSION_MODULES=myedge.scanners,myedge.risk
MARKETHAWK_EXTENSION_MODULES: list[str] = []

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

### Call-site placement rationale

The loader is called in `create_app()` (not `lifespan()`) for three reasons:
1. **Fail-fast semantics**: an unhandled exception in `create_app()` prevents the ASGI app from being returned at all — stronger than `lifespan()`, which the codebase wraps in `try/except` with graceful-degrade semantics.
2. **Consistency**: all registry population (built-ins + extensions) happens in one place.
3. **Import ordering**: extension modules that register scanners can rely on built-in registrations already being present.

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
- **[ASSUMPTION]** The `MARKETHAWK_EXTENSION_MODULES` default is `[]` (empty), which means `load_extension_modules([])` is a no-op — no behavior change to the default deployment.
- **[ASSUMPTION]** `tests/conftest.py` will need `os.environ.setdefault("MARKETHAWK_EXTENSION_MODULES", "")` before app imports, consistent with the existing pattern for new Settings fields with validators (see `backend-patterns.md` memory entry).
