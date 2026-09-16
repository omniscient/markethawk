"""Tests for app.core.extensions and the extension error hierarchy."""

import sys

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


from app.core.extensions import load_extension_modules


@pytest.fixture
def fake_package(tmp_path, monkeypatch):
    """Write a temp package to sys.path; import it via the fixture's return
    value so the loader's importlib.import_module() actually executes the
    package body. Tears down sys.modules explicitly — monkeypatch.delitem
    cannot do this, since it only restores keys that already existed
    *before* the test, and these packages don't exist until we write them.
    """
    created_names = []

    def _write(name: str, body: str) -> None:
        package_dir = tmp_path / name
        package_dir.mkdir()
        (package_dir / "__init__.py").write_text(body)
        monkeypatch.syspath_prepend(str(tmp_path))
        created_names.append(name)

    yield _write

    for name in created_names:
        sys.modules.pop(name, None)


def test_load_extension_modules_empty_list_is_noop(caplog):
    with caplog.at_level("INFO"):
        load_extension_modules([])
    assert "No extension modules configured" in caplog.text


def test_load_extension_modules_imports_successfully(tmp_path, fake_package):
    counter_file = tmp_path / "counter.txt"
    counter_file.write_text("0")
    fake_package(
        "fake_ext_pkg",
        "from pathlib import Path\n"
        f"p = Path(r'{counter_file}')\n"
        "p.write_text(str(int(p.read_text()) + 1))\n",
    )

    load_extension_modules(["fake_ext_pkg"])

    assert counter_file.read_text() == "1"


def test_load_extension_modules_exactly_once(tmp_path, fake_package):
    counter_file = tmp_path / "counter_once.txt"
    counter_file.write_text("0")
    fake_package(
        "fake_ext_pkg_once",
        "from pathlib import Path\n"
        f"p = Path(r'{counter_file}')\n"
        "p.write_text(str(int(p.read_text()) + 1))\n",
    )

    load_extension_modules(["fake_ext_pkg_once"])
    load_extension_modules(["fake_ext_pkg_once"])

    # sys.modules caching (not the loader) makes the module body run once;
    # the loader itself is safe to call from multiple process entry points.
    assert counter_file.read_text() == "1"


def test_load_extension_modules_missing_module_raises_extension_import_error():
    with pytest.raises(ExtensionImportError) as exc_info:
        load_extension_modules(["this_module_does_not_exist_anywhere"])
    assert exc_info.value.module_name == "this_module_does_not_exist_anywhere"
    assert isinstance(exc_info.value.__cause__, ModuleNotFoundError)


def test_load_extension_modules_non_import_error_wrapped(fake_package):
    fake_package("fake_ext_pkg_raises", "raise ValueError('bad module body')\n")

    with pytest.raises(ExtensionImportError) as exc_info:
        load_extension_modules(["fake_ext_pkg_raises"])
    assert isinstance(exc_info.value.__cause__, ValueError)
