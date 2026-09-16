# Scanner Extension Registration

**Issue:** #440
**Revised:** 2026-09-16 (operator amendment after plan-gate review)

## Goal

Formalize `scan_orchestrator.ScannerDescriptor`/`_REGISTRY` as a first-class extension point: add
`asset_classes` and `default_parameters` metadata fields, migrate the plain-dict registry onto
#439's `ExtensionRegistry[T]` (duplicate-key guard, `replace=True` semantics), update all five
built-in scanner modules (seven registered keys) to supply the new fields, and expose the fields
through `/api/v1/scanner/types`. A private extension module registered through #439's
`load_extension_modules()` loader must resolve and run identically to a built-in.

This plan assumes #439 has landed and exposes `ExtensionRegistry` (`app/core/extensions.py`),
`load_extension_modules` (`app/core/extensions.py`), and `ExtensionDuplicateError` /
`ExtensionDescriptorError` (`app/exceptions.py`). #439 merged to `origin/main` (merge commit
`1808e18`) but is not yet on this branch — see **Prerequisite** below.

## Prerequisite: bring #439 onto this branch

**Files:** none (integration step only)

```bash
git fetch origin
git merge-base --is-ancestor 1808e18 HEAD && echo "already present" || git merge origin/main
```
Expected: the merge completes cleanly (no conflicts are expected — this branch has only touched
`docs/superpowers/specs/` and `docs/superpowers/plans/` so far) and afterwards:
```bash
test -f backend/app/core/extensions.py && echo "present" || echo "MISSING"
```
prints `present`. If this prints `MISSING`, `origin/main` was stale at fetch time — re-run
`git fetch origin` and the merge before proceeding. If a real merge conflict occurs, resolve it
and re-run the check before
starting Task 1 — Task 1 imports `app.core.extensions.ExtensionRegistry`, which does not exist on
this branch until this step runs.

## Architecture

`scan_orchestrator.py` is the single source of truth for scanner discovery: modules self-register
a `ScannerDescriptor` at import time, and `run()` dispatches by key. This ticket keeps that shape
and swaps the storage/guard layer underneath it (`_REGISTRY: dict` → `_REGISTRY: ExtensionRegistry`),
then widens the descriptor so extension authors (built-in or private) can declare which asset
classes a scanner targets and its canonical default thresholds — both currently tribal knowledge
living in ad hoc module-level `DEFAULT_CONFIG` dicts.

## Tech Stack

Backend only: FastAPI router (`routers/scanner.py`), plain dataclasses, pytest.

## File Structure

| File | Change |
|---|---|
| `backend/app/services/scan_orchestrator.py` | `ScannerDescriptor` gains 2 fields; `_REGISTRY` becomes `ExtensionRegistry[ScannerDescriptor]`; `register`/`get_all`/`run` become thin wrappers |
| `backend/tests/services/test_scan_orchestrator.py` | Fixture + dict-style assertions updated to the registry API; new tests for defaults, duplicate/replace, built-in compatibility, private-module-via-loader |
| `backend/app/services/pocket_pivot.py` | `DEFAULT_CONFIG` → `_DEFAULT_PARAMS`; `register()` call gains `asset_classes`, `default_parameters` |
| `backend/app/services/trend_pullback_scan.py` | Same rename + `register()` update |
| `backend/app/services/liquidity_hunt.py` | `DEFAULT_CONFIG` name kept as-is (shared by 3 keys); the registration loop's 3 `register()` calls gain `asset_classes`, `default_parameters=DEFAULT_CONFIG` |
| `backend/app/services/oversold_bounce_scan.py` | `register()` call gains explicit `asset_classes=("stocks",)`, `default_parameters={}` |
| `backend/app/services/pre_market_scan.py` | Same explicit-empty-defaults update |
| `backend/tests/services/test_trend_pullback_scan.py` | `_REGISTRY` membership check updated to `.get(...)` |
| `backend/app/routers/scanner.py` | `/types` response includes `asset_classes`, `default_parameters` |
| `backend/tests/api/test_scanner.py` | `test_list_scanner_types` key-set assertion updated to 6 keys + type checks |

No new files, no migration (no SQLAlchemy model touched).

---

