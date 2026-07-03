# Raise Arch-Slice Token Cap Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Raise `architecture.max_tokens` from 3,000 to 5,000 (and `min_tokens` from 1,500 to 2,500) across all three pinning sites — `config.yaml`, `_HARDCODED` in `budget_enforce.py`, and `DEFAULT_CONFIG` in the test file — then re-run `token_opt_eval.py --calibrate` and commit a scorecard proving `section_at_risk_rate == 0%` and `over_budget_rate <= 10%` for refine/plan at 30k. The fix eliminates the structural root cause of the 50% `section_at_risk_rate` seen in T5 (p90 uncapped arch-slice = 4,645 tokens, 35% above the 3,000 cap).

**Architecture:** Pure config/code change within the dark-factory scripts layer. No new files, no schema migrations, no Docker changes. Three files change: `config.yaml` (runtime config), `budget_enforce.py` (fallback hardcoded defaults), `test_budget_enforce.py` (test-local DEFAULT_CONFIG + assertions that pin old cap values). A calibration run after the code changes produces new report artifacts.

**Tech Stack:** Python 3, pytest (dark-factory tests), `token_opt_eval.py --calibrate` (full corpus), ANTHROPIC_API_KEY (calibration requires live API).

## Global Constraints

- `enforce` flags (`enforce.refine`, `enforce.plan`) must NOT be touched — the enforcement flip is a separate follow-on ticket.
- Do NOT change line 282 (`"architecture": {"max_tokens": 3000, "min_tokens": 100}`) — custom test config with intentional floor=100.
- Do NOT change line 388 (`"architecture_md": {"tokens": 3000, ...}`) — a section *size* fixture, not a cap value.
- Do NOT change `make_sections(arch_tokens=3000)` default — represents typical arch slice size in test helpers, not the cap.
- `min_tokens` must always be 50% of `max_tokens` (floor convention from T1 #714).

## File Structure

| File | Action | Why |
|---|---|---|
| `dark-factory/tests/test_budget_enforce.py` | Modify | Update `DEFAULT_CONFIG` + assertions in Tests 12, 13, 14, 24 |
| `dark-factory/scripts/budget_enforce.py` | Modify | Update `_HARDCODED` to 5000/2500 |
| `.claude/skills/refinement/config.yaml` | Modify | Raise `architecture.max_tokens`/`min_tokens` |
| `dark-factory/evals/reports/budget-calibration-scorecard-*.md` | Create (generated) | New scorecard from calibration run |
| `dark-factory/evals/results/*.json` | Create (generated) | Raw calibration JSON |

---

### Task 1: Update DEFAULT_CONFIG and test assertions (Tests 12, 13, 14)

**Files:**
- Modify: `dark-factory/tests/test_budget_enforce.py`

**What and why:** `DEFAULT_CONFIG` in the test file mirrors the cap values and is the config object passed to `derive_caps` in Tests 12–14. Updating it to the new values and correcting the sum-of-defaults/sum-of-floors comments and assertions brings the tests in sync with the new cap before touching the implementation.

- [ ] Run the existing test suite to confirm a clean baseline:
  ```bash
  cd /workspace/markethawk
  python -m pytest dark-factory/tests/test_budget_enforce.py -q
  ```
  Expected: all tests pass (green baseline).

- [ ] Update `DEFAULT_CONFIG` at lines 18–19 of `dark-factory/tests/test_budget_enforce.py`:
  ```python
  # old
  "architecture": {"max_tokens": 3000, "min_tokens": 1500},
  # new
  "architecture": {"max_tokens": 5000, "min_tokens": 2500},
  ```

- [ ] Run the test suite immediately after changing `DEFAULT_CONFIG` — Tests 12, 13, 14 should fail because the assertions still expect old cap values:
  ```bash
  python -m pytest dark-factory/tests/test_budget_enforce.py -q -k "test_proportional"
  ```
  Expected: 3 failures (`test_proportional_distribution_normal`, `test_proportional_distribution_floor_clamp`, `test_proportional_distribution_default_clamp`).

- [ ] Fix **Test 12** (`test_proportional_distribution_normal`, lines 159–174):
  ```python
  # old comment + assertion
  # Sum of defaults = 3000 + 1500 + 2000 + 6000 = 12500
  assert result.derived_caps.get("architecture_md") == 3000

  # new comment + assertion
  # Sum of defaults = 5000 + 1500 + 2000 + 6000 = 14500
  assert result.derived_caps.get("architecture_md") == 5000
  ```

- [ ] Fix **Test 13** (`test_proportional_distribution_floor_clamp`, lines 177–192):
  ```python
  # old comment + assertion
  # budget=3000, reserve=2000, allowance=1000 (much less than sum of floors=6250)
  assert result.derived_caps.get("architecture_md") == 1500

  # new comment + assertion
  # budget=3000, reserve=2000, allowance=1000 (much less than sum of floors=7250)
  assert result.derived_caps.get("architecture_md") == 2500
  ```
  Floor sum arithmetic: arch(2500) + memory(750) + comments(1000) + diff(3000) = **7,250**.

- [ ] Fix **Test 14** (`test_proportional_distribution_default_clamp`, lines 195–209):
  ```python
  # old comment + assertion
  # budget=200000, reserve=2000 (floor), allowance=198000 >> 12500 (sum of defaults)
  assert result.derived_caps.get("architecture_md") == 3000

  # new comment + assertion
  # budget=200000, reserve=2000 (floor), allowance=198000 >> 14500 (sum of defaults)
  assert result.derived_caps.get("architecture_md") == 5000
  ```

- [ ] Verify Tests 12, 13, 14 are now green:
  ```bash
  python -m pytest dark-factory/tests/test_budget_enforce.py -q -k "test_proportional"
  ```
  Expected: 3 tests pass.

- [ ] Commit:
  ```bash
  git add dark-factory/tests/test_budget_enforce.py
  git commit -m "test(#731): update DEFAULT_CONFIG to 5000/2500 + fix Tests 12/13/14 assertions"
  ```

---

### Task 2: Update Test 24 assertion and _HARDCODED in budget_enforce.py

**Files:**
- Modify: `dark-factory/tests/test_budget_enforce.py` (Test 24 assertions)
- Modify: `dark-factory/scripts/budget_enforce.py` (`_HARDCODED`)

**What and why:** `_HARDCODED` in `budget_enforce.py` is the fallback when config is missing/invalid. Test 24 (`test_missing_config_uses_hardcoded_defaults`) calls `_load_config("/nonexistent/path/config.yaml")` and asserts the returned dict contains the hardcoded defaults. Updating the test first (to expect 5000/2500) creates a failing test; updating `_HARDCODED` makes it pass.

- [ ] Update Test 24 assertions at lines 379–380 of `dark-factory/tests/test_budget_enforce.py`:
  ```python
  # old
  assert config["token_optimization"]["architecture"]["max_tokens"] == 3000
  assert config["token_optimization"]["architecture"]["min_tokens"] == 1500

  # new
  assert config["token_optimization"]["architecture"]["max_tokens"] == 5000
  assert config["token_optimization"]["architecture"]["min_tokens"] == 2500
  ```

- [ ] Verify Test 24 is now red:
  ```bash
  python -m pytest dark-factory/tests/test_budget_enforce.py::test_missing_config_uses_hardcoded_defaults -v
  ```
  Expected: FAILED (returns 3000 from `_HARDCODED` but test now expects 5000).

- [ ] Update `_HARDCODED` in `dark-factory/scripts/budget_enforce.py` at line 30:
  ```python
  # old (line 30)
  "architecture": {"max_tokens": 3000, "min_tokens": 1500},

  # new
  "architecture": {"max_tokens": 5000, "min_tokens": 2500},
  ```

- [ ] Verify Test 24 is now green and the full suite still passes:
  ```bash
  python -m pytest dark-factory/tests/test_budget_enforce.py -q
  ```
  Expected: all tests pass.

- [ ] Commit:
  ```bash
  git add dark-factory/tests/test_budget_enforce.py dark-factory/scripts/budget_enforce.py
  git commit -m "fix(#731): raise _HARDCODED arch cap to 5000/2500 + update Test 24 assertion"
  ```

---

### Task 3: Update config.yaml architecture cap values

**Files:**
- Modify: `.claude/skills/refinement/config.yaml`

**What and why:** `config.yaml` is the runtime source of truth for `budget_enforce.py`. It's loaded by `_load_config` on every factory run. Updating it here is what actually fixes `derive_caps` clamping in production. The `_HARDCODED` fallback (Task 2) and the test-local `DEFAULT_CONFIG` (Task 1) must stay in lockstep with this value.

- [ ] Update `.claude/skills/refinement/config.yaml` lines 126–127:
  ```yaml
  # old
  max_tokens: 3000          # token ceiling for architecture context per scenario (baked — no env override)
  min_tokens: 1500          # floor for budget_enforce.py proportional distribution (50% of max_tokens)

  # new
  max_tokens: 5000          # token ceiling for architecture context per scenario (baked — no env override)
  min_tokens: 2500          # floor for budget_enforce.py proportional distribution (50% of max_tokens)
  ```

- [ ] Verify the config parses correctly and `_load_config` returns the new values:
  ```bash
  python3 -c "
  import sys; sys.path.insert(0, 'dark-factory/scripts')
  import budget_enforce as be
  cfg = be._load_config('.claude/skills/refinement/config.yaml')
  arch = cfg['token_optimization']['architecture']
  assert arch['max_tokens'] == 5000, f'Expected 5000, got {arch[\"max_tokens\"]}'
  assert arch['min_tokens'] == 2500, f'Expected 2500, got {arch[\"min_tokens\"]}'
  print('config.yaml: max=5000 min=2500 ✓')
  "
  ```
  Expected output: `config.yaml: max=5000 min=2500 ✓`

- [ ] Run the full test suite one final time to confirm nothing regressed:
  ```bash
  python -m pytest dark-factory/tests/test_budget_enforce.py -q
  ```
  Expected: all tests pass.

- [ ] Commit:
  ```bash
  git add .claude/skills/refinement/config.yaml
  git commit -m "fix(#731): raise config.yaml architecture.max_tokens to 5000 (p90=4645 + 7.6% headroom)"
  ```

---

### Task 4: Run calibration and commit scorecard

**Files:**
- Create (generated): `dark-factory/evals/reports/budget-calibration-scorecard-<date>.md`
- Create (generated): `dark-factory/evals/results/calibration-<date>.json` (or similar)

**What and why:** The scorecard is the acceptance gate. After the cap raise, `derive_caps` will no longer clamp arch at 3,000, so any issue whose arch slice was between 3,001–5,000 tokens will move from `section_at_risk` to within-cap. The calibration must confirm `section_at_risk_rate == 0%` and `over_budget_rate <= 10%` for refine/plan at 30k.

- [ ] Run the calibration (full corpus, no `--issues` filter) inside the factory container:
  ```bash
  python3 dark-factory/evals/token_opt_eval.py --calibrate
  ```
  Expected: script runs to completion and writes a new scorecard file to `dark-factory/evals/reports/` and raw JSON to `dark-factory/evals/results/`.

- [ ] Verify the scorecard acceptance criteria for refine and plan at their 30,000-token budgets:
  ```bash
  grep -A 5 "refine\|plan" dark-factory/evals/reports/budget-calibration-scorecard-*.md | grep "section_at_risk\|over_budget"
  ```
  Required values:
  - `section_at_risk_rate: 0%` for refine at 30k
  - `section_at_risk_rate: 0%` for plan at 30k
  - `over_budget_rate: <= 10%` for both

  If `section_at_risk_rate` is non-zero after the cap raise: investigate whether any corpus issue has an arch slice above 5,000 tokens before accepting the result. Do not proceed to commit if the gate fails.

- [ ] Stage and commit the generated artifacts:
  ```bash
  git add dark-factory/evals/reports/ dark-factory/evals/results/
  git commit -m "eval(#731): recalibration scorecard — section_at_risk 0% refine/plan at 30k"
  ```

- [ ] Final sanity check — confirm `enforce` flags were not touched:
  ```bash
  grep -A 6 "enforce:" .claude/skills/refinement/config.yaml
  ```
  Expected: `refine: false`, `plan: false` (unchanged from before).
