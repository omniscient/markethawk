"""
Extension loader and shared registry primitives for MarketHawk.

Lets host operators wire in third-party extension modules (edge scanners,
risk managers, custom providers) that live outside the core repo. See
docs/superpowers/specs/2026-06-14-extension-loader-shared-registry-design.md
for the trust-boundary rationale: MARKETHAWK_EXTENSION_MODULES is a
host-.env-only setting and must never become settable through any runtime
API.
"""

import importlib
import logging
from typing import Generic, TypeVar

from app.exceptions import (
    ExtensionDescriptorError,
    ExtensionDuplicateError,
    ExtensionImportError,
)

logger = logging.getLogger(__name__)

T = TypeVar("T")


class ExtensionRegistry(Generic[T]):
    """Generic keyed registry for extension-point descriptors."""

    def __init__(self) -> None:
        self._entries: dict[str, T] = {}

    def register(self, descriptor: T, *, replace: bool = False) -> T:
        key = getattr(descriptor, "key", None)
        if not isinstance(key, str) or not key.strip():
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

    Idempotent by contract: sys.modules makes repeat calls no-ops, so this
    may be invoked from every process entry point (create_app, Celery
    worker_init).
    """
    if not module_names:
        logger.info("No extension modules configured")
        return
    logger.info("Loading extension modules: %s", module_names)
    for name in module_names:
        try:
            importlib.import_module(name)
        except Exception as exc:  # ModuleNotFoundError, SyntaxError, or anything the module body raises
            raise ExtensionImportError(
                f"Failed to import extension module {name!r}",
                module_name=name,
                original_error=str(exc),
            ) from exc
