# Implementation Plan: Phase 4 T1 — budget_enforce.py per-scenario budget derivation

**Goal:** Implement `dark-factory/scripts/budget_enforce.py` — a pure-stdlib module that computes per-scenario token budget allocations from a context-budget.json input. Distributes allowance (budget minus reserved) proportionally across optimizable sections, clamped to configurable floors/defaults. Two modes: observe (pure return value) and enforce (also prints sourceable `KEY=VALUE` env lines to stdout). Unit tests only; no DAG wiring.

**Issue:** #714  
**Epic:** #713 (Dark Factory token optimization Phase 4)  
**Spec:** `docs/superpowers/specs/2026-07-02-token-opt-phase4-enforcement-design.md`

## Architecture

```
dark-factory/scripts/budget_enforce.py   — pure-stdlib module (new)
dark-factory/tests/test_budget_enforce.py — pytest unit tests (new)
.claude/skills/refinement/config.yaml    — add min_tokens / min_review_tokens floors + issue_context (edit)
```

All three files live inside the Dark Factory boundary. No app-code changes.

**Data flow:**

```
context-budget.json (written by context_budget.py)
        │
        ▼
budget_enforce.py: derive_caps()
  ├─ Reserved set: claude_md (always) + architecture_md (if fallback) + issue_context (floor)
  ├─ Allowance = max(0, budget - reserved)
  └─ Optimizable: arch/memory/comments/diff (present, not reserved) → proportional + clamp
        │
  observe mode ─── returns BudgetResult (no stdout)
  enforce mode ─── KEY=VALUE lines → stdout; status → stderr
```

## Tech Stack

- Python 3 (stdlib only for `derive_caps()`; `yaml` lazy-imported only in `_load_config` for CLI)
- pytest — same pattern as `test_context_budget.py` and `test_diff_rank.py`
- `token_estimate.py` imported for reference (floor table mirrors 4 × `CHARS_PER_TOKEN` approach)

## File Structure

| File | Status | Role |
|---|---|---|
| `.claude/skills/refinement/config.yaml` | Edit | Add floor keys and `issue_context` sub-block |
| `dark-factory/scripts/budget_enforce.py` | New | `BudgetResult`, `derive_caps()`, CLI |
| `dark-factory/tests/test_budget_enforce.py` | New | All unit tests from spec |

---

## Task 1: Add floor keys to config.yaml

**Files:** `.claude/skills/refinement/config.yaml`

### Steps

**1a. Read current token_optimization block**

```bash
grep -n "token_optimization" .claude/skills/refinement/config.yaml
# Expected: lines 105–132 show architecture/memory/comments/diff sub-blocks
```

**1b. Add `issue_context.reserve_tokens`, and `min_tokens`/`min_review_tokens` floor keys**

Edit `.claude/skills/refinement/config.yaml`. Under the existing `token_optimization:` block, make the following additions (new lines marked with `# ADD`):

```yaml
token_optimization:
  enabled: true
  enforce_budgets: false
  default_budget_tokens: 24000
  issue_context:                          # ADD — new sub-block
    reserve_tokens: 2000                  # ADD — minimum tokens reserved for issue body
  architecture:
    enabled: true
    mode: slice
    max_tokens: 3000
    min_tokens: 1500                      # ADD — floor when distributing allowance
  memory:
    enabled: true
    mode: top_k
    max_entries: 8
    max_tokens: 1500
    min_tokens: 750                       # ADD — floor when distributing allowance
  comments:
    enabled: true
    digest_after_factory_marker: true
    max_tokens: 2000
    min_tokens: 1000                      # ADD — floor when distributing allowance
  diff:
    enabled: true
    max_review_tokens: 6000
    min_review_tokens: 3000               # ADD — floor when distributing allowance (note: _review_ suffix matches max_review_tokens)
  escalation:
    ...  # unchanged
```

**1c. Verify structure is valid YAML**

```bash
python3 -c "import yaml; yaml.safe_load(open('.claude/skills/refinement/config.yaml')); print('OK')"
# Expected output: OK
```

**1d. Commit**

```bash
git add .claude/skills/refinement/config.yaml
git commit -m "config: add token_optimization floor keys and issue_context.reserve_tokens for #714"
# Expected: 1 file changed, ~5 insertions
```

---

## Task 2: Write failing unit tests

**Files:** `dark-factory/tests/test_budget_enforce.py`

