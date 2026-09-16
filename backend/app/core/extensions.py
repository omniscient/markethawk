"""
Extension loader and shared registry primitives for MarketHawk.

Lets host operators wire in third-party extension modules (edge scanners,
risk managers, custom providers) that live outside the core repo. See
docs/superpowers/specs/2026-06-14-extension-loader-shared-registry-design.md
for the trust-boundary rationale: MARKETHAWK_EXTENSION_MODULES is a
host-.env-only setting and must never become settable through any runtime
API.
"""

import logging
from typing import Generic, TypeVar

from app.exceptions import (
    ExtensionDescriptorError,
    ExtensionDuplicateError,
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
