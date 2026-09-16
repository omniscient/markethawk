"""Tests for app.core.extensions and the extension error hierarchy."""

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