### Steps

**2a. Create test file**

Create `dark-factory/tests/test_budget_enforce.py`:

```python
"""Tests for dark-factory/scripts/budget_enforce.py."""
from __future__ import annotations

import io
import json
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import budget_enforce as be


# ── helpers ───────────────────────────────────────────────────────────────────

def make_config(
    arch_max=3000, arch_min=1500,
    mem_max=1500, mem_min=750,
    comm_max=2000, comm_min=1000,
    diff_max=6000, diff_min=3000,
    issue_context_reserve=2000,
):
    return {
        "token_optimization": {
            "issue_context": {"reserve_tokens": issue_context_reserve},
            "architecture": {"max_tokens": arch_max, "min_tokens": arch_min},
            "memory": {"max_tokens": mem_max, "min_tokens": mem_min},
            "comments": {"max_tokens": comm_max, "min_tokens": comm_min},
            "diff": {"max_review_tokens": diff_max, "min_review_tokens": diff_min},
        }
    }


def make_sections(
    claude_md_tokens=18000,
    arch_tokens=3000,
    arch_fallback=False,
    memory_tokens=1200,
    comments_tokens=800,
    diff_tokens=4000,
    issue_context_tokens=1800,
    include_diff=True,
):
    sections = {
        "claude_md": {"tokens": claude_md_tokens},
        "architecture_md": {"tokens": arch_tokens, "fallback": arch_fallback},
        "memory_context": {"tokens": memory_tokens},
        "comments": {"tokens": comments_tokens},
        "issue_context": {"tokens": issue_context_tokens},
    }
    if include_diff:
        sections["diff"] = {"tokens": diff_tokens}
    return sections


def run_main(context_budget_data, budget_tokens, mode, config_data=None):
    """Invoke be.main() in-process; return captured stdout string."""
    if config_data is None:
        config_data = make_config()
    with tempfile.TemporaryDirectory() as d:
        cb_path = Path(d) / "context-budget.json"
        cb_path.write_text(json.dumps(context_budget_data))
        cfg_path = Path(d) / "config.yaml"
        cfg_path.write_text(yaml.dump(config_data))

        argv = [
            "budget_enforce.py",
            "--context-budget-json", str(cb_path),
            "--budget-tokens", str(budget_tokens),
            "--mode", mode,
            "--config", str(cfg_path),
        ]
        buf = io.StringIO()
        with patch("sys.argv", argv), patch("sys.stdout", buf):
            be.main()
        return buf.getvalue()


# ── reserved breakdown ────────────────────────────────────────────────────────

def test_claude_md_always_reserved():
    cfg = make_config()
    sections = make_sections(claude_md_tokens=18000, arch_fallback=False)
    result = be.derive_caps(sections, budget=30000, arch_fallback=False, config=cfg)
    assert "claude_md" in result.reserved_breakdown
    assert result.reserved_breakdown["claude_md"] == 18000


def test_arch_reserved_when_fallback_true():
    cfg = make_config()
    sections = make_sections(arch_tokens=4500, arch_fallback=True)
    result = be.derive_caps(sections, budget=30000, arch_fallback=True, config=cfg)
    assert "architecture_md" in result.reserved_breakdown
    assert result.reserved_breakdown["architecture_md"] == 4500
    assert "architecture_md" not in result.derived_caps


def test_arch_not_reserved_when_fallback_false():
    cfg = make_config()
    sections = make_sections(arch_fallback=False)
    result = be.derive_caps(sections, budget=30000, arch_fallback=False, config=cfg)
    assert "architecture_md" not in result.reserved_breakdown
    assert "architecture_md" in result.derived_caps


def test_issue_context_reserved_at_floor_when_below_floor():
    cfg = make_config(issue_context_reserve=2000)
    sections = make_sections(issue_context_tokens=1000)  # below floor
    result = be.derive_caps(sections, budget=30000, arch_fallback=False, config=cfg)
    assert result.reserved_breakdown["issue_context"] == 2000  # floor applied


def test_issue_context_reserved_at_actual_when_above_floor():
    cfg = make_config(issue_context_reserve=2000)
    sections = make_sections(issue_context_tokens=3500)  # above floor
    result = be.derive_caps(sections, budget=30000, arch_fallback=False, config=cfg)
    assert result.reserved_breakdown["issue_context"] == 3500  # actual used


# ── allowance and over_budget ─────────────────────────────────────────────────

def test_allowance_equals_budget_minus_reserved():
    cfg = make_config()
    # claude_md=18000, issue_context=max(1800, 2000)=2000 → reserved=20000
    sections = make_sections(claude_md_tokens=18000, arch_fallback=False,
                              issue_context_tokens=1800)
    result = be.derive_caps(sections, budget=30000, arch_fallback=False, config=cfg)
    expected_reserved = 18000 + 2000  # claude_md + issue_context floor
    assert result.reserved_tokens == expected_reserved
    assert result.allowance_tokens == 30000 - expected_reserved


def test_over_budget_false_when_budget_exceeds_reserved():
    cfg = make_config()
    sections = make_sections(claude_md_tokens=18000, issue_context_tokens=1800,
                              arch_fallback=False)
    result = be.derive_caps(sections, budget=30000, arch_fallback=False, config=cfg)
    assert result.over_budget is False


def test_over_budget_true_when_reserved_exceeds_budget():
    cfg = make_config()
    # claude_md=28000, issue_context=max(5000,2000)=5000 → reserved=33000 > 30000
    sections = make_sections(claude_md_tokens=28000, issue_context_tokens=5000,
                              arch_fallback=False)
    result = be.derive_caps(sections, budget=30000, arch_fallback=False, config=cfg)
    assert result.over_budget is True
    assert result.allowance_tokens == 0


def test_allowance_is_zero_when_over_budget():
    cfg = make_config()
    sections = make_sections(claude_md_tokens=28000, issue_context_tokens=5000,
                              arch_fallback=False)
    result = be.derive_caps(sections, budget=30000, arch_fallback=False, config=cfg)
    assert result.allowance_tokens == 0


# ── proportional distribution ─────────────────────────────────────────────────

def test_derived_caps_within_floor_and_default():
    cfg = make_config()
    sections = make_sections(claude_md_tokens=18000, arch_fallback=False,
                              issue_context_tokens=1800)
    result = be.derive_caps(sections, budget=30000, arch_fallback=False, config=cfg)
    floors = {"architecture_md": 1500, "memory_context": 750, "comments": 1000, "diff": 3000}
    defaults = {"architecture_md": 3000, "memory_context": 1500, "comments": 2000, "diff": 6000}
    for sec, cap in result.derived_caps.items():
        assert floors[sec] <= cap <= defaults[sec], (
            f"{sec}: cap={cap} not in [{floors[sec]}, {defaults[sec]}]"
        )


def test_floor_enforcement_when_allowance_very_small():
    cfg = make_config()
    # reserved = 25000 + max(4000, 2000) = 29000, allowance = 1000 < sum_floors(6250)
    sections = make_sections(claude_md_tokens=25000, issue_context_tokens=4000,
                              arch_fallback=False)
    result = be.derive_caps(sections, budget=30000, arch_fallback=False, config=cfg)
    floors = {"architecture_md": 1500, "memory_context": 750, "comments": 1000, "diff": 3000}
    for sec, cap in result.derived_caps.items():
        assert cap == floors[sec], f"{sec}: expected floor {floors[sec]}, got {cap}"


def test_over_budget_sections_all_get_floor():
    cfg = make_config()
    sections = make_sections(claude_md_tokens=28000, issue_context_tokens=5000,
                              arch_fallback=False)
    result = be.derive_caps(sections, budget=30000, arch_fallback=False, config=cfg)
    floors = {"architecture_md": 1500, "memory_context": 750, "comments": 1000, "diff": 3000}
    for sec, cap in result.derived_caps.items():
        assert cap == floors[sec], f"{sec}: expected floor {floors[sec]}, got {cap}"


# ── absent sections skipped ───────────────────────────────────────────────────

def test_absent_diff_not_in_optimizable():
    cfg = make_config()
    sections = make_sections(include_diff=False)  # diff absent (refine scenario)
    result = be.derive_caps(sections, budget=30000, arch_fallback=False, config=cfg)
    assert "diff" not in result.derived_caps
    assert "diff" not in result.optimizable_sections


def test_absent_diff_remaining_sections_get_caps():
    cfg = make_config()
    sections = make_sections(include_diff=False)
    result = be.derive_caps(sections, budget=30000, arch_fallback=False, config=cfg)
    assert set(result.derived_caps.keys()) == {"architecture_md", "memory_context", "comments"}


# ── observe mode (pure function, no stdout) ───────────────────────────────────

def test_observe_mode_returns_budget_result(capsys):
    cfg = make_config()
    sections = make_sections()
    result = be.derive_caps(sections, budget=30000, arch_fallback=False, config=cfg)
    captured = capsys.readouterr()
    assert captured.out == ""
    assert isinstance(result, be.BudgetResult)


def test_observe_mode_cli_no_stdout():
    sections = make_sections(claude_md_tokens=18000, arch_fallback=False,
                              issue_context_tokens=1800)
    cb_data = {"scenario": "implement", "sections": sections}
    output = run_main(cb_data, budget_tokens=30000, mode="observe")
    assert output == ""


# ── enforce mode (stdout KEY=VALUE lines) ────────────────────────────────────

def test_enforce_mode_emits_all_four_env_lines():
    sections = make_sections(claude_md_tokens=18000, arch_fallback=False,
                              issue_context_tokens=1800)
    cb_data = {"scenario": "implement", "sections": sections}
    output = run_main(cb_data, budget_tokens=30000, mode="enforce")
    assert "TOKEN_OPTIMIZATION_ARCHITECTURE_MAX_TOKENS=" in output
    assert "TOKEN_OPTIMIZATION_MEMORY_MAX_TOKENS=" in output
    assert "TOKEN_OPTIMIZATION_COMMENTS_MAX_TOKENS=" in output
    assert "TOKEN_OPTIMIZATION_DIFF_MAX_REVIEW_TOKENS=" in output


def test_enforce_mode_values_are_integers():
    sections = make_sections(claude_md_tokens=18000, arch_fallback=False,
                              issue_context_tokens=1800)
    cb_data = {"scenario": "implement", "sections": sections}
    output = run_main(cb_data, budget_tokens=30000, mode="enforce")
    for line in output.strip().splitlines():
        key, _, val = line.partition("=")
        assert val.isdigit(), f"Non-integer value for {key}: {val!r}"


def test_enforce_mode_absent_diff_not_in_stdout():
    sections = make_sections(claude_md_tokens=18000, arch_fallback=False,
                              issue_context_tokens=1800, include_diff=False)
    cb_data = {"scenario": "refine", "sections": sections}
    output = run_main(cb_data, budget_tokens=30000, mode="enforce")
    assert "TOKEN_OPTIMIZATION_DIFF_MAX_REVIEW_TOKENS" not in output


def test_enforce_mode_arch_in_fallback_not_in_stdout():
    sections = make_sections(claude_md_tokens=18000, arch_fallback=True,
                              arch_tokens=4000, issue_context_tokens=1800)
    cb_data = {"scenario": "implement", "sections": sections}
    output = run_main(cb_data, budget_tokens=30000, mode="enforce")
    assert "TOKEN_OPTIMIZATION_ARCHITECTURE_MAX_TOKENS" not in output


def test_over_budget_enforce_emits_floor_values():
    sections = make_sections(claude_md_tokens=28000, arch_fallback=False,
                              issue_context_tokens=5000)
    cb_data = {"scenario": "implement", "sections": sections}
    output = run_main(cb_data, budget_tokens=30000, mode="enforce")
    assert "TOKEN_OPTIMIZATION_ARCHITECTURE_MAX_TOKENS=1500" in output
    assert "TOKEN_OPTIMIZATION_MEMORY_MAX_TOKENS=750" in output
    assert "TOKEN_OPTIMIZATION_COMMENTS_MAX_TOKENS=1000" in output
    assert "TOKEN_OPTIMIZATION_DIFF_MAX_REVIEW_TOKENS=3000" in output


# ── config-driven floors ──────────────────────────────────────────────────────

def test_config_driven_floors_applied():
    cfg = make_config(arch_min=2000, mem_min=1000, comm_min=1500, diff_min=4000)
    # allowance ~1000 → all sections clamped to their (custom) floors
    sections = make_sections(claude_md_tokens=25000, issue_context_tokens=4000,
                              arch_fallback=False)
    result = be.derive_caps(sections, budget=30000, arch_fallback=False, config=cfg)
    assert result.derived_caps.get("architecture_md") == 2000
    assert result.derived_caps.get("memory_context") == 1000
    assert result.derived_caps.get("comments") == 1500
    assert result.derived_caps.get("diff") == 4000


def test_missing_floor_keys_fall_back_to_hardcoded():
    cfg = {
        "token_optimization": {
            "issue_context": {"reserve_tokens": 2000},
            "architecture": {"max_tokens": 3000},
            "memory": {"max_tokens": 1500},
            "comments": {"max_tokens": 2000},
            "diff": {"max_review_tokens": 6000},
        }
    }
    sections = make_sections(claude_md_tokens=25000, issue_context_tokens=4000,
                              arch_fallback=False)
    result = be.derive_caps(sections, budget=30000, arch_fallback=False, config=cfg)
    # Must not crash; floors default to hardcoded 1500/750/1000/3000
    assert result.derived_caps.get("architecture_md") >= 1500
    assert result.derived_caps.get("memory_context") >= 750
    assert result.derived_caps.get("comments") >= 1000
    assert result.derived_caps.get("diff") >= 3000
```

