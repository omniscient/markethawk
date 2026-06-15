# Data Provider Extension Registry Design

**Date:** 2026-06-15  
**Issue:** #441 — Unify data provider registration under extension registry  
**Parent epic:** #438 — Formal module extension points for MarketHawk  
**Blocked by:** #439 — Add extension loader and shared registry primitives  
**Status:** Spec pending review

## Overview

`DataProviderFactory` currently stores providers in a plain class-level dict (`_providers: Dict[str, BaseDataProvider]`) and silently overwrites duplicate names. This is incompatible with the extension registry introduced in #439, which validates descriptors and rejects duplicate registrations with structured errors.

This spec migrates `DataProviderFactory` to wrap a `BaseRegistry[BaseDataProvider]` instance from #439, so that extension-loaded providers (private modules registered via `MARKETHAWK_EXTENSION_MODULES`) appear through the same factory surface as built-in providers, and duplicate names produce a `DuplicateRegistrationError` instead of a silent overwrite. The factory's public API (`get`, `get_or_none`, `get_available`, `get_all_with_classes`, `all`, `register`) is unchanged.

## Requirements

From the acceptance criteria:

1. **API preservation** — `DataProviderFactory.get`, `get_or_none`, `get_available`, `get_all_with_classes`, and `all` behave identically from the perspective of callers. No existing call site changes.
2. **Extension visibility** — A provider registered from a configured extension module (loaded by the #439 extension loader at startup) is returned by `get`, listed by `get_available`, and appears in `get_all_with_classes`.
3. **Descriptor fields** — Every registered provider exposes `name`, `supported_asset_classes`, and `is_available()`. These are already enforced by `BaseDataProvider`'s abstract interface.
4. **Duplicate rejection** — Registering a second provider under a name already in the registry raises `DuplicateRegistrationError` (from #439). Today's silent overwrite must not survive.
5. **Test coverage** — Unit tests cover: built-in providers registered at import time; a test-only provider registered directly via `DataProviderFactory.register()`; duplicate name rejection; and the `get`/`get_or_none`/`get_available`/`all` paths after registration.

## Architecture

### Decision: DataProviderFactory wraps BaseRegistry (composition)

`DataProviderFactory` keeps its class structure and classmethods. Internally, the class-level `_providers: Dict` is replaced by `_registry: BaseRegistry[BaseDataProvider]` from #439.

```python
# backend/app/providers/__init__.py  (after the change)

from app.core.extensions import BaseRegistry, DuplicateRegistrationError  # from #439

class DataProviderFactory:
    _registry: BaseRegistry[BaseDataProvider] = BaseRegistry()

    @classmethod
    def register(cls, provider: BaseDataProvider) -> None:
        cls._registry.register(provider.name, provider)  # raises DuplicateRegistrationError on collision

    @classmethod
    def get(cls, name: str) -> BaseDataProvider:
        provider = cls._registry.get_or_none(name)
        if not provider:
            raise ValueError(f"Unknown provider: {name}")
        return provider

    @classmethod
    def get_or_none(cls, name: str) -> Optional[BaseDataProvider]:
        return cls._registry.get_or_none(name)

    @classmethod
    def get_available(cls) -> List[str]:
        return [name for name, p in cls._registry.all().items() if p.is_available()[0]]

    @classmethod
    def get_all_with_classes(cls) -> List[Dict[str, Any]]:
        return [
            {
                "name": p.name,
                "classes": p.supported_asset_classes,
                "available": p.is_available()[0],
                "status_message": p.is_available()[1],
            }
            for p in cls._registry.all().values()
        ]

    @classmethod
    def all(cls) -> Dict[str, BaseDataProvider]:
        return dict(cls._registry.all())


# Built-in auto-registration — unchanged from today
DataProviderFactory.register(MassiveDataProvider())
DataProviderFactory.register(IBKRDataProvider())
```

No other files change as part of this issue.

### How extension providers register

Extension modules (loaded by the #439 extension loader from `MARKETHAWK_EXTENSION_MODULES`) call `DataProviderFactory.register(MyProvider())` as an import side-effect — identical to how built-ins register. The factory routes through `BaseRegistry.register(provider.name, provider)`, which enforces duplicate rejection automatically.

### No separate ProviderDescriptor

`BaseDataProvider` is self-describing: `name`, `supported_asset_classes`, and `is_available()` are all abstract properties that cannot be omitted. A registration-time descriptor object would add no validation that the ABC does not already enforce, and would require changes to every call site. The existing `get_all_with_classes()` output is the "provider descriptor" the acceptance criteria references.

### GET /api/v1/futures/providers — no change

`routers/futures.py` calls `DataProviderFactory.get_all_with_classes()`. Because the factory's public API is unchanged, the endpoint continues to return the same shape and automatically includes any extension-registered providers.

### Test fixture update

Existing tests and fixtures reach into `DataProviderFactory._providers` directly. Those must be updated to use `DataProviderFactory._registry` (or, preferably, `DataProviderFactory.all()`) to avoid fragile private-attribute access. Two `patch("app.providers.DataProviderFactory")` sites in `tests/tasks/test_paper_exit.py` should also be reviewed.

## Alternatives Considered

### B: DataProviderFactory extends BaseRegistry directly

`DataProviderFactory` inherits from `BaseRegistry[BaseDataProvider]`. Rejected because the factory's public surface uses classmethods with provider-specific projections (`get_available`, `get_all_with_classes`) that don't map cleanly onto `BaseRegistry`'s generic operations. Extending would force the factory to override most inherited methods anyway, removing the benefit of inheritance while coupling provider concepts into the shared primitive. Composition (Approach A) keeps `BaseRegistry` generic and reusable across all extension points in the epic.

### C: Global namespaced extension registry

One global registry holds all extension types keyed by `(type, name)`. Rejected because it couples unrelated subsystems (providers, scanners, channels) through a shared global, contradicting the established pattern in this codebase where each domain owns its own small registry (`_REGISTRY` in `scan_orchestrator.py`, `_SCREENER_REGISTRY` in `discovery_service.py`). The `BaseRegistry` from #439 is designed as a per-domain primitive, not a global singleton.

## Open Questions

- **`BaseRegistry` key convention** — The #439 spec has not been written yet. This spec assumes `BaseRegistry.register(key: str, item: T)` and `BaseRegistry.get_or_none(key: str) -> Optional[T]`. If #439 uses a different signature (e.g., descriptor objects with a `.key` attribute), the bridge in `DataProviderFactory.register()` will need a small adjustment.
- **Re-import guard** — Because `DuplicateRegistrationError` is now raised on collision, the extension loader from #439 should avoid re-importing modules already in `sys.modules`. If the loader already handles this, no change is needed here. If not, `DataProviderFactory.register()` may need a `replace=True` escape hatch for testing.

## Assumptions

- **`BaseRegistry[T]` is available from #439** before this issue is implemented. This issue makes no sense without it.
- **`BaseDataProvider.name` is stable per-provider** (not computed dynamically per call). Used as the registry key.
- **Built-in auto-registration remains at module-import time** (bottom of `providers/__init__.py`). The extension loader from #439 is responsible only for loading external module paths — not for re-loading already-imported built-in modules.
- **No changes to `routers/futures.py`**, `routers/scanner.py`, task files, or any other call site. The factory's public API contract is the sole migration surface.