## Task 1: Migrate `_REGISTRY` onto `ExtensionRegistry[ScannerDescriptor]` and add descriptor fields

**Files:**
- `backend/app/services/scan_orchestrator.py`
- `backend/tests/services/test_scan_orchestrator.py`
- `backend/tests/services/test_trend_pullback_scan.py`

### Step 1 — write failing tests

Add to `backend/tests/services/test_scan_orchestrator.py`, after `test_register_returns_descriptor`
(around line 63):

```python
from app.exceptions import ExtensionDuplicateError


def test_descriptor_new_fields_default():
    fn = AsyncMock(return_value=[])
    desc = ScannerDescriptor(key="defaults_test", display_name="D", description="d", run=fn)
    assert desc.asset_classes == ("stocks",)
    assert desc.default_parameters == {}


def test_duplicate_key_raises_without_replace():
    fn = AsyncMock(return_value=[])
    register(ScannerDescriptor(key="dup_test", display_name="A", description="d", run=fn))
    with pytest.raises(ExtensionDuplicateError):
        register(ScannerDescriptor(key="dup_test", display_name="B", description="d", run=fn))


def test_duplicate_key_with_replace_succeeds():
    fn = AsyncMock(return_value=[])
    register(ScannerDescriptor(key="replace_test", display_name="A", description="d", run=fn))
    replacement = ScannerDescriptor(
        key="replace_test", display_name="B", description="d", run=fn
    )
    register(replacement, replace=True)
    assert orchestrator._REGISTRY.get("replace_test") is replacement
```

Also replace `test_run_raises_for_unknown_type` (lines 47-49) so Requirement 8 (the unknown-scanner
error lists every registered key) is actually asserted, not just the fixed prefix of the message:

```python
def test_run_raises_for_unknown_type():
    fn = AsyncMock(return_value=[])
    register(ScannerDescriptor(key="known_key", display_name="K", description="d", run=fn))
    with pytest.raises(ValueError, match="Unknown scanner type: 'does_not_exist'") as exc_info:
        asyncio.run(run("does_not_exist", [], db=None, event_date=date.today()))
    assert "known_key" in str(exc_info.value)
```

Also update the existing dict-style assertions in the same file (they will otherwise fail for the
wrong reason — `_REGISTRY` won't support `in`/`[]` once it's an `ExtensionRegistry`):

Replace the `isolated_registry` fixture (lines 11-16):

```python
@pytest.fixture(autouse=True)
def isolated_registry():
    original = orchestrator._REGISTRY.get_all()
    yield
    orchestrator._REGISTRY.clear()
    for desc in original:
        orchestrator._REGISTRY.register(desc, replace=True)
```

Replace `test_register_adds_descriptor` (lines 19-24):

```python
def test_register_adds_descriptor():
    fn = AsyncMock(return_value=[])
    desc = ScannerDescriptor(key="test", display_name="Test", description="d", run=fn)
    register(desc)
    assert orchestrator._REGISTRY.get("test") is not None
    assert orchestrator._REGISTRY.get("test") is desc
```

Replace `test_pre_market_scanner_registered` (lines 66-72):

```python
def test_pre_market_scanner_registered():
    import app.services.pre_market_scan  # noqa: F401

    desc = orchestrator._REGISTRY.get("pre_market_volume_spike")
    assert desc is not None
    assert desc.display_name == "Pre-Market Volume Spike"
    assert desc.supports_date_range is True
```

Replace `test_oversold_bounce_scanner_registered` (lines 75-81):

```python
def test_oversold_bounce_scanner_registered():
    import app.services.oversold_bounce_scan  # noqa: F401

    desc = orchestrator._REGISTRY.get("oversold_bounce")
    assert desc is not None
    assert desc.display_name == "Oversold Bounce"
    assert desc.supports_date_range is True
```

Replace `test_liquidity_hunt_variants_registered` (lines 84-88):

```python
def test_liquidity_hunt_variants_registered():
    import app.services.liquidity_hunt  # noqa: F401

    for key in ("liquidity_hunt", "liquidity_hunt_pre", "liquidity_hunt_post"):
        assert orchestrator._REGISTRY.get(key) is not None, f"Expected {key!r} in registry"
```