**2b. Verify tests fail (module not yet created)**

```bash
cd /workspace/markethawk
python -m pytest dark-factory/tests/test_budget_enforce.py -x 2>&1 | head -20
# Expected: ModuleNotFoundError: No module named 'budget_enforce'
```

**2c. Commit failing tests**

```bash
git add dark-factory/tests/test_budget_enforce.py
git commit -m "test(budget_enforce): write failing unit tests for #714 T1"
# Expected: 1 file changed, ~200 insertions
```

---

## Task 3: Implement `budget_enforce.py`

**Files:** `dark-factory/scripts/budget_enforce.py`

### Steps

**3a. Create the module**

Create `dark-factory/scripts/budget_enforce.py`:

```python
"""Per-scenario token budget derivation for Dark Factory context budget enforcement.

Pure-stdlib module: no external dependencies beyond the standard library.
derive_caps() is a side-effect-free pure function; only _load_config() uses yaml
(lazy-imported so the module is importable without PyYAML for unit tests that
pass config dicts directly).

Usage (CLI):
  python3 budget_enforce.py \
    --context-budget-json /path/to/context-budget.json \
    --budget-tokens 30000 \
    --mode observe|enforce \
    [--config /path/to/config.yaml]
"""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, field

# ── Section constants ─────────────────────────────────────────────────────────

OPTIMIZABLE_SECTIONS = ["architecture_md", "memory_context", "comments", "diff"]

ENV_VAR_NAMES: dict[str, str] = {
    "architecture_md": "TOKEN_OPTIMIZATION_ARCHITECTURE_MAX_TOKENS",
    "memory_context":  "TOKEN_OPTIMIZATION_MEMORY_MAX_TOKENS",
    "comments":        "TOKEN_OPTIMIZATION_COMMENTS_MAX_TOKENS",
    "diff":            "TOKEN_OPTIMIZATION_DIFF_MAX_REVIEW_TOKENS",
}

# Hardcoded fallbacks used when config keys are absent (fail-open, no crash)
_DEFAULT_CAPS: dict[str, int] = {
    "architecture_md": 3000,
    "memory_context":  1500,
    "comments":        2000,
    "diff":            6000,
}
_DEFAULT_FLOORS: dict[str, int] = {
    "architecture_md": 1500,
    "memory_context":  750,
    "comments":        1000,
    "diff":            3000,
}
_DEFAULT_ISSUE_CONTEXT_FLOOR = 2000


# ── Result dataclass ──────────────────────────────────────────────────────────

@dataclass
class BudgetResult:
    scenario: str
    budget_tokens: int
    reserved_tokens: int
    allowance_tokens: int
    over_budget: bool
    reserved_breakdown: dict[str, int] = field(default_factory=dict)
    derived_caps: dict[str, int] = field(default_factory=dict)
    optimizable_sections: list[str] = field(default_factory=list)


# ── Config helpers ────────────────────────────────────────────────────────────

def _load_config(path: str | None) -> dict:
    """Load config.yaml. yaml is lazy-imported; returns {} on any error."""
    if not path:
        return {}
    try:
        import yaml  # noqa: PLC0415
        with open(path, encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    except Exception:  # noqa: BLE001
        return {}


def _read_caps_and_floors(config: dict) -> tuple[dict[str, int], dict[str, int], int]:
    """Extract per-section cap/floor values and issue_context floor from config."""
    tok = config.get("token_optimization", {})

    arch = tok.get("architecture", {})
    mem  = tok.get("memory", {})
    comm = tok.get("comments", {})
    diff = tok.get("diff", {})

    caps: dict[str, int] = {
        "architecture_md": arch.get("max_tokens",       _DEFAULT_CAPS["architecture_md"]),
        "memory_context":  mem.get("max_tokens",        _DEFAULT_CAPS["memory_context"]),
        "comments":        comm.get("max_tokens",       _DEFAULT_CAPS["comments"]),
        "diff":            diff.get("max_review_tokens", _DEFAULT_CAPS["diff"]),
    }
    floors: dict[str, int] = {
        "architecture_md": arch.get("min_tokens",        _DEFAULT_FLOORS["architecture_md"]),
        "memory_context":  mem.get("min_tokens",         _DEFAULT_FLOORS["memory_context"]),
        "comments":        comm.get("min_tokens",        _DEFAULT_FLOORS["comments"]),
        "diff":            diff.get("min_review_tokens", _DEFAULT_FLOORS["diff"]),
    }
    issue_floor = (
        tok.get("issue_context", {}).get("reserve_tokens", _DEFAULT_ISSUE_CONTEXT_FLOOR)
    )
    return caps, floors, issue_floor


# ── Core pure function ────────────────────────────────────────────────────────

def derive_caps(
    sections: dict,
    budget: int,
    arch_fallback: bool,
    config: dict,
    scenario: str = "unknown",
) -> BudgetResult:
    """Compute per-scenario derived token caps.

    Args:
        sections:     dict from context-budget.json "sections" field
        budget:       per-scenario budget in tokens
        arch_fallback: True when architecture_md is in full-doc safety fallback
        config:       parsed config dict (or full config.yaml contents)
        scenario:     scenario name for BudgetResult metadata

    Returns:
        BudgetResult — pure; no stdout/stderr side effects
    """
    caps, floors, issue_context_floor = _read_caps_and_floors(config)

    # ── Reserved set ─────────────────────────────────────────────────────────
    reserved_breakdown: dict[str, int] = {}

    reserved_breakdown["claude_md"] = sections.get("claude_md", {}).get("tokens", 0)

    if arch_fallback:
        reserved_breakdown["architecture_md"] = (
            sections.get("architecture_md", {}).get("tokens", 0)
        )

    actual_issue = sections.get("issue_context", {}).get("tokens", 0)
    reserved_breakdown["issue_context"] = max(actual_issue, issue_context_floor)

    reserved_total = sum(reserved_breakdown.values())
    over_budget = reserved_total >= budget
    allowance = 0 if over_budget else budget - reserved_total

    # ── Optimizable set ───────────────────────────────────────────────────────
    optimizable = [
        s for s in OPTIMIZABLE_SECTIONS
        if s in sections and s not in reserved_breakdown
    ]

    # ── Proportional distribution with floor/cap clamping ────────────────────
    derived: dict[str, int] = {}
    total_default = sum(caps[s] for s in optimizable)

    for s in optimizable:
        if over_budget or allowance == 0 or total_default == 0:
            derived[s] = floors[s]
        else:
            raw = allowance * (caps[s] / total_default)
            derived[s] = max(floors[s], min(int(raw), caps[s]))

    return BudgetResult(
        scenario=scenario,
        budget_tokens=budget,
        reserved_tokens=reserved_total,
        allowance_tokens=allowance,
        over_budget=over_budget,
        reserved_breakdown=reserved_breakdown,
        derived_caps=derived,
        optimizable_sections=optimizable,
    )


# ── CLI ────────────────────────────────────────────────────────────────────────

def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Compute per-scenario token budget derivation."
    )
    p.add_argument(
        "--context-budget-json",
        required=True,
        help="Path to context-budget.json written by context_budget.py",
    )
    p.add_argument(
        "--budget-tokens",
        type=int,
        default=30000,
        help="Per-scenario token budget (default: 30000)",
    )
    p.add_argument(
        "--mode",
        choices=["observe", "enforce"],
        default="observe",
        help="observe = compute only; enforce = print KEY=VALUE env lines to stdout",
    )
    p.add_argument(
        "--config",
        default=".claude/skills/refinement/config.yaml",
        help="Path to refinement config.yaml",
    )
    return p.parse_args()


def main() -> None:
    args = parse_args()

    with open(args.context_budget_json, encoding="utf-8") as f:
        cb_data = json.load(f)

    sections = cb_data.get("sections", {})
    scenario = cb_data.get("scenario", "unknown")
    arch_fallback = sections.get("architecture_md", {}).get("fallback", False)

    config = _load_config(args.config)
    result = derive_caps(sections, args.budget_tokens, arch_fallback, config, scenario)

    print(
        f"budget_enforce: scenario={result.scenario} "
        f"budget={result.budget_tokens} "
        f"reserved={result.reserved_tokens} "
        f"allowance={result.allowance_tokens} "
        f"over_budget={result.over_budget} "
        f"optimizable={result.optimizable_sections}",
        file=sys.stderr,
    )

    if args.mode == "enforce":
        for sec in result.optimizable_sections:
            sys.stdout.write(f"{ENV_VAR_NAMES[sec]}={result.derived_caps[sec]}\n")


if __name__ == "__main__":
    try:
        main()
    except (FileNotFoundError, KeyError, json.JSONDecodeError) as exc:
        print(f"budget_enforce: error: {exc}", file=sys.stderr)
        sys.exit(1)
```

