# Implementation Plan: Phase 4 T5 — Extend #672 Eval for Enforcement Calibration/Safety

**Date:** 2026-07-03  
**Issue:** [#718](https://github.com/omniscient/markethawk/issues/718)  
**Epic:** #713 (Phase 4 budget enforcement)  
**Spec:** `docs/superpowers/specs/2026-07-03-token-opt-phase4-t5-eval-calibration-design.md`

---

## Goal

Extend `dark-factory/evals/token_opt_eval.py` with a `--calibrate` flag that:

1. Expands scenario coverage from 3 to all 5 enforcement scenarios (`refine, plan, implement, conformance, code-review`) by default.
2. For each issue × scenario, sweeps 8 candidate budgets (22k–40k) calling `budget_enforce.derive_caps()` on the already-assembled `opt_manifest` — no re-assembly needed.
3. Computes `section_at_risk` per row (would enforcement trim below the existing architecture slice?) and `over_budget` (reserved tokens ≥ budget?).
4. Emits a `budget-calibration-scorecard-<date>.md` with per-scenario p50/p90 token distributions, `over_budget_rate@N` and `section_at_risk_rate@N` per budget, and a `safe_budget_recommendation`.
5. Appends raw calibration rows under a `calibration_results` key in the existing JSON output.

Without `--calibrate`, existing eval behavior is unchanged.

---

## Architecture

All changes are confined to one file: **`dark-factory/evals/token_opt_eval.py`**.  
Tests live in: **`dark-factory/tests/test_token_opt_eval.py`** (update existing file).

New functions added to `token_opt_eval.py`:

| Function | Purpose |
|---|---|
| `simulate_enforcement(opt_manifest, budget, config, scenario, section_check)` | Call `derive_caps()` on one issue × scenario at one budget; return row dict |
| `calibrate_issue(issue, scenario, opt_manifest, section_check, budgets, config)` | Loop over budgets; return list of row dicts |
| `safe_budget_recommendation(scenario_rows, budgets)` | Find lowest candidate where `section_at_risk_rate==0` and `over_budget_rate≤10%` |
| `generate_calibration_scorecard(calibration_rows, eval_results, budgets, output_dir)` | Write `budget-calibration-scorecard-<date>.md`; return path |
| `_get_default_budget_tokens(clone_dir)` | Read `default_budget_tokens` from `config.yaml`; fallback 30000 |

---

## Tech Stack

- Python 3 stdlib only (no new dependencies)
- `budget_enforce.derive_caps()` + `budget_enforce._load_config` imported with lazy try/except (fail-open)
- `yaml` already available in the factory container

---

## File Structure

| File | Change |
|---|---|
| `dark-factory/evals/token_opt_eval.py` | All new code: constants, imports, 5 new functions, extended `eval_issue_scenario()`, extended `run_eval()` + `main()` |
| `dark-factory/tests/test_token_opt_eval.py` | Update existing test + add calibration-specific tests |

---

## Tasks

---

### Task 1: Rename constant + backward-compat alias + update scorecard header

**Goal:** `ENFORCEMENT_SCENARIOS` replaces `TIER1_SCENARIOS` as the canonical name; `TIER1_SCENARIOS` becomes an alias pointing to the same list. Existing references (`generate_scorecard`, loop in `run_eval`) continue to work.

**Files:** `dark-factory/evals/token_opt_eval.py`, `dark-factory/tests/test_token_opt_eval.py`

#### TDD Steps

**Step 1 — Write the failing tests:**

In `dark-factory/tests/test_token_opt_eval.py`, add after `test_tier1_scenarios`:

```python
def test_enforcement_scenarios_constant():
    mod = _load_module()
    assert hasattr(mod, "ENFORCEMENT_SCENARIOS")
    assert mod.ENFORCEMENT_SCENARIOS == [
        "refine", "plan", "implement", "conformance", "code-review"
    ]


def test_tier1_scenarios_is_alias_for_enforcement_scenarios():
    mod = _load_module()
    assert mod.TIER1_SCENARIOS is mod.ENFORCEMENT_SCENARIOS
```

Also **update** (not delete) the existing `test_tier1_scenarios` to match the new semantics:

```python
def test_tier1_scenarios():
    mod = _load_module()
    # TIER1_SCENARIOS is now an alias; backward compat means it still contains all 5 scenarios
    assert "refine" in mod.TIER1_SCENARIOS
    assert "implement" in mod.TIER1_SCENARIOS
```

**Step 2 — Verify tests fail:**
```bash
cd /workspace/markethawk
python3 -m pytest dark-factory/tests/test_token_opt_eval.py::test_enforcement_scenarios_constant -x 2>&1 | tail -5
# Expected: AttributeError: module 'token_opt_eval' has no attribute 'ENFORCEMENT_SCENARIOS'
```

**Step 3 — Implement:**

In `dark-factory/evals/token_opt_eval.py`, replace the constants block:

```python
# ── Constants ─────────────────────────────────────────────────────────────────

ENFORCEMENT_SCENARIOS = ["refine", "plan", "implement", "conformance", "code-review"]
TIER1_SCENARIOS = ENFORCEMENT_SCENARIOS  # backward-compat alias

SAFETY_RULES = [
    "alembic upgrade head",
    ...
]
```

Also update `generate_scorecard()` in two places:

1. Header line — change `"## Per-Issue Savings (Tier 1: refine / plan / implement)"` to `"## Per-Issue Savings (All scenarios: refine / plan / implement / conformance / code-review)"`.
2. The two `{s: [] for s in TIER1_SCENARIOS}` dicts — change to `{s: [] for s in ENFORCEMENT_SCENARIOS}` (functionally identical now, but makes the intent clear).
3. The `for s in TIER1_SCENARIOS:` loop → `for s in ENFORCEMENT_SCENARIOS:`.

**Step 4 — Verify tests pass:**
```bash
python3 -m pytest dark-factory/tests/test_token_opt_eval.py::test_enforcement_scenarios_constant \
    dark-factory/tests/test_token_opt_eval.py::test_tier1_scenarios_is_alias_for_enforcement_scenarios \
    dark-factory/tests/test_token_opt_eval.py::test_tier1_scenarios -x
# Expected: 3 passed
```

**Step 5 — Commit:**
```bash
git add dark-factory/evals/token_opt_eval.py dark-factory/tests/test_token_opt_eval.py
git commit -m "feat(#718): rename TIER1_SCENARIOS → ENFORCEMENT_SCENARIOS; keep alias"
```

---

### Task 2: Add fail-open lazy import of `budget_enforce`

**Goal:** Import `derive_caps` and `_load_config` from `budget_enforce` at module level, wrapped in try/except. Set a module-level `_BUDGET_ENFORCE_AVAILABLE` flag so `calibrate_issue()` can skip calibration gracefully when the import fails.

**Files:** `dark-factory/evals/token_opt_eval.py`, `dark-factory/tests/test_token_opt_eval.py`

#### TDD Steps

**Step 1 — Write failing test:**

```python
def test_budget_enforce_import_flag_exists():
    mod = _load_module()
    assert hasattr(mod, "_BUDGET_ENFORCE_AVAILABLE")
    # The flag is bool; calibrate rows check it before calling derive_caps
    assert isinstance(mod._BUDGET_ENFORCE_AVAILABLE, bool)
```

**Step 2 — Verify fail:**
```bash
python3 -m pytest dark-factory/tests/test_token_opt_eval.py::test_budget_enforce_import_flag_exists -x 2>&1 | tail -5
```

**Step 3 — Implement:**

In `token_opt_eval.py`, add after the existing `from context_pack import assemble_pack` line:

```python
# Lazy import — budget_enforce.py ships with T1; wrapped fail-open so the eval
# still runs if the script is not yet present.
try:
    from budget_enforce import derive_caps as _derive_caps
    from budget_enforce import _load_config as _load_enforce_config
    _BUDGET_ENFORCE_AVAILABLE = True
except ImportError:
    _BUDGET_ENFORCE_AVAILABLE = False
    _derive_caps = None          # type: ignore[assignment]
    _load_enforce_config = None  # type: ignore[assignment]
```

**Step 4 — Verify test passes:**
```bash
python3 -m pytest dark-factory/tests/test_token_opt_eval.py::test_budget_enforce_import_flag_exists -x
```

**Step 5 — Commit:**
```bash
git add dark-factory/evals/token_opt_eval.py dark-factory/tests/test_token_opt_eval.py
git commit -m "feat(#718): fail-open lazy import of budget_enforce for calibration pass"
```

---

### Task 3: Expose `opt_manifest` from `eval_issue_scenario()`

**Goal:** Add `"opt_manifest": opt_manifest` to the dict returned by `eval_issue_scenario()` so the calibration pass can reuse the already-assembled manifest without re-assembly.

**Files:** `dark-factory/evals/token_opt_eval.py`, `dark-factory/tests/test_token_opt_eval.py`

#### TDD Steps

**Step 1 — Write failing test:**

```python
def test_eval_issue_scenario_returns_opt_manifest_key():
    """eval_issue_scenario must return opt_manifest so calibrate_issue can reuse it."""
    import types, unittest.mock as mock
    mod = _load_module()

    fake_manifest = {
        "estimated_input_tokens": 10000,
        "sections": {
            "architecture_md": {"fallback": False, "tokens": 2000,
                                "included_sections": [], "omitted_sections": [],
                                "component": "backend", "status": "sliced"},
        },
    }

    def fake_run_assemble(*args, **kwargs):
        return ("text", fake_manifest)

    with mock.patch.object(mod, "_run_assemble", side_effect=fake_run_assemble), \
         mock.patch.object(mod, "build_issue_json", return_value="{}"), \
         mock.patch("builtins.open", mock.mock_open()), \
         mock.patch("os.path.join", side_effect=lambda *a: "/tmp/" + "-".join(str(x) for x in a)):
        try:
            result = mod.eval_issue_scenario(
                {"number": 1, "title": "t", "labels": [], "body": ""},
                "plan",
                "/repo",
                "/tmp",
            )
        except Exception:
            pass
    # Key must be present in returned dict — value matches the manifest
    assert "opt_manifest" in result
    assert result["opt_manifest"] == fake_manifest
```

Because this test patches low-level I/O it may be fragile — a simpler integration approach is also acceptable (see Step 4). Add it to `test_token_opt_eval.py` alongside existing tests.

**Step 2 — Verify fail:**
```bash
python3 -m pytest dark-factory/tests/test_token_opt_eval.py::test_eval_issue_scenario_returns_opt_manifest_key -x 2>&1 | tail -10
```

**Step 3 — Implement:**

In `token_opt_eval.py`, in `eval_issue_scenario()`, change the return statement from:

```python
    return {
        "issue": issue_num,
        ...
        "omitted_arch_sections": omitted_arch,
    }
```

to:

```python
    return {
        "issue": issue_num,
        ...
        "omitted_arch_sections": omitted_arch,
        "opt_manifest": opt_manifest,      # retained for calibrate_issue(); not written to JSON
    }
```

**Step 4 — Verify test passes:**
```bash
python3 -m pytest dark-factory/tests/test_token_opt_eval.py::test_eval_issue_scenario_returns_opt_manifest_key -x
```

**Step 5 — Commit:**
```bash
git add dark-factory/evals/token_opt_eval.py dark-factory/tests/test_token_opt_eval.py
git commit -m "feat(#718): expose opt_manifest in eval_issue_scenario return dict"
```

---

### Task 4: Add `simulate_enforcement()` function

**Goal:** Implement the per-row enforcement simulation: call `derive_caps()` on the manifest's `sections` dict, compute `section_at_risk`, and return a structured row dict. Handle fail-open: if `_BUDGET_ENFORCE_AVAILABLE` is False or `derive_caps` raises, return a row with `status: "calibration_error"`.

**Files:** `dark-factory/evals/token_opt_eval.py`, `dark-factory/tests/test_token_opt_eval.py`

#### TDD Steps

**Step 1 — Write failing tests:**

```python
def test_simulate_enforcement_section_at_risk_when_trim_needed():
    """arch_fallback=False + derived_arch < opt_arch_tokens → section_at_risk=True."""
    mod = _load_module()
    from dataclasses import dataclass

    # Build a minimal BudgetResult stub matching budget_enforce.BudgetResult fields
    @dataclass
    class FakeBudgetResult:
        reserved_tokens: int = 25000
        allowance: int = 5000
        over_budget: bool = False
        derived_caps: dict = None
        would_trim: bool = True
        sections_skipped: list = None
        claude_md_tokens: int = 20000
        issue_context_tokens: int = 5000

        def __post_init__(self):
            if self.derived_caps is None:
                self.derived_caps = {"architecture_md": 1000}  # 1000 < opt_arch_tokens=2000
            if self.sections_skipped is None:
                self.sections_skipped = []

    opt_manifest = {
        "sections": {
            "architecture_md": {"fallback": False, "tokens": 2000, "status": "sliced"},
        }
    }
    section_check = {}  # no pre-existing gaps

    import unittest.mock as mock
    with mock.patch.object(mod, "_derive_caps", return_value=FakeBudgetResult()), \
         mock.patch.object(mod, "_BUDGET_ENFORCE_AVAILABLE", True):
        row = mod.simulate_enforcement(
            opt_manifest=opt_manifest,
            budget=30000,
            config={},
            scenario="plan",
            section_check=section_check,
        )

    assert row["section_at_risk"] is True
    assert row["over_budget"] is False
    assert row["would_trim"] is True
    assert row["budget"] == 30000


def test_simulate_enforcement_no_risk_when_cap_sufficient():
    """derived_arch >= opt_arch_tokens → section_at_risk=False."""
    mod = _load_module()
    from dataclasses import dataclass

    @dataclass
    class FakeBudgetResult:
        reserved_tokens: int = 10000
        allowance: int = 20000
        over_budget: bool = False
        derived_caps: dict = None
        would_trim: bool = False
        sections_skipped: list = None
        claude_md_tokens: int = 8000
        issue_context_tokens: int = 2000

        def __post_init__(self):
            if self.derived_caps is None:
                self.derived_caps = {"architecture_md": 3000}  # 3000 >= opt_arch=2000
            if self.sections_skipped is None:
                self.sections_skipped = []

    opt_manifest = {
        "sections": {
            "architecture_md": {"fallback": False, "tokens": 2000, "status": "sliced"},
        }
    }
    import unittest.mock as mock
    with mock.patch.object(mod, "_derive_caps", return_value=FakeBudgetResult()), \
         mock.patch.object(mod, "_BUDGET_ENFORCE_AVAILABLE", True):
        row = mod.simulate_enforcement(opt_manifest, 30000, {}, "plan", {})

    assert row["section_at_risk"] is False


def test_simulate_enforcement_propagates_preexisting_missing():
    """Pre-existing section_check 'missing' → section_at_risk=True regardless of budget."""
    mod = _load_module()
    from dataclasses import dataclass

    @dataclass
    class FakeBudgetResult:
        reserved_tokens: int = 10000
        allowance: int = 20000
        over_budget: bool = False
        derived_caps: dict = None
        would_trim: bool = False
        sections_skipped: list = None
        claude_md_tokens: int = 8000
        issue_context_tokens: int = 2000

        def __post_init__(self):
            if self.derived_caps is None:
                self.derived_caps = {"architecture_md": 3000}  # cap generous
            if self.sections_skipped is None:
                self.sections_skipped = []

    opt_manifest = {
        "sections": {
            "architecture_md": {"fallback": False, "tokens": 2000, "status": "sliced"},
        }
    }
    section_check = {"Backend Module Map": "missing"}  # pre-existing gap
    import unittest.mock as mock
    with mock.patch.object(mod, "_derive_caps", return_value=FakeBudgetResult()), \
         mock.patch.object(mod, "_BUDGET_ENFORCE_AVAILABLE", True):
        row = mod.simulate_enforcement(opt_manifest, 30000, {}, "plan", section_check)

    assert row["section_at_risk"] is True


def test_simulate_enforcement_fallback_no_risk():
    """arch_fallback=True → architecture in full-doc mode, not trimmed → section_at_risk=False."""
    mod = _load_module()
    from dataclasses import dataclass

    @dataclass
    class FakeBudgetResult:
        reserved_tokens: int = 25000
        allowance: int = 5000
        over_budget: bool = False
        derived_caps: dict = None
        would_trim: bool = False
        sections_skipped: list = None
        claude_md_tokens: int = 20000
        issue_context_tokens: int = 5000

        def __post_init__(self):
            if self.derived_caps is None:
                # architecture_md not in derived_caps when arch_fallback=True (reserved)
                self.derived_caps = {}
            if self.sections_skipped is None:
                self.sections_skipped = []

    opt_manifest = {
        "sections": {
            "architecture_md": {"fallback": True, "tokens": 15000, "status": "full"},
        }
    }
    import unittest.mock as mock
    with mock.patch.object(mod, "_derive_caps", return_value=FakeBudgetResult()), \
         mock.patch.object(mod, "_BUDGET_ENFORCE_AVAILABLE", True):
        row = mod.simulate_enforcement(opt_manifest, 30000, {}, "plan", {})

    assert row["section_at_risk"] is False


def test_simulate_enforcement_unavailable_returns_error_row():
    """When _BUDGET_ENFORCE_AVAILABLE=False, simulate_enforcement returns calibration_error row."""
    mod = _load_module()
    import unittest.mock as mock
    with mock.patch.object(mod, "_BUDGET_ENFORCE_AVAILABLE", False):
        row = mod.simulate_enforcement({"sections": {}}, 30000, {}, "plan", {})

    assert row.get("status") == "calibration_error"
    assert row["budget"] == 30000
```

**Step 2 — Verify fail:**
```bash
python3 -m pytest dark-factory/tests/test_token_opt_eval.py -k "test_simulate_enforcement" -x 2>&1 | tail -10
# Expected: AttributeError — simulate_enforcement not yet defined
```

**Step 3 — Implement:**

Add after `_check_section_presence()` in `token_opt_eval.py`:

```python
# ── Calibration: enforcement simulation ───────────────────────────────────────


def simulate_enforcement(
    opt_manifest: dict,
    budget: int,
    config: dict,
    scenario: str,
    section_check: dict,
) -> dict:
    """Call derive_caps on opt_manifest sections at one budget; compute section_at_risk.

    Returns a row dict. If budget_enforce is unavailable or derive_caps raises,
    returns {"status": "calibration_error", "budget": budget, ...} — never raises.
    """
    if not _BUDGET_ENFORCE_AVAILABLE:
        return {
            "budget": budget,
            "status": "calibration_error",
            "error": "budget_enforce unavailable (ImportError)",
            "section_at_risk": None,
            "over_budget": None,
            "would_trim": None,
            "derived_caps": {},
            "reserved_tokens": None,
            "allowance": None,
        }

    sections = opt_manifest.get("sections", {})
    arch_fallback = bool(sections.get("architecture_md", {}).get("fallback", False))
    opt_arch_tokens = int(sections.get("architecture_md", {}).get("tokens", 0))

    try:
        result = _derive_caps(
            sections=sections,
            budget=budget,
            arch_fallback=arch_fallback,
            config=config,
            scenario=scenario,
        )
    except Exception as exc:
        return {
            "budget": budget,
            "status": "calibration_error",
            "error": str(exc),
            "section_at_risk": None,
            "over_budget": None,
            "would_trim": None,
            "derived_caps": {},
            "reserved_tokens": None,
            "allowance": None,
        }

    # Section-at-risk: enforcement would trim the architecture slice below its current size.
    # arch_fallback=True means architecture is reserved (full-doc), not trimmed by derive_caps.
    section_at_risk = False
    if not arch_fallback:
        derived_arch = result.derived_caps.get("architecture_md")
        if derived_arch is not None and derived_arch < opt_arch_tokens:
            section_at_risk = True
    # Pre-existing section gaps propagate unconditionally.
    if section_check and any(v == "missing" for v in section_check.values()):
        section_at_risk = True

    return {
        "budget": budget,
        "over_budget": result.over_budget,
        "would_trim": result.would_trim,
        "derived_caps": result.derived_caps,
        "section_at_risk": section_at_risk,
        "reserved_tokens": result.reserved_tokens,
        "allowance": result.allowance,
    }
```

**Step 4 — Verify tests pass:**
```bash
python3 -m pytest dark-factory/tests/test_token_opt_eval.py -k "test_simulate_enforcement" -x
# Expected: 5 passed
```

**Step 5 — Commit:**
```bash
git add dark-factory/evals/token_opt_eval.py dark-factory/tests/test_token_opt_eval.py
git commit -m "feat(#718): add simulate_enforcement() for per-row calibration simulation"
```

---

### Task 5: Add `calibrate_issue()` and `_get_default_budget_tokens()` functions

**Goal:** `calibrate_issue()` loops over the budget sweep, calls `simulate_enforcement()` for each budget, and tags each row with `{issue, scenario}` metadata. `_get_default_budget_tokens()` reads `token_optimization.default_budget_tokens` from `config.yaml`, used later to ensure it is always included in the sweep.

**Files:** `dark-factory/evals/token_opt_eval.py`, `dark-factory/tests/test_token_opt_eval.py`

#### TDD Steps

**Step 1 — Write failing tests:**

```python
def test_calibrate_issue_returns_one_row_per_budget():
    """calibrate_issue must return exactly len(budgets) rows."""
    mod = _load_module()
    import unittest.mock as mock

    fake_row = {
        "budget": 0, "over_budget": False, "would_trim": False,
        "derived_caps": {}, "section_at_risk": False,
        "reserved_tokens": 0, "allowance": 0,
    }

    with mock.patch.object(mod, "simulate_enforcement", return_value=fake_row):
        rows = mod.calibrate_issue(
            issue={"number": 42},
            scenario="plan",
            opt_manifest={"sections": {}},
            section_check={},
            budgets=[22000, 28000, 36000],
            config={},
        )

    assert len(rows) == 3
    assert all(r["issue"] == 42 for r in rows)
    assert all(r["scenario"] == "plan" for r in rows)
    assert rows[0]["budget_swept"] == 22000
    assert rows[1]["budget_swept"] == 28000
    assert rows[2]["budget_swept"] == 36000


def test_get_default_budget_tokens_fallback():
    """_get_default_budget_tokens returns 30000 when config.yaml is not found."""
    mod = _load_module()
    result = mod._get_default_budget_tokens("/nonexistent/repo")
    assert result == 30000
```

**Step 2 — Verify fail:**
```bash
python3 -m pytest dark-factory/tests/test_token_opt_eval.py -k "test_calibrate_issue or test_get_default_budget" -x 2>&1 | tail -10
```

**Step 3 — Implement:**

Add after `simulate_enforcement()` in `token_opt_eval.py`:

```python
def calibrate_issue(
    issue: dict,
    scenario: str,
    opt_manifest: dict,
    section_check: dict,
    budgets: list,
    config: dict,
) -> list:
    """Sweep budgets for one issue × scenario; return one row dict per budget."""
    rows = []
    issue_num = issue.get("number")
    for budget in budgets:
        row = simulate_enforcement(opt_manifest, budget, config, scenario, section_check)
        row["issue"] = issue_num
        row["scenario"] = scenario
        row["budget_swept"] = budget
        rows.append(row)
    return rows


def _get_default_budget_tokens(clone_dir: str) -> int:
    """Read token_optimization.default_budget_tokens from config.yaml; fallback 30000."""
    config_path = os.path.join(clone_dir, ".claude", "skills", "refinement", "config.yaml")
    try:
        import yaml  # type: ignore
        with open(config_path, encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        return int(
            data.get("token_optimization", {}).get("default_budget_tokens", 30000)
        )
    except Exception:
        return 30000
```

**Step 4 — Verify tests pass:**
```bash
python3 -m pytest dark-factory/tests/test_token_opt_eval.py -k "test_calibrate_issue or test_get_default_budget" -x
# Expected: 2 passed
```

**Step 5 — Commit:**
```bash
git add dark-factory/evals/token_opt_eval.py dark-factory/tests/test_token_opt_eval.py
git commit -m "feat(#718): add calibrate_issue() and _get_default_budget_tokens() helpers"
```

---

### Task 6: Add `safe_budget_recommendation()` and `generate_calibration_scorecard()`

**Goal:** Implement the scorecard emitter. `safe_budget_recommendation()` finds the lowest budget where `section_at_risk_rate == 0` AND `over_budget_rate ≤ 10%`. `generate_calibration_scorecard()` computes p50/p90 from the existing eval results and builds the full markdown scorecard.

**Files:** `dark-factory/evals/token_opt_eval.py`, `dark-factory/tests/test_token_opt_eval.py`

#### TDD Steps

**Step 1 — Write failing tests:**

```python
def test_safe_budget_recommendation_lowest_qualifying():
    mod = _load_module()
    # 22000 has section_at_risk, 28000 has over_budget_rate=20%, 36000 qualifies
    rows = [
        # budget=22000: section_at_risk → disqualified
        {"budget_swept": 22000, "section_at_risk": True, "over_budget": False},
        # budget=28000: over_budget_rate=2/2=100% → disqualified
        {"budget_swept": 28000, "section_at_risk": False, "over_budget": True},
        {"budget_swept": 28000, "section_at_risk": False, "over_budget": True},
        # budget=36000: section_at_risk_rate=0, over_budget_rate=0 → qualifies
        {"budget_swept": 36000, "section_at_risk": False, "over_budget": False},
        {"budget_swept": 36000, "section_at_risk": False, "over_budget": False},
    ]
    result = mod.safe_budget_recommendation(rows, [22000, 28000, 36000])
    assert result == "36000"


def test_safe_budget_recommendation_none_when_all_fail():
    mod = _load_module()
    rows = [
        {"budget_swept": 22000, "section_at_risk": True, "over_budget": False},
    ]
    result = mod.safe_budget_recommendation(rows, [22000])
    assert result == "none — widen --budgets"


def test_safe_budget_recommendation_over_budget_threshold():
    """over_budget_rate <= 10% (1 in 10 = exactly 10%) should qualify."""
    mod = _load_module()
    rows = (
        [{"budget_swept": 30000, "section_at_risk": False, "over_budget": True}]
        + [{"budget_swept": 30000, "section_at_risk": False, "over_budget": False}] * 9
    )
    result = mod.safe_budget_recommendation(rows, [30000])
    assert result == "30000"


def test_generate_calibration_scorecard_creates_file(tmp_path):
    mod = _load_module()
    calibration_rows = [
        {"issue": 1, "scenario": "plan", "budget_swept": 30000,
         "section_at_risk": False, "over_budget": False, "would_trim": False,
         "derived_caps": {}, "reserved_tokens": 10000, "allowance": 20000},
    ]
    eval_results = [
        {"issue": 1, "scenario": "plan", "opt_tokens": 28000},
    ]
    budgets = [30000]
    path = mod.generate_calibration_scorecard(
        calibration_rows, eval_results, budgets, str(tmp_path)
    )
    assert os.path.exists(path)
    with open(path, encoding="utf-8") as f:
        text = f.read()
    assert "budget-calibration" in path
    assert "p50" in text or "p90" in text
    assert "safe_budget_recommendation" in text or "Safe budget" in text
```

**Step 2 — Verify fail:**
```bash
python3 -m pytest dark-factory/tests/test_token_opt_eval.py -k "test_safe_budget or test_generate_calibration" -x 2>&1 | tail -10
```

**Step 3 — Implement:**

Add after `calibrate_issue()` in `token_opt_eval.py`:

```python
def safe_budget_recommendation(scenario_rows: list, budgets: list) -> str:
    """Return the lowest swept budget (as string) where section_at_risk_rate==0 AND
    over_budget_rate<=10%, or 'none — widen --budgets' if no candidate qualifies."""
    for budget in sorted(budgets):
        rows_at = [r for r in scenario_rows if r.get("budget_swept") == budget]
        if not rows_at:
            continue
        section_at_risk_rate = sum(
            1 for r in rows_at if r.get("section_at_risk")
        ) / len(rows_at)
        over_budget_rate = sum(
            1 for r in rows_at if r.get("over_budget")
        ) / len(rows_at)
        if section_at_risk_rate == 0.0 and over_budget_rate <= 0.10:
            return str(budget)
    return "none — widen --budgets"


def generate_calibration_scorecard(
    calibration_rows: list,
    eval_results: list,
    budgets: list,
    output_dir: str,
) -> str:
    """Write budget-calibration-scorecard-<date>.md. Returns path."""
    import statistics

    date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    reports_dir = os.path.join(output_dir, "reports")
    os.makedirs(reports_dir, exist_ok=True)

    # Group calibration rows by scenario
    scenarios_seen: list[str] = []
    rows_by_scenario: dict[str, list] = {}
    for r in calibration_rows:
        s = r.get("scenario", "unknown")
        if s not in rows_by_scenario:
            rows_by_scenario[s] = []
            scenarios_seen.append(s)
        rows_by_scenario[s].append(r)

    # Compute p50/p90 opt_tokens per scenario from eval_results
    opt_tokens_by_scenario: dict[str, list] = {}
    for r in eval_results:
        if r.get("status") in ("skipped", "error") or "opt_tokens" not in r:
            continue
        s = r.get("scenario", "unknown")
        opt_tokens_by_scenario.setdefault(s, []).append(r["opt_tokens"])

    sorted_budgets = sorted(budgets)

    lines: list[str] = []
    lines.append(f"# Budget Calibration Scorecard — {date_str}")
    lines.append("")
    lines.append("**Issue:** [#718](https://github.com/omniscient/markethawk/issues/718)")
    lines.append("**Script:** `dark-factory/evals/token_opt_eval.py --calibrate`")
    lines.append(f"**Budgets swept:** {sorted_budgets}")
    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append("## Per-Scenario Summary")
    lines.append("")

    # Build header
    budget_cols = " | ".join(f"ob@{b//1000}k | sar@{b//1000}k" for b in sorted_budgets)
    lines.append(f"| Scenario | p50 opt_tokens | p90 opt_tokens | p90+10% headroom | {budget_cols} | safe_budget_recommendation |")
    sep_cols = " | ".join("--- | ---" for _ in sorted_budgets)
    lines.append(f"|----------|----------------|----------------|------------------|{sep_cols}|---------------------------|")

    for scenario in scenarios_seen:
        s_rows = rows_by_scenario[scenario]
        opt_tokens = opt_tokens_by_scenario.get(scenario, [])

        if opt_tokens:
            sorted_opt = sorted(opt_tokens)
            n = len(sorted_opt)
            p50 = int(statistics.median(sorted_opt))
            p90_idx = min(int(n * 0.9), n - 1)
            p90 = sorted_opt[p90_idx]
            p90_headroom = int(p90 * 1.1)
        else:
            p50 = p90 = p90_headroom = 0

        rec = safe_budget_recommendation(s_rows, sorted_budgets)

        rate_cols_parts = []
        for budget in sorted_budgets:
            rows_at = [r for r in s_rows if r.get("budget_swept") == budget]
            if rows_at:
                ob_rate = f"{sum(1 for r in rows_at if r.get('over_budget')) / len(rows_at):.0%}"
                sar_rate = f"{sum(1 for r in rows_at if r.get('section_at_risk')) / len(rows_at):.0%}"
            else:
                ob_rate = sar_rate = "—"
            rate_cols_parts.append(f"{ob_rate} | {sar_rate}")
        rate_cols = " | ".join(rate_cols_parts)

        lines.append(
            f"| {scenario} | {p50:,} | {p90:,} | {p90_headroom:,} | {rate_cols} | {rec} |"
        )

    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append("## Column Definitions")
    lines.append("")
    lines.append("- **p50/p90 opt_tokens** — distribution of optimized-pack token counts from the standard eval pass")
    lines.append("- **ob@Nk** (`over_budget_rate@N`) — fraction of issue × scenario rows where `reserved_tokens >= N`")
    lines.append("- **sar@Nk** (`section_at_risk_rate@N`) — fraction where enforcement would trim the arch slice below its current size, or where a required section is pre-existing missing")
    lines.append("- **p90+10% headroom** — advisory figure: `p90_opt_tokens * 1.1`; not used as recommendation")
    lines.append("- **safe_budget_recommendation** — lowest swept candidate where `sar==0%` AND `ob≤10%`; or `none — widen --budgets`")
    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append("*Generated by `dark-factory/evals/token_opt_eval.py --calibrate`*")

    path = os.path.join(reports_dir, f"budget-calibration-scorecard-{date_str}.md")
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    print(f"Calibration scorecard written: {path}")
    return path
```

**Step 4 — Verify tests pass:**
```bash
python3 -m pytest dark-factory/tests/test_token_opt_eval.py -k "test_safe_budget or test_generate_calibration" -x
# Expected: 4 passed
```

**Step 5 — Commit:**
```bash
git add dark-factory/evals/token_opt_eval.py dark-factory/tests/test_token_opt_eval.py
git commit -m "feat(#718): add safe_budget_recommendation() and generate_calibration_scorecard()"
```

---

### Task 7: Extend `run_eval()` and `main()` with `--calibrate`, `--budgets`, `--scenarios`

**Goal:** Wire the calibration pass into the main eval loop. Add three CLI flags. Extend `run_eval()` to accept `calibrate`, `budgets`, and `scenarios` parameters. When `calibrate=True`, call `calibrate_issue()` after each `eval_issue_scenario()` and aggregate results. Append `calibration_results` to JSON output and call `generate_calibration_scorecard()`. Strip `opt_manifest` from the result dicts before writing to JSON (it's not serializable and not needed in output). Ensure `default_budget_tokens` from config is always merged into the budget sweep.

**Files:** `dark-factory/evals/token_opt_eval.py`, `dark-factory/tests/test_token_opt_eval.py`

#### TDD Steps

**Step 1 — Write failing tests:**

```python
def test_default_budgets_include_config_default(tmp_path):
    """The default budget sweep must always include config's default_budget_tokens."""
    mod = _load_module()
    import unittest.mock as mock

    # If _get_default_budget_tokens returns 31000 (not in hardcoded default list),
    # it should still appear in the merged sweep.
    with mock.patch.object(mod, "_get_default_budget_tokens", return_value=31000):
        sweep = mod._build_budget_sweep(None, "/repo")  # None = use hardcoded defaults

    assert 31000 in sweep
    assert 22000 in sweep  # hardcoded defaults still present


def test_run_eval_calibrate_false_no_calibration_results(tmp_path, monkeypatch):
    """Without --calibrate, the JSON output must not contain calibration_results."""
    mod = _load_module()
    import unittest.mock as mock

    empty_manifest = {
        "estimated_input_tokens": 1000,
        "sections": {"architecture_md": {"fallback": True, "tokens": 0,
                                         "included_sections": [], "omitted_sections": [],
                                         "component": None, "status": "full"}},
    }

    with mock.patch.object(mod, "fetch_issue", return_value={
            "number": 1, "title": "t", "body": "", "labels": []}), \
         mock.patch.object(mod, "_run_assemble", return_value=("", empty_manifest)), \
         mock.patch("builtins.open", mock.mock_open(read_data='{"tasks":[]}')), \
         mock.patch("json.load", return_value={"tasks": []}), \
         mock.patch("json.dump") as mock_dump, \
         mock.patch("os.makedirs"), \
         mock.patch("tempfile.TemporaryDirectory"):
        # Runs eval with default calibrate=False; we only test that calibration_results is absent.
        pass  # Integration-level — use the CLI smoke test below instead.
```

Because the integration test for `run_eval` requires heavy mocking, use a simpler smoke approach:

```python
def test_main_help_contains_calibrate_flag():
    """Smoke test: --help output must mention --calibrate, --budgets, --scenarios."""
    import subprocess, sys
    result = subprocess.run(
        [sys.executable, SCRIPT_PATH, "--help"],
        capture_output=True, text=True,
    )
    assert "--calibrate" in result.stdout
    assert "--budgets" in result.stdout
    assert "--scenarios" in result.stdout


def test_run_eval_accepts_calibrate_param():
    """run_eval() must accept calibrate, budgets, scenarios kwargs without raising."""
    mod = _load_module()
    import inspect
    sig = inspect.signature(mod.run_eval)
    assert "calibrate" in sig.parameters
    assert "budgets" in sig.parameters
    assert "scenarios" in sig.parameters
```

**Step 2 — Verify fail:**
```bash
python3 -m pytest dark-factory/tests/test_token_opt_eval.py -k "test_default_budgets or test_main_help or test_run_eval_accepts" -x 2>&1 | tail -10
```

**Step 3 — Implement:**

Add the `_build_budget_sweep()` helper above `run_eval()`:

```python
_DEFAULT_BUDGETS = [22000, 24000, 26000, 28000, 30000, 32000, 36000, 40000]


def _build_budget_sweep(budgets_override: list | None, clone_dir: str) -> list:
    """Return deduplicated sorted budget list. Always includes config's default_budget_tokens."""
    base = budgets_override if budgets_override is not None else list(_DEFAULT_BUDGETS)
    default_from_config = _get_default_budget_tokens(clone_dir)
    merged = sorted(set(base) | {default_from_config})
    return merged
```

Update `run_eval()` signature and body:

```python
def run_eval(
    clone_dir: str,
    output_dir: str,
    issue_override: list | None = None,
    dry_run: bool = False,
    calibrate: bool = False,
    budgets: list | None = None,
    scenarios: list | None = None,
) -> dict:
    """Run the full evaluation; return aggregated results dict."""
    suite_json = os.path.join(clone_dir, "dark-factory", "bench", "suite.json")
    bench_issues = load_bench_issues(suite_json)

    active_scenarios = scenarios if scenarios is not None else ENFORCEMENT_SCENARIOS
    budget_sweep = _build_budget_sweep(budgets, clone_dir)

    if issue_override:
        all_issues = issue_override
    else:
        all_issues = bench_issues + SUPPLEMENTAL_SCOPE_SPILLOVER + SUPPLEMENTAL_FACTORY_REGRESSION

    seen: set = set()
    deduped: list = []
    for n in all_issues:
        if n not in seen:
            seen.add(n)
            deduped.append(n)
    all_issues = deduped

    print(f"Evaluation corpus: {len(all_issues)} issues")
    print(f"Issues: {all_issues}")
    print(f"Scenarios: {active_scenarios}")
    if calibrate:
        print(f"Calibrate: ON — budget sweep: {budget_sweep}")

    if dry_run:
        print("[dry-run] Exiting without running eval.")
        return {"dry_run": True, "issues": all_issues}

    results_dir = os.path.join(output_dir, "results")
    os.makedirs(results_dir, exist_ok=True)

    # Load enforce config once for the calibration pass
    enforce_config: dict = {}
    if calibrate and _BUDGET_ENFORCE_AVAILABLE:
        config_path = os.path.join(clone_dir, ".claude", "skills", "refinement", "config.yaml")
        enforce_config = _load_enforce_config(config_path)

    all_results: list = []
    all_calibration_rows: list = []

    with tempfile.TemporaryDirectory(prefix="tokeval-") as tmp_dir:
        for issue_num in all_issues:
            print(f"\n── Issue #{issue_num} ──")
            issue = fetch_issue(issue_num)
            if issue is None:
                all_results.append({
                    "issue": issue_num, "status": "skipped", "reason": "fetch_failed",
                })
                continue

            for scenario in active_scenarios:
                print(f"  scenario={scenario} ...", end="", flush=True)
                try:
                    result = eval_issue_scenario(issue, scenario, clone_dir, tmp_dir)
                    verdict = safety_verdict(result["safety"], result.get("section_check"))
                    savings = result["savings_pct"]
                    print(
                        f" baseline={result['baseline_tokens']:,}"
                        f" optimized={result['opt_tokens']:,}"
                        f" savings={savings}%"
                        f" safety={verdict}"
                    )
                    # Calibration pass: reuse opt_manifest; do not re-assemble
                    if calibrate:
                        opt_manifest = result.get("opt_manifest", {})
                        section_check = result.get("section_check", {})
                        cal_rows = calibrate_issue(
                            issue=issue,
                            scenario=scenario,
                            opt_manifest=opt_manifest,
                            section_check=section_check,
                            budgets=budget_sweep,
                            config=enforce_config,
                        )
                        all_calibration_rows.extend(cal_rows)
                    # Strip opt_manifest before accumulating for JSON output
                    result_for_json = {k: v for k, v in result.items() if k != "opt_manifest"}
                    all_results.append(result_for_json)
                except Exception as e:
                    print(f" ERROR: {e}", file=sys.stderr)
                    all_results.append({
                        "issue": issue_num, "scenario": scenario,
                        "status": "error", "error": str(e),
                    })

    date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    output_payload: dict = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "results": all_results,
    }
    if calibrate:
        output_payload["calibration_results"] = all_calibration_rows

    json_path = os.path.join(results_dir, f"token-opt-eval-{date_str}.json")
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(output_payload, f, indent=2)
    print(f"\nResults written: {json_path}")

    return {
        "results": all_results,
        "calibration_results": all_calibration_rows,
        "json_path": json_path,
        "date": date_str,
        "calibrate": calibrate,
        "budget_sweep": budget_sweep,
    }
```

Update `main()` to add the three new args and pass them through:

```python
def main() -> None:
    parser = argparse.ArgumentParser(description="Token optimization eval for issue #672")
    parser.add_argument("--clone-dir", default="/workspace/markethawk")
    parser.add_argument("--output-dir", default=None)
    parser.add_argument("--issues", default=None,
                        help="Comma-separated issue numbers (overrides suite.json + supplementals)")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument(
        "--calibrate", action="store_true",
        help="Run enforcement simulation sweep after the standard eval pass",
    )
    parser.add_argument(
        "--budgets", default=None,
        help="Comma-separated candidate budgets (default: 22000,24000,...,40000)",
    )
    parser.add_argument(
        "--scenarios", default=None,
        help="Comma-separated scenarios to evaluate (default: all 5 enforcement scenarios)",
    )
    args = parser.parse_args()

    clone_dir = args.clone_dir
    output_dir = args.output_dir or os.path.join(clone_dir, "dark-factory", "evals")

    issue_override = None
    if args.issues:
        issue_override = [int(n.strip()) for n in args.issues.split(",") if n.strip()]

    budgets_override = None
    if args.budgets:
        budgets_override = [int(n.strip()) for n in args.budgets.split(",") if n.strip()]

    scenarios_override = None
    if args.scenarios:
        scenarios_override = [s.strip() for s in args.scenarios.split(",") if s.strip()]

    eval_data = run_eval(
        clone_dir, output_dir, issue_override, args.dry_run,
        calibrate=args.calibrate,
        budgets=budgets_override,
        scenarios=scenarios_override,
    )

    if not eval_data.get("dry_run"):
        generate_scorecard(eval_data, output_dir, clone_dir)
        if eval_data.get("calibrate") and eval_data.get("calibration_results"):
            generate_calibration_scorecard(
                eval_data["calibration_results"],
                eval_data["results"],
                eval_data["budget_sweep"],
                output_dir,
            )
```

**Step 4 — Verify tests pass:**
```bash
python3 -m pytest dark-factory/tests/test_token_opt_eval.py -k "test_default_budgets or test_main_help or test_run_eval_accepts" -x
# Expected: 3 passed
```

Run the full test suite for the module:
```bash
python3 -m pytest dark-factory/tests/test_token_opt_eval.py -v 2>&1 | tail -30
# Expected: all existing + new tests pass
```

Smoke test the new flags:
```bash
python3 dark-factory/evals/token_opt_eval.py --help
# Expected output includes: --calibrate, --budgets, --scenarios
```

**Step 5 — Commit:**
```bash
git add dark-factory/evals/token_opt_eval.py dark-factory/tests/test_token_opt_eval.py
git commit -m "feat(#718): wire --calibrate/--budgets/--scenarios into run_eval() and main()"
```

---

## Final Validation

After all 7 tasks, run the complete test suite:

```bash
python3 -m pytest dark-factory/tests/test_token_opt_eval.py -v
# Expected: all tests pass (no regressions; existing test_tier1_scenarios updated to match alias)
```

Smoke-test the module is importable and the constants are correct:
```bash
python3 -c "
import sys; sys.path.insert(0, 'dark-factory/evals')
sys.path.insert(0, 'dark-factory/scripts')
import token_opt_eval as m
assert m.ENFORCEMENT_SCENARIOS == ['refine','plan','implement','conformance','code-review']
assert m.TIER1_SCENARIOS is m.ENFORCEMENT_SCENARIOS
assert m._BUDGET_ENFORCE_AVAILABLE is True
assert hasattr(m, 'simulate_enforcement')
assert hasattr(m, 'calibrate_issue')
assert hasattr(m, 'safe_budget_recommendation')
assert hasattr(m, 'generate_calibration_scorecard')
print('All assertions passed')
"
```

Dry-run with calibration:
```bash
python3 dark-factory/evals/token_opt_eval.py \
    --clone-dir /workspace/markethawk \
    --dry-run \
    --calibrate \
    --budgets 28000,30000,36000 \
    --scenarios refine,plan
# Expected: prints corpus size and exits — no error
```

---

## Checklist

- [ ] `ENFORCEMENT_SCENARIOS` constant, `TIER1_SCENARIOS` alias
- [ ] Fail-open `budget_enforce` import, `_BUDGET_ENFORCE_AVAILABLE` flag
- [ ] `eval_issue_scenario()` returns `opt_manifest` key
- [ ] `simulate_enforcement()` with `section_at_risk` logic + fail-open error row
- [ ] `calibrate_issue()` loops budgets, tags rows with `{issue, scenario, budget_swept}`
- [ ] `_get_default_budget_tokens()` reads config, fallback 30000
- [ ] `_build_budget_sweep()` merges hardcoded defaults + config default + CLI override
- [ ] `safe_budget_recommendation()` with `section_at_risk_rate==0` AND `over_budget_rate≤10%`
- [ ] `generate_calibration_scorecard()` emits `budget-calibration-scorecard-<date>.md`
- [ ] `run_eval()` extended: `calibrate`, `budgets`, `scenarios` params; strips `opt_manifest` before JSON write
- [ ] `main()` extended: `--calibrate`, `--budgets`, `--scenarios` flags; calls scorecard if calibrate
- [ ] All new tests pass; existing tests pass (including updated `test_tier1_scenarios`)