`ExtensionRegistry` (from #439) defines no `__contains__`, so any other file's
`"key" in _REGISTRY`-style check breaks the moment `_REGISTRY` stops being a `dict` — not just
within this file. Fix the one other repo-wide occurrence in the same step so this task lands as a
self-contained green change: replace `test_orchestrator_registration` in
`backend/tests/services/test_trend_pullback_scan.py` (lines 147-151):

```python
def test_orchestrator_registration():
    import app.services.trend_pullback_scan  # noqa: F401 — triggers registration
    from app.services.scan_orchestrator import _REGISTRY

    assert _REGISTRY.get("trend_pullback") is not None
```

### Step 2 — verify fail

```bash
docker-compose exec backend python -m pytest tests/services/test_scan_orchestrator.py tests/services/test_trend_pullback_scan.py -x -q
```
Expected: every test in `test_scan_orchestrator.py` errors at fixture setup —
`AttributeError: 'dict' object has no attribute 'get_all'` — because the updated
`isolated_registry` fixture (Step 1) calls `orchestrator._REGISTRY.get_all()`/`.clear()`/
`.register(desc, replace=True)`, none of which the current plain-`dict` `_REGISTRY` supports as
written (`.clear()` exists on `dict` too, but `.get_all()` does not, and the module-level
`register()` function does not yet accept a `replace` kwarg). `test_orchestrator_registration` in
`test_trend_pullback_scan.py` still passes at this point (`_REGISTRY` is still a plain `dict`,
so `.get(...)` already works on it) — its failure only appears after Step 3 changes `_REGISTRY`'s
type, which is why Step 1 already carries its fix. This confirms the fixture is correctly
targeting the not-yet-implemented `ExtensionRegistry` API before Step 3 lands it.

### Step 3 — implement

Replace everything from the top of `backend/app/services/scan_orchestrator.py` (the `import json`
line) down through the end of the `register()` function definition (i.e. the file's imports, the
`ScannerFn` alias, the `_REGISTRY` module variable, the `ScannerDescriptor` dataclass, and
`register()`) with:

```python
import json
import uuid as _uuid
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from typing import Any, Awaitable, Callable, Optional, Tuple

import redis as _redis

from app.core.extensions import ExtensionRegistry

ScannerFn = Callable[[list[str], Any, date], Awaitable[list[dict]]]
# Every implementation accepts scanner_run= and gate_metadata= keyword arguments;
# the alias above does not encode them (left unchanged in this ticket).

_REGISTRY: ExtensionRegistry["ScannerDescriptor"] = ExtensionRegistry()


@dataclass(frozen=True)
class ScannerDescriptor:
    key: str
    display_name: str
    description: str
    run: ScannerFn
    supports_date_range: bool = True
    asset_classes: tuple[str, ...] = ("stocks",)
    default_parameters: dict[str, Any] = field(default_factory=dict, hash=False)


def register(descriptor: "ScannerDescriptor", *, replace: bool = False) -> "ScannerDescriptor":
    return _REGISTRY.register(descriptor, replace=replace)
```

Replace the existing `get_all()` function (immediately below `register()`) with:

```python
def get_all() -> list["ScannerDescriptor"]:
    return _REGISTRY.get_all()
```

Replace the body of the existing `run()` function (below `get_all()`), keeping its signature
unchanged:

```python
async def run(
    scanner_type: str,
    tickers: list[str],
    db: Any,
    event_date: date,
    scanner_run: Optional[Any] = None,
    gate_metadata: Optional[Any] = None,
) -> list[dict]:
    descriptor = _REGISTRY.get(scanner_type)
    if descriptor is None:
        raise ValueError(
            f"Unknown scanner type: {scanner_type!r}. "
            f"Registered: {[d.key for d in _REGISTRY.get_all()]}"
        )
    return await descriptor.run(
        tickers, db, event_date, scanner_run=scanner_run, gate_metadata=gate_metadata
    )
```

`compute_next_run`, `get_scan_progress`, `request_scan_cancel`, and `enqueue_scan` are unchanged.

### Step 4 — verify pass

```bash
docker-compose exec backend ruff check .
```
Expected: `All checks passed!` — CI's `test` job runs ruff before pytest, so each task commit
must be lint-clean, not only test-green.

```bash
docker-compose exec backend python -m pytest tests/services/test_scan_orchestrator.py tests/services/test_trend_pullback_scan.py -x -q
```
Expected: `18 passed` in `test_scan_orchestrator.py` — the file's 15 pre-existing test functions
(4 of which were rewritten in Step 1 to use `.get(...)`, 1 of which —
`test_run_raises_for_unknown_type` — was extended for Requirement 8) plus the 3 new tests added
in Step 1 — plus all of `test_trend_pullback_scan.py` passing (including the updated
`test_orchestrator_registration`), no failures.

### Step 5 — commit

```bash
git add backend/app/services/scan_orchestrator.py backend/tests/services/test_scan_orchestrator.py \
  backend/tests/services/test_trend_pullback_scan.py
git commit -m "feat(scanner): migrate _REGISTRY onto ExtensionRegistry, add descriptor metadata fields (#440)"
```

---

## Task 2: Update the five built-in scanner modules (seven keys) with the new fields

**Files:**
- `backend/app/services/pocket_pivot.py`
- `backend/app/services/trend_pullback_scan.py`
- `backend/app/services/liquidity_hunt.py`
- `backend/app/services/oversold_bounce_scan.py`
- `backend/app/services/pre_market_scan.py`
- `backend/tests/services/test_scan_orchestrator.py`

### Step 1 — write failing test

`isolated_registry` (Task 1) snapshots the registry at the *start* of each test and restores that
exact snapshot afterward. If a scanner module is imported for the first time from inside a test
body, its `register()` call fires during that test — but the snapshot taken at that same test's
setup predates it, so teardown evicts it, and any later test that does nothing but assert the key
is already registered gets a no-op import (Python caches modules) and fails. To avoid this
ordering hazard, import all five built-in scanner modules at **module scope** at the top of
`backend/tests/services/test_scan_orchestrator.py` — so registration happens once, at collection
time, before the first test's fixture snapshot ever runs. Replace the file's existing import block
(`import app.services.scan_orchestrator as orchestrator` /
`from app.services.scan_orchestrator import ScannerDescriptor, get_all, register, run`) with this
ruff-`isort`-clean ordering (`import app.services.*` lines sort alphabetically ahead of the `from`
line under the repo's `ruff` config):

```python
import app.services.liquidity_hunt  # noqa: F401 — self-registers at import time
import app.services.oversold_bounce_scan  # noqa: F401
import app.services.pocket_pivot  # noqa: F401
import app.services.pre_market_scan  # noqa: F401
import app.services.scan_orchestrator as orchestrator
import app.services.trend_pullback_scan  # noqa: F401
from app.services.scan_orchestrator import ScannerDescriptor, get_all, register, run
```

Then add this test anywhere in the file (after the liquidity-hunt-variants test):

```python
def test_built_in_scanners_register_seven_keys_with_metadata():
    from app.services.liquidity_hunt import DEFAULT_CONFIG as LIQUIDITY_HUNT_PARAMS
    from app.services.pocket_pivot import _DEFAULT_PARAMS as POCKET_PIVOT_PARAMS
    from app.services.trend_pullback_scan import (
        _DEFAULT_PARAMS as TREND_PULLBACK_PARAMS,
    )

    expected_keys = {
        "pre_market_volume_spike",
        "oversold_bounce",
        "liquidity_hunt",
        "liquidity_hunt_pre",
        "liquidity_hunt_post",
        "pocket_pivot",
        "trend_pullback",
    }
    all_descriptors = {d.key: d for d in get_all()}
    assert expected_keys <= set(all_descriptors)

    for key in expected_keys:
        assert all_descriptors[key].asset_classes == ("stocks",), key

    assert all_descriptors["pocket_pivot"].default_parameters == POCKET_PIVOT_PARAMS
    assert all_descriptors["pocket_pivot"].default_parameters["lookback_days"] == 10
    assert all_descriptors["trend_pullback"].default_parameters == TREND_PULLBACK_PARAMS
    assert all_descriptors["trend_pullback"].default_parameters["trend_sma_fast"] == 50
    for key in ("liquidity_hunt", "liquidity_hunt_pre", "liquidity_hunt_post"):
        assert all_descriptors[key].default_parameters == LIQUIDITY_HUNT_PARAMS
    assert all_descriptors["liquidity_hunt"].default_parameters["volume_ratio_min"] == 4.0
    assert all_descriptors["oversold_bounce"].default_parameters == {}
    assert all_descriptors["pre_market_volume_spike"].default_parameters == {}
```

The equality checks against `*_PARAMS` confirm the descriptor references the module's real config
object (not a copy that could drift); the added index assertions pin a concrete known value so the
test would still fail if `default_parameters` were wired to an empty dict that merely happened to
`==` the import (impossible here, but keeps the test meaningful in isolation).

Note `liquidity_hunt.py` keeps the module-level name `DEFAULT_CONFIG` (it is shared across
three registrations rather than renamed — see Step 3); `pocket_pivot.py` and
`trend_pullback_scan.py` rename to `_DEFAULT_PARAMS`.

### Step 2 — verify fail

```bash
docker-compose exec backend python -m pytest tests/services/test_scan_orchestrator.py -x -q
```
Expected: `ImportError` on `_DEFAULT_PARAMS` (doesn't exist yet in `pocket_pivot.py` /
`trend_pullback_scan.py`) and `AssertionError` on `asset_classes`/`default_parameters` for keys
that still use the dataclass defaults implicitly but haven't been updated to reference the
module's real config dict.

### Step 3 — implement

**`backend/app/services/pocket_pivot.py`** — rename the module-level dict (line 42) and its one
usage (line 196):

```python
_DEFAULT_PARAMS: dict[str, Any] = {
    "lookback_days": 10,
    "min_lookback_days": 5,
    "price_floor": 5.00,
    "volume_floor": 100_000,
}
```
```python
        cfg: dict[str, Any] = {**_DEFAULT_PARAMS, **(config or {})}
```

Update the `register(...)` call at the end of the file:

```python
register(
    ScannerDescriptor(
        key="pocket_pivot",
        display_name="Pocket Pivot",
        description=(
            "Detects up-days where session volume exceeds the highest "
            "down-day volume in the prior 10 trading days "
            "(classic Morales/Kacher pocket pivot)."
        ),
        run=_orchestrator_run,
        supports_date_range=True,
        asset_classes=("stocks",),
        default_parameters=_DEFAULT_PARAMS,
    )
)
```

**`backend/app/services/trend_pullback_scan.py`** — rename the module-level dict (line 40) and
its one usage (line 293):

```python
_DEFAULT_PARAMS: dict[str, Any] = {
    "trend_sma_fast": 50,
    "trend_sma_slow": 200,
    "sma_rising_lookback": 20,
    "max_pct_off_high": 15,
    "pullback_sma": 20,
    "pullback_sma_tolerance_pct": 1,
    "min_days_above_sma": 5,
    "pullback_min_pct": 3,
    "pullback_max_pct": 12,
    "rsi_period": 5,
    "rsi_max": 40,
    "min_dollar_vol": 5_000_000,
    "min_price": 5.0,
}
```
```python
        cfg: dict[str, Any] = {**_DEFAULT_PARAMS, **(config or {})}
```

Update the `register(...)` call:

```python
register(
    ScannerDescriptor(
        key="trend_pullback",
        display_name="Trend Pullback",
        description=(
            "Detects stocks in confirmed uptrends (close > SMA50 > SMA200, SMA50 rising) "
            "pulling back in an orderly way to their rising 20-day SMA. "
            "RSI(5) < 40 confirms the reset; liquidity floors apply."
        ),
        run=_orchestrator_run,
        supports_date_range=True,
        asset_classes=("stocks",),
        default_parameters=_DEFAULT_PARAMS,
    )
)
```

**`backend/app/services/liquidity_hunt.py`** — `DEFAULT_CONFIG` (line 45) is kept as-is (its name
is referenced only within this module — no rename needed per spec; the descriptor becomes the
authoritative *external* source while `DEFAULT_CONFIG` remains the internal name). Update the
registration loop (lines 728-750) to pass the two new fields for all three keys, since all three
share one `_orchestrator_run` and one `DEFAULT_CONFIG`:

```python
for _key, _display, _desc in [
    ("liquidity_hunt", "Liquidity Hunt", "Intraday liquidity concentration scanner."),
    (
        "liquidity_hunt_pre",
        "Liquidity Hunt (Pre-Market)",
        "Pre-market liquidity concentration scanner.",
    ),
    (
        "liquidity_hunt_post",
        "Liquidity Hunt (Post-Market)",
        "Post-market liquidity concentration scanner.",
    ),
]:
    # All three keys share the same _orchestrator_run and DEFAULT_CONFIG —
    # run_liquidity_hunt_scan emits all variant types.
    register(
        ScannerDescriptor(
            key=_key,
            display_name=_display,
            description=_desc,
            run=_orchestrator_run,
            supports_date_range=True,
            asset_classes=("stocks",),
            default_parameters=DEFAULT_CONFIG,
        )
    )
```

**`backend/app/services/oversold_bounce_scan.py`** — no tunable config exists; update the
`register(...)` call to be explicit:

```python
register(
    ScannerDescriptor(
        key="oversold_bounce",
        display_name="Oversold Bounce",
        description="Identifies oversold stocks showing early reversal signals.",
        run=_run,
        supports_date_range=True,
        asset_classes=("stocks",),
        default_parameters={},
    )
)
```

**`backend/app/services/pre_market_scan.py`** — same explicit-empty-defaults update:

```python
register(
    ScannerDescriptor(
        key="pre_market_volume_spike",
        display_name="Pre-Market Volume Spike",
        description="Detects stocks with >4x average volume in the pre-market window.",
        run=_run,
        supports_date_range=True,
        asset_classes=("stocks",),
        default_parameters={},
    )
)
```

### Step 4 — verify pass

```bash
docker-compose exec backend ruff check .
```
Expected: `All checks passed!` — CI's `test` job runs ruff before pytest, so each task commit
must be lint-clean, not only test-green.

```bash
docker-compose exec backend python -m pytest tests/services/test_scan_orchestrator.py tests/services/test_trend_pullback_scan.py tests/services/test_liquidity_hunt.py tests/services/test_pocket_pivot.py -q
```
Expected: all green, no `ImportError`, no `AssertionError`.

### Step 5 — commit

```bash
git add backend/app/services/pocket_pivot.py backend/app/services/trend_pullback_scan.py \
  backend/app/services/liquidity_hunt.py backend/app/services/oversold_bounce_scan.py \
  backend/app/services/pre_market_scan.py backend/tests/services/test_scan_orchestrator.py
git commit -m "feat(scanner): register asset_classes/default_parameters on all built-in scanners (#440)"
```

---

## Task 3: Private-module-via-loader end-to-end test

**Files:**
- `backend/tests/services/test_scan_orchestrator.py`

No production code changes — this exercises Task 1's already-migrated registry through #439's
real loader, per spec Requirement 6/7.

### Step 1 — write failing test

The test must genuinely exercise `load_extension_modules()` importing a module for the first
time — a `sys.modules`-preinstalled fake (via `exec()`) is a no-op import and would validate
nothing. #439's own suite (`backend/tests/core/test_extensions.py:118-138`) solves this by writing
a real temporary package to disk and prepending it to `sys.path`; duplicate that fixture locally
(rather than importing it) so this test file stays self-contained. Insert this block **after**
`test_built_in_scanners_register_seven_keys_with_metadata` (i.e. after at least one `def`), not
adjacent to the file-top imports: ruff/isort merges blank-line-separated import statements into one
block and would demand `json`/`sys` hoisted to the stdlib group and `load_extension_modules` sorted
before `scan_orchestrator` (`I001`). `E402` is ignored under `tests/**`, so a mid-file import block is
allowed — the file already does this at its `# ── New orchestration functions` section. Step 4 now
runs `ruff check .` so a misplacement fails here, not in Task 5:

```python
import json
import sys

from app.core.extensions import load_extension_modules


@pytest.fixture
def fake_scanner_package(tmp_path, monkeypatch):
    """Write a temp package to sys.path so importlib genuinely executes its body
    (mirrors app.core.extensions' own test fixture in test_extensions.py)."""
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


def test_private_module_registers_and_runs_through_loader(tmp_path, fake_scanner_package):
    call_log = tmp_path / "call_log.json"
    fake_scanner_package(
        "fake_private_scanner_ext",
        "import json\n"
        "from pathlib import Path\n"
        "from app.services.scan_orchestrator import ScannerDescriptor, register\n"
        "\n"
        "async def _run(tickers, db, event_date, scanner_run=None, gate_metadata=None):\n"
        f"    Path(r'{call_log}').write_text(json.dumps({{\n"
        "        'tickers': tickers, 'event_date': str(event_date),\n"
        "        'scanner_run': scanner_run, 'gate_metadata': gate_metadata,\n"
        "    }))\n"
        "    return [{'ticker': tickers[0]}]\n"
        "\n"
        "register(ScannerDescriptor(\n"
        "    key='private_test_scanner',\n"
        "    display_name='Private Test Scanner',\n"
        "    description='d',\n"
        "    run=_run,\n"
        "    asset_classes=('stocks',),\n"
        "    default_parameters={'threshold': 1.0},\n"
        "))\n",
    )

    load_extension_modules(["fake_private_scanner_ext"])

    today = date(2026, 5, 23)
    result = asyncio.run(run("private_test_scanner", ["AAPL"], db=None, event_date=today))
    assert result == [{"ticker": "AAPL"}]
    assert json.loads(call_log.read_text()) == {
        "tickers": ["AAPL"],
        "event_date": "2026-05-23",
        "scanner_run": None,
        "gate_metadata": None,
    }
```

The written package's top-level `register(...)` call fires exactly when `load_extension_modules`
calls `importlib.import_module("fake_private_scanner_ext")` for the first time — the same
import-time self-registration pattern every built-in module uses — so this genuinely exercises
the loader, not an import-cache no-op.

### Step 2 — verify (no red step; see note)

```bash
docker-compose exec backend python -m pytest tests/services/test_scan_orchestrator.py::test_private_module_registers_and_runs_through_loader -x -q
```
Expected (once the Prerequisite has merged #439 onto this branch): `1 passed` immediately — this
test exercises only Task 1's already-migrated registry plus #439's already-shipped loader, neither
of which this task modifies. There is no red step for this task; it is included for spec
Requirement 7's traceability, not because it fails first. A green result here on the first run is
correct — do not treat it as a gate failure. Run it anyway to confirm it currently passes before
moving on.

### Step 3 — implement

No implementation step — this task is test-only, validating Task 1 + #439's loader together.

### Step 4 — verify pass

```bash
docker-compose exec backend ruff check .
```
Expected: `All checks passed!` — CI's `test` job runs ruff before pytest, so each task commit
must be lint-clean, not only test-green.

```bash
docker-compose exec backend python -m pytest tests/services/test_scan_orchestrator.py -q
```
Expected: every test in the file passes, with no regressions from the new fixture or test.

### Step 5 — commit

```bash
git add backend/tests/services/test_scan_orchestrator.py
git commit -m "test(scanner): cover private-module registration through the #439 extension loader (#440)"
```

---

## Task 4: Expose the new fields on `/api/v1/scanner/types`

**Files:**
- `backend/app/routers/scanner.py`
- `backend/tests/api/test_scanner.py`

### Step 1 — write failing test

Update `backend/tests/api/test_scanner.py`'s key-set assertion (lines 472-474):

```python
    for item in data:
        assert {
            "key",
            "display_name",
            "description",
            "supports_date_range",
            "asset_classes",
            "default_parameters",
        } == set(item)
        assert isinstance(item["supports_date_range"], bool)
        assert isinstance(item["asset_classes"], list)
        assert isinstance(item["default_parameters"], dict)
```

### Step 2 — verify fail

```bash
docker-compose exec backend python -m pytest tests/api/test_scanner.py::test_list_scanner_types -x -q
```
Expected: `AssertionError` — response items only have the original 4 keys.

### Step 3 — implement

Update `backend/app/routers/scanner.py` lines 81-95:

```python
@router.get("/types")
@cache_response("mh:scanner:types", ttl=3600)
def list_scanner_types():
    """Return all registered scanner types for frontend scanner pickers."""
    from app.services.scan_orchestrator import get_all

    return [
        {
            "key": d.key,
            "display_name": d.display_name,
            "description": d.description,
            "supports_date_range": d.supports_date_range,
            "asset_classes": list(d.asset_classes),
            "default_parameters": dict(d.default_parameters),
        }
        for d in get_all()
    ]
```

`dict(d.default_parameters)` returns a shallow copy rather than the module-level dict by
reference (e.g. `pocket_pivot._DEFAULT_PARAMS`) — an API response consumer mutating the returned
object must not be able to mutate that scanner's real defaults for the life of the process.

### Step 4 — verify pass

```bash
docker-compose exec backend python -m pytest tests/api/test_scanner.py::test_list_scanner_types -x -q
```
Expected: `1 passed`.

**Live validation (per CLAUDE.md Development Rules — required before commit):**

`/types` is cached for 1 hour under `mh:scanner:types` (`@cache_response`, unchanged TTL) — a
process that served a request before this change is picked up will return the stale 4-key
payload. Confirm the backend actually reloaded before trusting `curl`:

```bash
docker-compose logs backend --tail=10
docker-compose exec redis redis-cli DEL mh:scanner:types
curl -s http://localhost:8000/api/v1/scanner/types | python -m json.tool
```
Expected: backend log shows a clean reload with no traceback; the curl output is a JSON array
where every item has `asset_classes` (a list) and `default_parameters` (an object) alongside the
four pre-existing fields.

### Step 5 — commit

```bash
git add backend/app/routers/scanner.py backend/tests/api/test_scanner.py
git commit -m "feat(scanner): expose asset_classes and default_parameters on /scanner/types (#440)"
```

---

## Task 5: Full-suite regression pass

**Files:** none (verification-only)

### Step 1 — run full backend suite

```bash
docker-compose exec backend python -m pytest --cov=app --cov-fail-under=60 -q
```
Expected: all tests pass, coverage ≥60%, no `_REGISTRY`-shaped `TypeError`/`AttributeError`
anywhere else in the suite (a grep-only sanity check, not a new test):

`discovery_service._SCREENER_REGISTRY` is a separate, unrelated dict-backed registry (out of scope
for #440 per the spec) — exclude it so this sanity check doesn't flag pre-existing, untouched code:

```bash
grep -rn "_REGISTRY\[" backend/tests/ backend/app/ | grep -v _SCREENER_REGISTRY || echo "no remaining dict-subscript usages"
grep -rn '"[a-z_]*" in .*_REGISTRY' backend/tests/ backend/app/ | grep -v _SCREENER_REGISTRY || echo "no remaining 'in _REGISTRY' usages"
```
Expected: both commands print only the "no remaining..." fallback line.

### Step 2 — lint

```bash
docker-compose exec backend ruff check .
```
Expected: `All checks passed!`

### Step 3 — commit

No commit — this task only verifies Tasks 1-4; if either command fails, fix the offending file
and re-run the corresponding task's Step 4 before returning here.

## Assumptions carried from the spec

- `app.core.extensions.ExtensionRegistry`, `load_extension_modules`, and
  `app.exceptions.ExtensionDuplicateError` / `ExtensionDescriptorError` exist and match the
  contract quoted in the spec — supplied by #439, which must land first.
- `oversold_bounce_scan.py` and `pre_market_scan.py` have no tunable config; their
  `default_parameters` is `{}`.
- No caller on `main` hashes a `ScannerDescriptor`, so `hash=False` on `default_parameters` is
  belt-and-braces, not a compatibility requirement (verified across `scan_orchestrator.py`,
  `routers/scanner.py`, `tasks/scanning.py`, `replay_diff_service.py`).

## Memory context check

`.archon/memory/` entries retrieved for this phase (`architecture.md`, `codebase-patterns.md`)
concern durable-state storage (Postgres vs. Redis), Docker service sprawl, and memory-retrieval
tooling — none apply to this ticket, which touches only in-process dataclasses/registries and adds
no persistence, no new service, and no memory-system code. No task steps were changed as a result;
noting this explicitly per the Phase 1 memory-context instruction.