**3b. Run tests — all should pass**

```bash
cd /workspace/markethawk
python -m pytest dark-factory/tests/test_budget_enforce.py -v 2>&1
# Expected output (all green):
# test_claude_md_always_reserved PASSED
# test_arch_reserved_when_fallback_true PASSED
# test_arch_not_reserved_when_fallback_false PASSED
# test_issue_context_reserved_at_floor_when_below_floor PASSED
# test_issue_context_reserved_at_actual_when_above_floor PASSED
# test_allowance_equals_budget_minus_reserved PASSED
# test_over_budget_false_when_budget_exceeds_reserved PASSED
# test_over_budget_true_when_reserved_exceeds_budget PASSED
# test_allowance_is_zero_when_over_budget PASSED
# test_derived_caps_within_floor_and_default PASSED
# test_floor_enforcement_when_allowance_very_small PASSED
# test_over_budget_sections_all_get_floor PASSED
# test_absent_diff_not_in_optimizable PASSED
# test_absent_diff_remaining_sections_get_caps PASSED
# test_observe_mode_returns_budget_result PASSED
# test_observe_mode_cli_no_stdout PASSED
# test_enforce_mode_emits_all_four_env_lines PASSED
# test_enforce_mode_values_are_integers PASSED
# test_enforce_mode_absent_diff_not_in_stdout PASSED
# test_enforce_mode_arch_in_fallback_not_in_stdout PASSED
# test_over_budget_enforce_emits_floor_values PASSED
# test_config_driven_floors_applied PASSED
# test_missing_floor_keys_fall_back_to_hardcoded PASSED
# 23 passed in X.XXs
```

