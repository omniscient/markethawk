# Extension Loader and Shared Registry Primitives Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use
> `superpowers:executing-plans` to implement this plan task-by-task. Steps use
> checkbox syntax for tracking.

**Issue:** #439
**Revised:** 2026-09-16 (operator amendment after plan-gate review)

**Goal:** Add the shared extension foundation for MarketHawk — a startup
module loader driven by `MARKETHAWK_EXTENSION_MODULES`, a generic
`ExtensionRegistry[T]` primitive with descriptor validation and duplicate-key
rejection, four structured `MarketHawkError` subclasses, and unit tests. No
behavioral change to existing scanner/provider/trading execution; the
built-in registries (`scan_orchestrator._REGISTRY`,
`discovery_service._SCREENER_REGISTRY`) are untouched.

**Architecture:** Infrastructure primitives live in `app/core/extensions.py`
(alongside `config.py`, `error_tracking.py`, `circuit_breakers.py`), errors in
`app/exceptions.py` following the existing `MarketHawkError` hierarchy. The
loader is called from two process entry points — `create_app()` in
`app/main.py` (API process) and a `worker_init` signal handler in
`app/core/celery_app.py`. `worker_init` fires only in a process that starts a
Celery `WorkController` — `celery-worker` and `forecast-worker` — not in
`celery-beat` (a scheduler, no `WorkController`) or `flower` (a monitor);
this is harmless since scans execute in the worker, not beat or flower, and
covering the process that matters (the worker) is why this call site exists.
Neither call site is
`lifespan()`, which the codebase reserves for graceful-degrade startup
checks. `live-scanner` is a third process entry point and is explicitly out
of scope for this slice (deferred to a follow-up ticket per the spec).

**Tech Stack:** FastAPI, SQLAlchemy 2.0 (sync), pydantic-settings 2.7+,
Celery, pytest.

**No database migration is required** — this slice adds no SQLAlchemy
models.

---

## File Structure

| File | Change |
|------|--------|
| `backend/requirements.txt` | Modify — bump `pydantic-settings` lower bound to `>=2.7,<3.0` (`NoDecode` needs 2.7) |
| `backend/app/core/config.py` | Modify — add `MARKETHAWK_EXTENSION_MODULES` field (`Annotated[list[str], NoDecode]`) + `mode="before"` validator |
| `backend/tests/core/test_config.py` | Modify — add 3 settings-parsing tests |
| `backend/app/exceptions.py` | Modify — add `ExtensionImportError`, `ExtensionDescriptorError`, `ExtensionDuplicateError`, `ExtensionRuntimeError` |
| `backend/app/core/extensions.py` | **Create** — `ExtensionRegistry[T]` (incl. `clear()`), `load_extension_modules()` |
| `backend/tests/core/test_extensions.py` | **Create** — unit tests for the registry and loader |
| `backend/app/main.py` | Modify — call `load_extension_modules()` in `create_app()` after built-in scanner imports |
| `backend/app/core/celery_app.py` | Modify — add `worker_init` signal handler calling `load_extension_modules()`, fail-fast via `SystemExit` |
| `backend/tests/core/test_celery_app.py` | Modify — add `worker_init` handler tests |
| `docker-compose.yml` | Modify — pass `MARKETHAWK_EXTENSION_MODULES` into the `backend` and `celery-worker` services' `environment:` blocks |
| `.env.example` | Modify — one commented line documenting `MARKETHAWK_EXTENSION_MODULES` |
| `ENV_VARIABLES.md` | Modify — add `MARKETHAWK_EXTENSION_MODULES` row to the Optional Variables table |

## Global Constraints

- No behavioral change to `scan_orchestrator._REGISTRY`,
  `discovery_service._SCREENER_REGISTRY`, or any existing scanner/provider
  code path.
- `MARKETHAWK_EXTENSION_MODULES` is host-`.env`-only — never settable via any
  HTTP endpoint, DB row, or scanner-config JSON surface.
- Each task follows red-green TDD: write the failing test, verify it fails,
  implement, verify it passes, commit.
- Run backend tests via `docker-compose exec backend python -m pytest <path> -v`
  (falls back to `cd backend && python -m pytest <path> -v` on the host with
  `DATABASE_URL` pointed at `localhost`, per `DEVELOPMENT.md`).
