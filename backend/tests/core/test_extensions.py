"""Tests for app.core.extensions and the extension error hierarchy."""

import pytest

from app.exceptions import (
    ExtensionDescriptorError,
    ExtensionDuplicateError,
    ExtensionImportError,
    ExtensionRuntimeError,
    MarketHawkError,
)


def test_extension_import_error_is_retryable_false():
    exc = ExtensionImportError(
        "boom", module_name="myedge.x", original_error="ImportError: x"
    )
    assert isinstance(exc, MarketHawkError)
    assert exc.is_retryable is False
    assert exc.module_name == "myedge.x"


def test_extension_descriptor_error_is_retryable_false():
    exc = ExtensionDescriptorError(
        "bad descriptor", descriptor_repr="Foo()", field="key"
    )
    assert exc.is_retryable is False
    assert exc.field == "key"


def test_extension_duplicate_error_is_retryable_false():
    exc = ExtensionDuplicateError("dup", key="my-key")
    assert exc.is_retryable is False
    assert exc.key == "my-key"


def test_extension_runtime_error_is_retryable_true():
    exc = ExtensionRuntimeError("boom", key="my-key", original_error="ValueError: x")
    assert exc.is_retryable is True
    assert exc.key == "my-key"


from dataclasses import dataclass

from app.core.extensions import ExtensionRegistry


@dataclass(frozen=True)
class _FakeDescriptor:
    key: str
    value: int = 0


def test_registry_register_and_get():
    registry: ExtensionRegistry[_FakeDescriptor] = ExtensionRegistry()
    d = _FakeDescriptor(key="a", value=1)
    registry.register(d)
    assert registry.get("a") == d
    assert registry.get("missing") is None


def test_registry_get_all_preserves_insertion_order():
    registry: ExtensionRegistry[_FakeDescriptor] = ExtensionRegistry()
    registry.register(_FakeDescriptor(key="a"))
    registry.register(_FakeDescriptor(key="b"))
    assert [d.key for d in registry.get_all()] == ["a", "b"]


def test_registry_duplicate_key_raises():
    registry: ExtensionRegistry[_FakeDescriptor] = ExtensionRegistry()
    registry.register(_FakeDescriptor(key="a"))
    with pytest.raises(ExtensionDuplicateError):
        registry.register(_FakeDescriptor(key="a"))


def test_registry_replace_true_overwrites_silently():
    registry: ExtensionRegistry[_FakeDescriptor] = ExtensionRegistry()
    registry.register(_FakeDescriptor(key="a", value=1))
    registry.register(_FakeDescriptor(key="a", value=2), replace=True)
    assert registry.get("a").value == 2


def test_registry_missing_key_raises_descriptor_error():
    registry: ExtensionRegistry = ExtensionRegistry()

    @dataclass(frozen=True)
    class _NoKey:
        value: int = 0

    with pytest.raises(ExtensionDescriptorError):
        registry.register(_NoKey())


def test_registry_non_string_key_raises_descriptor_error():
    registry: ExtensionRegistry = ExtensionRegistry()

    @dataclass(frozen=True)
    class _IntKey:
        key: int = 1

    with pytest.raises(ExtensionDescriptorError):
        registry.register(_IntKey())


def test_registry_clear_empties_registry():
    registry: ExtensionRegistry[_FakeDescriptor] = ExtensionRegistry()
    registry.register(_FakeDescriptor(key="a"))
    registry.clear()
    assert registry.get_all() == []
    assert registry.get("a") is None