**3c. Confirm no regressions in related tests**

```bash
python -m pytest dark-factory/tests/test_token_estimate.py dark-factory/tests/test_context_budget.py -v 2>&1 | tail -5
# Expected: all passed
```

**3d. Commit**

```bash
git add dark-factory/scripts/budget_enforce.py
git commit -m "feat(budget_enforce): implement per-scenario budget derivation for #714 T1"
# Expected: 1 file changed, ~120 insertions
```

---

## Commit sequence summary

| # | Files | Message |
|---|---|---|
| 1 | `.claude/skills/refinement/config.yaml` | `config: add token_optimization floor keys and issue_context.reserve_tokens for #714` |
| 2 | `dark-factory/tests/test_budget_enforce.py` | `test(budget_enforce): write failing unit tests for #714 T1` |
| 3 | `dark-factory/scripts/budget_enforce.py` | `feat(budget_enforce): implement per-scenario budget derivation for #714 T1` |

## Key design decisions captured from spec

- **arch_fallback read from JSON**: `sections.architecture_md.fallback` (already written by `context_budget.py`) — no duplicate filesystem work
- **Observe mode = no stdout**: `derive_caps()` is pure; enforce mode uses `sys.stdout.write()` for clean capsys testing
- **Floor clamping applies when over_budget**: enforcement proceeds (informational only); sections still get floor values — fail-open is a T3 concern
- **Absent sections skipped**: `diff` absent in `refine` scenario → not in `optimizable_sections`, not in `derived_caps`, not in enforce stdout
- **yaml lazy-imported**: module is importable without PyYAML; only CLI path through `_load_config()` needs it
- **issue_context floor**: fixed 2000 tokens (config-driven); `max(actual, floor)` so a large issue body isn't shrunk