- `backend/pyproject.toml` sets `addopts = "--cov=app ... --cov-fail-under=60"`,
  so any single-file or `-k`-filtered run legitimately covers well under 60%
  of `app` and exits non-zero even when every test passes. Every focused run
  in this plan appends `--no-cov` for that reason; only the whole-suite
  `pytest -x` runs (Task 6 Step 5, Final Validation) omit it.

---

### Task 1: Bump `pydantic-settings` lower bound (#439)

**Files:**

- Modify: `backend/requirements.txt`

**Interfaces:**

- No code interface — dependency bound only. `Annotated[list[str], NoDecode]`
  (Task 2) requires pydantic-settings >= 2.7.0.

- [ ] **Step 1: Confirm the currently pinned bound and installed version.**

  Run: `grep pydantic-settings backend/requirements.txt`

  Expected: `pydantic-settings>=2.0,<3.0`

  Run: `docker-compose exec backend python -c "import pydantic_settings; print(pydantic_settings.__version__)"`

  Expected: a version >= 2.7 is already resolved into the image (confirms
  the bump is safe and non-breaking before it's made). If instead a version
  below 2.7 is resolved, install a satisfying version before continuing:
  `docker-compose exec backend pip install -U 'pydantic-settings>=2.7,<3.0'`
  (the bumped bound from Step 2 still needs to be baked into the image via
  `docker-compose build backend` before this ticket ships, so that a fresh
  build doesn't silently resolve back to the old floor).

- [ ] **Step 2: Bump the lower bound.**

  In `backend/requirements.txt`, change:

  ```diff
  -pydantic-settings>=2.0,<3.0
  +pydantic-settings>=2.7,<3.0
  ```

- [ ] **Step 3: Verify the resolved environment still satisfies the bound.**

  Run: `docker-compose exec backend pip show pydantic-settings`

  Expected: `Version: 2.7.0` or higher — no reinstall needed since the image
  already resolves a satisfying version (Step 1).

- [ ] **Step 4: Commit.**

  ```bash
  git add backend/requirements.txt
  git commit -m "build(backend): bump pydantic-settings lower bound to 2.7 for NoDecode"
  ```

---

### Task 2: `MARKETHAWK_EXTENSION_MODULES` setting (#439)

**Files:**

- Modify: `backend/app/core/config.py`
- Modify: `backend/tests/core/test_config.py`

**Interfaces:**

- Produces: `Settings.MARKETHAWK_EXTENSION_MODULES: list[str]`, parsed from a
  comma-separated env var at Settings-load time.

- [ ] **Step 1: Add failing settings-parsing tests.**

  Append to `backend/tests/core/test_config.py`:

  These use `monkeypatch.setenv`/`delenv` plus `_env_file=None` (the house
  F-NET-01 pattern at `test_redis_password_omitted_raises_validation_error`,
  line 74-80 of this file) — not `Settings(MARKETHAWK_EXTENSION_MODULES=...)`
  kwargs — because Requirement 1's whole point is that pydantic-settings'
  `EnvSettingsSource` JSON-decodes the raw *environment* value before any
  validator runs; passing the value as a constructor kwarg bypasses that
  source entirely and would pass whether or not `NoDecode` is present.

  ```python
  def test_extension_modules_parses_comma_separated_string(monkeypatch):
      monkeypatch.setenv("MARKETHAWK_EXTENSION_MODULES", "a, b,,c")
      s = Settings(_env_file=None)
      assert s.MARKETHAWK_EXTENSION_MODULES == ["a", "b", "c"]


  def test_extension_modules_empty_string_yields_empty_list(monkeypatch):
      monkeypatch.setenv("MARKETHAWK_EXTENSION_MODULES", "")
      s = Settings(_env_file=None)
      assert s.MARKETHAWK_EXTENSION_MODULES == []


  def test_extension_modules_unset_yields_empty_list(monkeypatch):
      monkeypatch.delenv("MARKETHAWK_EXTENSION_MODULES", raising=False)
      s = Settings(_env_file=None)
      assert s.MARKETHAWK_EXTENSION_MODULES == []
  ```

- [ ] **Step 2: Run the focused tests and verify they fail.**

  Run: `docker-compose exec backend python -m pytest tests/core/test_config.py -k extension_modules -v --no-cov`

  Expected: `AttributeError: 'Settings' object has no attribute
  'MARKETHAWK_EXTENSION_MODULES'` — the field does not exist on `Settings`
  yet. (Once the field exists but is added *without* the `Annotated[...,
  NoDecode]` wrapper, re-running this same command instead fails with
  `pydantic_settings.exceptions.SettingsError: error parsing value for field
  "MARKETHAWK_EXTENSION_MODULES" from source "EnvSettingsSource"` on the
  comma-separated and empty-string cases — this is the exact failure
  Requirement 1's `NoDecode` annotation exists to prevent.)

- [ ] **Step 3: Add the field and validator.**

  In `backend/app/core/config.py`, add the imports. `Annotated` goes in the
  stdlib block (alongside `functools`/`urllib.parse`, alphabetically between
  them), not next to the third-party `pydantic_settings` import — ruff's
  isort rule (`I`, enabled for `app/**` in `backend/pyproject.toml`) would
  otherwise reorder it on the next `ruff --fix` pre-commit run and the diff
  below would drift from the committed file:

  ```diff
   from functools import lru_cache
  +from typing import Annotated
   from urllib.parse import quote

   from pydantic import Field, field_validator, model_validator
  -from pydantic_settings import BaseSettings, SettingsConfigDict
  +from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict
  ```

  Add the field next to `CORS_ORIGINS` (both are `list[str]` settings with
  different parsing conventions — worth contrasting in the comment):

  ```python
      # CORS — JSON array format in .env: CORS_ORIGINS=["http://localhost:3333","https://example.com"]
      CORS_ORIGINS: list[str] = ["http://localhost:3333"]

      # Extension modules — comma-separated; NOT a JSON array (contrast with CORS_ORIGINS above).
      # NoDecode stops pydantic-settings from JSON-decoding the raw env/.env value before
      # validation; without it a bare comma-separated string (and the empty string) raises
      # SettingsError at startup. Host-operator-only — see app/core/extensions.py docstring
      # for the trust boundary.
      # Example: MARKETHAWK_EXTENSION_MODULES=myedge.scanners,myedge.risk
      MARKETHAWK_EXTENSION_MODULES: Annotated[list[str], NoDecode] = []
  ```

  Add the validator directly after `validate_jwt_secret_key` (before the
  `validate_llm_guardrails` model validator):

  ```python
      @field_validator("MARKETHAWK_EXTENSION_MODULES", mode="before")
      @classmethod
      def split_extension_modules(cls, v):
          if isinstance(v, str):
              return [m.strip() for m in v.split(",") if m.strip()]
          return v
  ```

- [ ] **Step 4: Run the focused tests and verify they pass.**

  Run: `docker-compose exec backend python -m pytest tests/core/test_config.py -k extension_modules -v --no-cov`

  Expected: 3 passed.

- [ ] **Step 5: Run the full config test suite to guard against regressions.**

  Run: `docker-compose exec backend python -m pytest tests/core/test_config.py -v --no-cov`

  Expected: all tests pass (no change to any existing field's behavior).

- [ ] **Step 6: Commit.**

  ```bash
  git add backend/app/core/config.py backend/tests/core/test_config.py
  git commit -m "feat(config): add MARKETHAWK_EXTENSION_MODULES setting"
  ```

---

### Task 3: Structured extension errors (#439)

**Files:**

- Modify: `backend/app/exceptions.py`

**Interfaces:**

- Produces: `ExtensionImportError`, `ExtensionDescriptorError`,
  `ExtensionDuplicateError`, `ExtensionRuntimeError`, all subclasses of
  `MarketHawkError`.
- Consumed by: Task 4 (`app/core/extensions.py`).

- [ ] **Step 1: Add a failing test file exercising the new error classes.**

  Create `backend/tests/core/test_extensions.py` with its first block (later
  tasks append to this same file):

  ```python
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
      exc = ExtensionImportError("boom", module_name="myedge.x", original_error="ImportError: x")
      assert isinstance(exc, MarketHawkError)
      assert exc.is_retryable is False
      assert exc.module_name == "myedge.x"


  def test_extension_descriptor_error_is_retryable_false():
      exc = ExtensionDescriptorError("bad descriptor", descriptor_repr="Foo()", field="key")
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
  ```

- [ ] **Step 2: Run the focused tests and verify they fail.**

  Run: `docker-compose exec backend python -m pytest tests/core/test_extensions.py -v --no-cov`

  Expected: `ImportError: cannot import name 'ExtensionDescriptorError' from 'app.exceptions'`
  (the first name in the import list is the one reported).

- [ ] **Step 3: Add the four error classes.**

  Append to `backend/app/exceptions.py`:

  ```python
  class ExtensionImportError(MarketHawkError):
      """Raised when a configured extension module fails to import."""

      def __init__(self, message: str, *, module_name: str, original_error: str, **ctx):
          super().__init__(
              message,
              is_retryable=False,
              module_name=module_name,
              original_error=original_error,
              **ctx,
          )
          self.module_name = module_name
          self.original_error = original_error


  class ExtensionDescriptorError(MarketHawkError):
      """Raised when an extension descriptor fails registry validation."""

      def __init__(self, message: str, *, descriptor_repr: str, field: str, **ctx):
          super().__init__(
              message,
              is_retryable=False,
              descriptor_repr=descriptor_repr,
              field=field,
              **ctx,
          )
          self.descriptor_repr = descriptor_repr
          self.field = field


  class ExtensionDuplicateError(MarketHawkError):
      """Raised when a registry key is already registered and replace=False."""

      def __init__(self, message: str, *, key: str, **ctx):
          super().__init__(message, is_retryable=False, key=key, **ctx)
          self.key = key


  class ExtensionRuntimeError(MarketHawkError):
      """Raised when a registered extension fails during execution."""

      def __init__(self, message: str, *, key: str, original_error: str, **ctx):
          super().__init__(
              message,
              is_retryable=True,
              key=key,
              original_error=original_error,
              **ctx,
          )
          self.key = key
          self.original_error = original_error
  ```

- [ ] **Step 4: Run the focused tests and verify they pass.**

  Run: `docker-compose exec backend python -m pytest tests/core/test_extensions.py -v --no-cov`

  Expected: 4 passed.

- [ ] **Step 5: Commit.**

  ```bash
  git add backend/app/exceptions.py backend/tests/core/test_extensions.py
  git commit -m "feat(exceptions): add structured extension error hierarchy"
  ```

---

### Task 4: `ExtensionRegistry[T]` primitive (#439)

**Files:**

- Create: `backend/app/core/extensions.py`
- Modify: `backend/tests/core/test_extensions.py`

**Interfaces:**

- Produces: `ExtensionRegistry[T]` with `register(descriptor, *, replace=False)`,
  `get(key) -> T | None`, `get_all() -> list[T]`, `clear() -> None`.
- Consumes: `ExtensionDescriptorError`, `ExtensionDuplicateError` from Task 3.

- [ ] **Step 1: Add failing registry tests.**

  Append to `backend/tests/core/test_extensions.py`:

  ```python
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
  ```

- [ ] **Step 2: Run the focused tests and verify they fail.**

  Run: `docker-compose exec backend python -m pytest tests/core/test_extensions.py -v --no-cov`

  Expected: `ModuleNotFoundError: No module named 'app.core.extensions'`.

- [ ] **Step 3: Create `app/core/extensions.py` with the registry.**

  ```python
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
  ```

- [ ] **Step 4: Run the focused tests and verify they pass.**

  Run: `docker-compose exec backend python -m pytest tests/core/test_extensions.py -v --no-cov`

  Expected: all `test_registry_*` tests pass (the `test_extension_*_error_*`
  tests from Task 3 continue to pass unchanged).

- [ ] **Step 5: Commit.**

  ```bash
  git add backend/app/core/extensions.py backend/tests/core/test_extensions.py
  git commit -m "feat(core): add ExtensionRegistry[T] primitive"
  ```

---

### Task 5: `load_extension_modules()` loader (#439)

**Files:**

- Modify: `backend/app/core/extensions.py`
- Modify: `backend/tests/core/test_extensions.py`

**Interfaces:**

- Produces: `load_extension_modules(module_names: list[str]) -> None`.
- Consumes: `ExtensionImportError` from Task 3.

- [ ] **Step 1: Add failing loader tests.**

  At the top of `backend/tests/core/test_extensions.py`, add the import this
  task needs alongside the existing `import pytest` and `from dataclasses
  import dataclass` lines from Tasks 3–4:

  ```python
  import sys
  ```

  Append to the bottom of `backend/tests/core/test_extensions.py`. Each
  "module body executes" case writes a real temporary package to `tmp_path`
  and puts it on `sys.path`, so the loader's `importlib.import_module()` call
  actually runs the package's `__init__.py` — per spec Requirement 5's "not a
  mocked `importlib`, which would only test the mock":

  ```python
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
  ```

  Building the failure case from a real module body that raises (rather than
  monkeypatching `importlib.import_module` itself) avoids globally replacing
  `import_module` for the test's duration, which would also intercept any
  unrelated lazy import pytest or app code performs while the patch is live.

- [ ] **Step 2: Run the focused tests and verify they fail.**

  Run: `docker-compose exec backend python -m pytest tests/core/test_extensions.py -k load_extension_modules -v --no-cov`

  Expected: `ImportError: cannot import name 'load_extension_modules' from 'app.core.extensions'`.

- [ ] **Step 3: Add the loader function.**

  Append to `backend/app/core/extensions.py`:

  ```python
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
  ```

- [ ] **Step 4: Run the focused tests and verify they pass.**

  Run: `docker-compose exec backend python -m pytest tests/core/test_extensions.py -v --no-cov`

  Expected: all tests in the file pass (registry tests from Task 4 unaffected).

- [ ] **Step 5: Run the full test file twice in a row, to confirm the `fake_package` fixture's `sys.modules.pop()` teardown leaves no cross-test pollution.**

  Run: `docker-compose exec backend python -m pytest tests/core/test_extensions.py -v --no-cov`
  (run it a second time immediately after)

  Expected: both runs pass identically. Note: a second `pytest` invocation is a new
  process with a fresh `sys.modules`, so it cannot observe a stale entry; the
  fixture's `sys.modules.pop()` teardown guards same-session reuse of the package
  name (two tests in one run), not cross-run state. Keep the teardown for that reason.

- [ ] **Step 6: Commit.**

  ```bash
  git add backend/app/core/extensions.py backend/tests/core/test_extensions.py
  git commit -m "feat(core): add load_extension_modules() startup loader"
  ```

---

### Task 6: Wire loader into `create_app()` (#439)

**Files:**

- Modify: `backend/app/main.py`

**Interfaces:**

- Consumes: `load_extension_modules` from `app.core.extensions`,
  `settings.MARKETHAWK_EXTENSION_MODULES`.

- [ ] **Step 1: Add a failing integration test asserting the loader is invoked at app creation.**

  `backend/tests/` has no `test_main.py`; append to
  `backend/tests/core/test_extensions.py`:

  ```python
  def test_create_app_calls_load_extension_modules(monkeypatch):
      calls = []
      monkeypatch.setattr(
          "app.core.extensions.load_extension_modules",
          lambda names: calls.append(names),
      )
      from app.main import create_app

      create_app()
      assert calls  # called at least once, with settings.MARKETHAWK_EXTENSION_MODULES
  ```

- [ ] **Step 2: Run the test and verify it fails.**

  Run: `docker-compose exec backend python -m pytest tests/core/test_extensions.py -k create_app -v --no-cov`

  Expected: `AssertionError: assert []` — `create_app()` does not call the
  loader yet.

- [ ] **Step 3: Wire the loader call into `create_app()`.**

  In `backend/app/main.py`, immediately after the existing built-in scanner
  imports (currently lines 456-458):

  ```diff
       importlib.import_module("app.services.pre_market_scan")
       importlib.import_module("app.services.oversold_bounce_scan")
       importlib.import_module("app.services.liquidity_hunt")
  +
  +    # Load user-configured extension modules (MARKETHAWK_EXTENSION_MODULES env var).
  +    # Must come after built-in imports so built-in registrations are already
  +    # present when extension modules attempt to build on top of them.
  +    from app.core.extensions import load_extension_modules
  +
  +    load_extension_modules(settings.MARKETHAWK_EXTENSION_MODULES)
  ```

- [ ] **Step 4: Run the test and verify it passes.**

  Run: `docker-compose exec backend python -m pytest tests/core/test_extensions.py -k create_app -v --no-cov`

  Expected: 1 passed.

- [ ] **Step 5: Run the full backend test suite to confirm `create_app()` still boots cleanly for every other test that calls it.**

  Run: `docker-compose exec backend python -m pytest -x`

  Expected: no new failures. With `MARKETHAWK_EXTENSION_MODULES` unset (`[]`
  default), `load_extension_modules([])` is a no-op — zero behavior change
  for the existing test suite and default deployment.

- [ ] **Step 6: Live-validate per CLAUDE.md's backend validation rule.**

  ```bash
  docker-compose restart backend
  docker-compose logs backend --tail=20
  ```

  Expected log line at startup: `No extension modules configured` (default
  empty `.env`).

  ```bash
  curl -s http://localhost:8000/api/health | python -m json.tool
  ```

  Expected: `200 OK` — app boots normally with the new call site.

- [ ] **Step 7: Commit.**

  ```bash
  git add backend/app/main.py backend/tests/core/test_extensions.py
  git commit -m "feat(main): load extension modules in create_app()"
  ```

---

### Task 7: Wire loader into Celery `worker_init` (#439)

**Files:**

- Modify: `backend/app/core/celery_app.py`
- Modify: `backend/tests/core/test_celery_app.py`

**Interfaces:**

- Consumes: `load_extension_modules`, `ExtensionImportError`,
  `settings.MARKETHAWK_EXTENSION_MODULES`.
- Produces: a `worker_init`-connected handler that raises `SystemExit(1)` on
  load failure (Celery's signal dispatcher otherwise swallows handler
  exceptions and lets the worker start silently without its extensions).

- [ ] **Step 1: Add failing `worker_init` handler tests.**

  `backend/tests/core/test_celery_app.py` is currently 33 lines: a module
  docstring followed directly by two `def test_...` functions, with no
  imports at module scope. Add `import pytest` as the first line *after* the
  existing module docstring (both new tests below need `pytest.raises`; the
  import must not go above the docstring, which would silently demote it to
  a no-op string expression), then append the tests, following the existing
  `test_worker_process_shutdown_*` pattern already in that file:

  ```python
  import pytest


  def test_worker_init_calls_load_extension_modules(monkeypatch):
      from app.core.celery_app import _load_extension_modules
      from app.core.config import settings

      calls = []
      monkeypatch.setattr(
          "app.core.celery_app.load_extension_modules",
          lambda names: calls.append(names),
      )

      _load_extension_modules()

      assert calls == [settings.MARKETHAWK_EXTENSION_MODULES]


  def test_worker_init_raises_system_exit_on_import_error(monkeypatch):
      from app.core.celery_app import _load_extension_modules
      from app.exceptions import ExtensionImportError

      def _raise(*args, **kwargs):
          raise ExtensionImportError("boom", module_name="myedge.x", original_error="x")

      monkeypatch.setattr("app.core.celery_app.load_extension_modules", _raise)

      with pytest.raises(SystemExit):
          _load_extension_modules()
  ```

- [ ] **Step 2: Run the tests and verify they fail.**

  Run: `docker-compose exec backend python -m pytest tests/core/test_celery_app.py -k worker_init -v --no-cov`

  Expected: `ImportError: cannot import name '_load_extension_modules' from 'app.core.celery_app'`.

- [ ] **Step 3: Add the `worker_init` handler.**

  In `backend/app/core/celery_app.py`, add the imports and handler.
  `backend/app/core/celery_app.py` currently has no `import logging` at
  module scope (verified: only `os`, `celery`, `celery.schedules`,
  `celery.signals`, `app.core.config` are imported) — add it unconditionally.
  The module already imports `from celery.signals import (...)` — add
  `worker_init` to that block. `load_extension_modules` and
  `ExtensionImportError` are imported at module scope (not function-local, as
  the spec's illustrative sketch shows) specifically so Step 1's
  `monkeypatch.setattr("app.core.celery_app.load_extension_modules", ...)`
  has a module-level name to patch — a function-local `from ... import ...`
  re-imports the real, un-patched function on every call and the test would
  silently exercise production behavior instead of the stub:

  ```diff
  +import logging
   import os

   from celery import Celery
   from celery.schedules import crontab
   from celery.signals import (
       after_setup_logger,
       after_setup_task_logger,
  +    worker_init,
       worker_process_shutdown,
       worker_ready,
   )

   from app.core.config import settings
  +from app.core.extensions import load_extension_modules
  +from app.exceptions import ExtensionImportError
  ```

  Add the handler near the other signal handlers (after `_install_log_redaction`):

  ```python
  @worker_init.connect
  def _load_extension_modules(**_kwargs):
      try:
          load_extension_modules(settings.MARKETHAWK_EXTENSION_MODULES)
      except ExtensionImportError as exc:
          logging.getLogger(__name__).critical(
              "Extension load failed; worker will not start: %s", exc
          )
          raise SystemExit(1) from exc
  ```

- [ ] **Step 4: Run the tests and verify they pass.**

  Run: `docker-compose exec backend python -m pytest tests/core/test_celery_app.py -v --no-cov`

  Expected: all pass, including the pre-existing
  `test_worker_process_shutdown_*` tests (unaffected).

- [ ] **Step 5: Live-validate the worker still starts cleanly.**

  ```bash
  docker-compose restart celery-worker
  docker-compose logs celery-worker --tail=20
  ```

  Expected: no `CRITICAL` extension-load log line, worker reaches "ready"
  state (default `.env` has no `MARKETHAWK_EXTENSION_MODULES` set).

- [ ] **Step 6: Commit.**

  ```bash
  git add backend/app/core/celery_app.py backend/tests/core/test_celery_app.py
  git commit -m "feat(celery): load extension modules in worker_init, fail-fast on error"
  ```

---

### Task 8: Wire `MARKETHAWK_EXTENSION_MODULES` into `docker-compose.yml` (#439)

**Files:**

- Modify: `docker-compose.yml`

**Interfaces:** None — deployment wiring only.

- [ ] **Step 1: Confirm the setting is not currently passed into any container.**

  Run: `grep -n "MARKETHAWK_EXTENSION_MODULES\|env_file" docker-compose.yml`

  Expected: no `MARKETHAWK_EXTENSION_MODULES` match. `env_file:` appears
  exactly once, on the `forecast-worker` service — `backend` and
  `celery-worker` (the two processes Task 6/7 wire the loader into) declare
  explicit `environment:` blocks with `${VAR}` interpolation and no
  `env_file:` directive, so a host `.env` entry is otherwise invisible to
  them. This mirrors how `CORS_ORIGINS` is already handled: also absent from
  both blocks, also falling back to its `Settings` default when unset.
  Without this task, the spec's Trust Boundary section ("the sole input path
  is the host `.env` file consumed by `docker-compose.yml`") is false for
  this variable — it would ship inert in the default deployment.

- [ ] **Step 2: Add the variable to the `backend` service's `environment:` block.**

  In `docker-compose.yml`, add a line to the `backend` service's
  `environment:` block, next to the other optional passthroughs such as
  `INTERNAL_API_TOKEN`:

  ```diff
         # System notifications (#570) — shared secret for POST /api/v1/alerts/system + ops recipient
         INTERNAL_API_TOKEN: ${INTERNAL_API_TOKEN:-}
         OPS_ALERT_EMAIL: ${OPS_ALERT_EMAIL:-}
  +      # Host-operator-only extension modules — see ENV_VARIABLES.md
  +      MARKETHAWK_EXTENSION_MODULES: ${MARKETHAWK_EXTENSION_MODULES:-}
  ```

- [ ] **Step 3: Add the variable to the `celery-worker` service's `environment:` block.**

  Scans execute in the Celery worker, not the API process (spec Requirement
  2), so the same variable must reach `celery-worker` too:

  ```diff
         # JWT auth secret — required by Settings validator (>=32 chars), sourced from .env
         JWT_SECRET_KEY: ${JWT_SECRET_KEY}
  +      # Host-operator-only extension modules — see ENV_VARIABLES.md
  +      MARKETHAWK_EXTENSION_MODULES: ${MARKETHAWK_EXTENSION_MODULES:-}
  ```

- [ ] **Step 4: Validate the compose file still parses.**

  Run: `docker-compose config --quiet`

  Expected: no output, exit code 0 — confirms the YAML is well-formed and
  the new interpolations resolve.

- [ ] **Step 5: Live-validate the variable reaches both containers.**

  ```bash
  MARKETHAWK_EXTENSION_MODULES=nonexistent.module docker-compose up -d backend celery-worker
  docker-compose logs backend celery-worker --tail=20
  ```

  Expected: both services log a `CRITICAL`/startup failure referencing
  `Failed to import extension module 'nonexistent.module'` (proving the value
  reached `Settings` in both containers), not the previous
  `No extension modules configured` no-op. Then restore the clean state:

  ```bash
  docker-compose up -d backend celery-worker
  docker-compose logs backend celery-worker --tail=10
  ```

  Expected: `No extension modules configured` (host `.env` has no
  `MARKETHAWK_EXTENSION_MODULES` entry by default), both services healthy.

- [ ] **Step 6: Commit.**

  ```bash
  git add docker-compose.yml
  git commit -m "chore(compose): pass MARKETHAWK_EXTENSION_MODULES to backend and celery-worker"
  ```

---

### Task 9: Document `.env.example` and `ENV_VARIABLES.md` (#439)

**Files:**

- Modify: `.env.example`
- Modify: `ENV_VARIABLES.md`

**Interfaces:** None — documentation only.

- [ ] **Step 1: Add the commented line to `.env.example`.**

  Add directly below the existing `# OPTIONAL: CORS Origins` block (the
  `CORS_ORIGINS=...` line, currently around line 65):

  ```diff
   # CORS_ORIGINS=["http://localhost:3333","https://your-domain.com"]
  +
  +# =============================================================================
  +# OPTIONAL: Extension Modules
  +# =============================================================================
  +# Comma-separated list of extension modules to import at startup (host-operator-only).
  +# Default: none
  +# MARKETHAWK_EXTENSION_MODULES=myedge.scanners,myedge.risk
  ```

- [ ] **Step 2: Add the row to `ENV_VARIABLES.md`'s Optional Variables table.**

  CLAUDE.md designates `ENV_VARIABLES.md` "the complete reference" for env
  vars; add a row next to the existing `CORS_ORIGINS` row (both are
  `list[str]` settings, worth contrasting the parsing format directly in the
  Purpose column):

  ```diff
   | `CORS_ORIGINS` | `["http://localhost:3333"]` | JSON array of allowed frontend origins (e.g. `["http://localhost:3333","https://your-domain.com"]`). Wildcard `*` is intentionally rejected; list explicit origins instead. |
  +| `MARKETHAWK_EXTENSION_MODULES` | `[]` (none) | Comma-separated list of extension modules to import at startup (e.g. `myedge.scanners,myedge.risk`) — NOT a JSON array, unlike `CORS_ORIGINS` above. Host-operator-only: set only in the host `.env` file, never via any runtime API. Imported with the full privileges of the backend and worker processes. |
  ```

- [ ] **Step 3: Verify both files updated correctly.**

  Run: `grep -n "MARKETHAWK_EXTENSION_MODULES" .env.example ENV_VARIABLES.md`

  Expected: one match per file.

- [ ] **Step 4: Commit.**

  ```bash
  git add .env.example ENV_VARIABLES.md
  git commit -m "docs(env): document MARKETHAWK_EXTENSION_MODULES"
  ```

---

## Final Validation

- [ ] Lint first, the way CI's `test` job does (ruff runs before pytest and fails the job on its own):

  ```bash
  docker-compose exec backend ruff check .
  ```

  Expected: no findings. (`pip-audit` follows in CI with the #848 ignores; this slice adds no new package, only a lower-bound bump.)

- [ ] Run the full backend suite once more end-to-end:

  ```bash
  docker-compose exec backend python -m pytest -x
  ```

  Expected: all tests pass, including the new
  `backend/tests/core/test_extensions.py` (12+ tests per spec Requirement 5)
  and the additions to `test_config.py` and `test_celery_app.py`.

- [ ] Confirm no behavioral change to existing scan execution: run the
  scanner-specific test subset.

  ```bash
  docker-compose exec backend python -m pytest tests/services -k scan -v --no-cov
  ```

  Expected: unchanged pass/fail state versus `main` (this slice does not
  touch `scan_orchestrator.py` or `discovery_service.py`).
