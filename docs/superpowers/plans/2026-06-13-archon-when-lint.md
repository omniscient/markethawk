# Plan: CI lint for Archon `when:` expressions — Issue #403

Date: 2026-06-13
Spec: docs/superpowers/specs/2026-06-13-archon-when-lint-design.md
Issue: #403

## Goal

Add a CI lint gate that validates `when:` expressions in `.archon/workflows/*.yaml` against Archon's supported grammar before merge. PR #359 introduced a parenthesized compound expression that Archon's engine could not parse, causing a 5-hour factory outage (#397). This plan adds a checker that catches that exact class of error.

## Architecture

A standalone Python script `dark-factory/scripts/check_workflow_when.py` mirrors the `check_workflow_dag.py` pattern: a `check(path) -> list[str]` public API callable from CI and tests, plus a `main(argv)` CLI entry point. It is called from the existing "Validate Archon workflow YAML" step in `.github/workflows/ci.yml` (the same `shell: python` run block that already calls `check_workflow_dag`). Tests live in `dark-factory/tests/test_workflow_when.py` and are picked up automatically by the `factory-tests` CI job (which already runs `dark-factory/tests/` with `PYTHONPATH: dark-factory/scripts`).

## Tech Stack

- Python 3 (stdlib: `pathlib`, `sys`; third-party: `pyyaml`, already in backend `requirements.txt`)
- pytest for unit tests (picked up by the `factory-tests` CI job)
- GitHub Actions CI (`.github/workflows/ci.yml`)

## File Structure

| File | Action | Description |
|------|--------|-------------|
| `dark-factory/scripts/check_workflow_when.py` | Create | Linter with `check()` API, `main()` CLI |
| `dark-factory/tests/test_workflow_when.py` | Create | Unit tests for the linter (6 required cases) |
| `.github/workflows/ci.yml` | Modify | Append `when_check()` call after existing `dag_check()` block |

---

## Task 1: Create the linter script and unit tests (TDD)

**Files:** `dark-factory/tests/test_workflow_when.py`, `dark-factory/scripts/check_workflow_when.py`

### Step 1.1 — Write failing tests

Create `dark-factory/tests/test_workflow_when.py`:

```python
"""Unit tests for check_workflow_when.py — when: expression grammar linter.

Guards against the class of silent Archon parse failure introduced by PR #359
(parenthesized / mixed-operator when: expressions) that caused the #397 outage.
"""

import sys
from pathlib import Path

import pytest
import yaml

_SCRIPTS_DIR = Path(__file__).resolve().parents[1] / "scripts"
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

from check_workflow_when import check  # noqa: E402

_WORKFLOW_PATH = (
    Path(__file__).resolve().parents[2]
    / ".archon" / "workflows" / "archon-dark-factory.yaml"
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_workflow(nodes: list[dict]) -> str:
    return yaml.dump({"name": "test-workflow", "nodes": nodes})


def _write_tmp(tmp_path: Path, content: str) -> Path:
    p = tmp_path / "workflow.yaml"
    p.write_text(content, encoding="utf-8")
    return p


# ---------------------------------------------------------------------------
# Happy path: current production workflow passes lint
# ---------------------------------------------------------------------------

def test_current_workflow_passes():
    """archon-dark-factory.yaml must pass the when: linter with zero errors."""
    assert _WORKFLOW_PATH.exists(), f"Workflow file not found: {_WORKFLOW_PATH}"
    errors = check(_WORKFLOW_PATH)
    assert errors == [], "\n".join(errors)


# ---------------------------------------------------------------------------
# Parentheses rejected
# ---------------------------------------------------------------------------

def test_parentheses_rejected(tmp_path):
    """A when: expression containing ( or ) must produce an error."""
    nodes = [{"id": "foo", "when": "($a.output == 'x') && $b.output == 'y'"}]
    path = _write_tmp(tmp_path, _make_workflow(nodes))
    errors = check(path)
    assert errors, "Expected an error for parenthesized expression but got none"
    assert any("paren" in e.lower() or "(" in e for e in errors), (
        f"Error message should mention parentheses: {errors}"
    )


# ---------------------------------------------------------------------------
# Mixed operators rejected
# ---------------------------------------------------------------------------

def test_mixed_operators_rejected(tmp_path):
    """A when: expression containing both && and || must produce an error."""
    nodes = [
        {"id": "foo", "when": "$a.output == 'x' && $b.output == 'y' || $c.output == 'z'"}
    ]
    path = _write_tmp(tmp_path, _make_workflow(nodes))
    errors = check(path)
    assert errors, "Expected an error for mixed && and || expression but got none"
    assert any("mixed" in e.lower() or "&&" in e or "||" in e for e in errors), (
        f"Error message should mention mixed operators: {errors}"
    )


# ---------------------------------------------------------------------------
# Same-operator chaining allowed (triple-OR is live in production)
# ---------------------------------------------------------------------------

def test_same_operator_chain_allowed(tmp_path):
    """Triple-OR chaining must produce no errors — confirmed working in production."""
    nodes = [
        {"id": "foo", "when": "$a.output == 'x' || $b.output == 'y' || $c.output == 'z'"}
    ]
    path = _write_tmp(tmp_path, _make_workflow(nodes))
    errors = check(path)
    assert errors == [], f"Expected no errors for same-operator chain, got: {errors}"


# ---------------------------------------------------------------------------
# Simple equality allowed
# ---------------------------------------------------------------------------

def test_simple_equality_allowed(tmp_path):
    """A bare equality when: expression must produce no errors."""
    nodes = [{"id": "foo", "when": "$node.output == 'value'"}]
    path = _write_tmp(tmp_path, _make_workflow(nodes))
    errors = check(path)
    assert errors == [], f"Expected no errors for simple equality, got: {errors}"


# ---------------------------------------------------------------------------
# Regression: the exact PR #359 expression that caused the #397 outage
# ---------------------------------------------------------------------------

def test_regression_pr359_expression_rejected(tmp_path):
    """The exact PR #359 expression that caused the #397 factory outage must be rejected.

    Expression: ($parse-intent.output.intent == 'new' || ...) && $bench-mode-probe.output != 'stub'
    Violations: parentheses + mixed && / || operators.
    """
    pr359_expr = (
        "($parse-intent.output.intent == 'new' || $parse-intent.output.intent == 'continue')"
        " && $bench-mode-probe.output != 'stub'"
    )
    nodes = [{"id": "foo", "when": pr359_expr}]
    path = _write_tmp(tmp_path, _make_workflow(nodes))
    errors = check(path)
    assert errors, "Expected PR #359 expression to be rejected but got no errors"
```

### Step 1.2 — Verify tests fail before implementation

```bash
cd /workspace/markethawk
PYTHONPATH=dark-factory/scripts python -m pytest dark-factory/tests/test_workflow_when.py -v 2>&1 | head -20
# Expected: ImportError — check_workflow_when module does not exist yet
```

### Step 1.3 — Implement the linter script

Create `dark-factory/scripts/check_workflow_when.py`:

```python
"""
when: expression linter for Archon workflow YAML files.

Enforces two rejection conditions against every when: field found anywhere
in a workflow YAML (depth-first walk handles any future YAML structure):

  1. No parentheses — reject if the expression contains ( or ).
  2. No mixed operators — reject if the expression contains both && and ||.

Same-operator chaining (e.g. a || b || c) is allowed and confirmed working
in production. The two conditions match the observable Archon grammar boundary
and the exact pattern that caused the #397 5-hour factory outage (PR #359).

Usage (CI):
    python dark-factory/scripts/check_workflow_when.py .archon/workflows/archon-dark-factory.yaml

API:
    from check_workflow_when import check
    errors = check(path)   # returns [] on success
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Union

import yaml


def _collect_when_values(obj: Any, results: list[str]) -> None:
    """Depth-first walk; appends every string value keyed 'when' to *results*."""
    if isinstance(obj, dict):
        for key, value in obj.items():
            if key == "when" and isinstance(value, str):
                results.append(value)
            else:
                _collect_when_values(value, results)
    elif isinstance(obj, list):
        for item in obj:
            _collect_when_values(item, results)


def _lint_expression(expr: str) -> list[str]:
    """Return error messages for *expr*; empty list means the expression is valid."""
    errors = []
    if "(" in expr or ")" in expr:
        errors.append(
            f"contains parentheses (not supported by Archon parser): {expr!r}"
        )
    if "&&" in expr and "||" in expr:
        errors.append(
            f"mixes && and || operators (not supported by Archon parser): {expr!r}"
        )
    return errors


def check(workflow_path: Union[str, Path]) -> list[str]:
    """Validate when: expressions in *workflow_path*.

    Returns a (possibly empty) list of human-readable error strings.
    Returns [] when all when: expressions pass the grammar check.
    """
    path = Path(workflow_path)
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        return [f"{path}: YAML parse error: {exc}"]
    except OSError as exc:
        return [f"{path}: cannot read file: {exc}"]

    when_values: list[str] = []
    _collect_when_values(data, when_values)

    errors: list[str] = []
    for expr in when_values:
        for msg in _lint_expression(expr):
            errors.append(f"{path}: when: {msg}")

    return errors


def main(argv: list[str] | None = None) -> int:
    args = argv if argv is not None else sys.argv[1:]
    if not args:
        print("Usage: check_workflow_when.py <workflow.yaml> [...]", file=sys.stderr)
        return 2

    all_errors: list[str] = []
    for path in args:
        all_errors.extend(check(path))

    if all_errors:
        print("Archon workflow when: expression lint failed:", file=sys.stderr)
        for err in all_errors:
            print(f"  {err}", file=sys.stderr)
        return 1

    print(f"when: expression lint passed for {len(args)} workflow file(s).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

### Step 1.4 — Verify all 6 tests pass

```bash
cd /workspace/markethawk
PYTHONPATH=dark-factory/scripts python -m pytest dark-factory/tests/test_workflow_when.py -v
```

Expected output:
```
PASSED dark-factory/tests/test_workflow_when.py::test_current_workflow_passes
PASSED dark-factory/tests/test_workflow_when.py::test_parentheses_rejected
PASSED dark-factory/tests/test_workflow_when.py::test_mixed_operators_rejected
PASSED dark-factory/tests/test_workflow_when.py::test_same_operator_chain_allowed
PASSED dark-factory/tests/test_workflow_when.py::test_simple_equality_allowed
PASSED dark-factory/tests/test_workflow_when.py::test_regression_pr359_expression_rejected
6 passed
```

### Step 1.5 — Commit

```bash
git add dark-factory/scripts/check_workflow_when.py dark-factory/tests/test_workflow_when.py
git commit -m "$(cat <<'EOF'
feat(ci): add when: expression linter for Archon workflow YAML files

Adds check_workflow_when.py (check(path) API mirroring check_workflow_dag.py)
and 6 unit tests including regression for the PR #359 expression that caused
the #397 factory outage. Rejects parentheses and mixed &&/|| operators.
EOF
)"
```

---

## Task 2: Wire the linter into CI

**Files:** `.github/workflows/ci.yml`

### Step 2.1 — Locate the insertion point

The "Validate Archon workflow YAML" step is a `shell: python` block. The current last line of the run script is:

```python
          print('DAG trigger_rule check passed.')
```

(The `sys.path.insert(0, 'dark-factory/scripts')` needed for the import is already present earlier in the same script block, so no second insertion is needed.)

### Step 2.2 — Apply the CI change

In `.github/workflows/ci.yml`, find the line:

```
          print('DAG trigger_rule check passed.')
```

and replace it with:

```
          print('DAG trigger_rule check passed.')

          # when: expression lint: rejects parentheses and mixed &&/|| operators.
          # Catches the class of regression introduced by PR #359 (issue #397).
          from check_workflow_when import check as when_check
          when_errors = when_check('.archon/workflows/archon-dark-factory.yaml')
          if when_errors:
              print('Archon workflow when: expression lint failed:')
              for e in when_errors:
                  print(f'  {e}')
              sys.exit(1)
          print('when: expression lint passed.')
```

### Step 2.3 — Verify the full CI step runs cleanly

Run the entire CI step script locally to confirm no regressions:

```bash
cd /workspace/markethawk
python -c "
import glob, sys, yaml
errors = []
for path in sorted(glob.glob('.archon/workflows/*.yaml')):
    try:
        yaml.safe_load(open(path))
    except yaml.YAMLError as e:
        errors.append(f'{path}: {e}')
if errors:
    print('Archon workflow YAML validation failed:')
    for e in errors:
        print(f'  {e}')
    sys.exit(1)
print(f'All {len(glob.glob(\".archon/workflows/*.yaml\"))} workflow file(s) valid.')

sys.path.insert(0, 'dark-factory/scripts')
from check_workflow_dag import check as dag_check
dag_errors = dag_check('.archon/workflows/archon-dark-factory.yaml')
if dag_errors:
    print('Archon workflow DAG validation failed:')
    for e in dag_errors:
        print(f'  {e}')
    sys.exit(1)
print('DAG trigger_rule check passed.')

from check_workflow_when import check as when_check
when_errors = when_check('.archon/workflows/archon-dark-factory.yaml')
if when_errors:
    print('Archon workflow when: expression lint failed:')
    for e in when_errors:
        print(f'  {e}')
    sys.exit(1)
print('when: expression lint passed.')
"
```

Expected output:
```
All 1 workflow file(s) valid.
DAG trigger_rule check passed.
when: expression lint passed.
```

### Step 2.4 — Commit

```bash
git add .github/workflows/ci.yml
git commit -m "$(cat <<'EOF'
ci: wire when: expression linter into Validate Archon workflow YAML step

Appends when_check() call after dag_check() in the existing Python CI step.
PRs that add parenthesized or mixed-operator when: expressions now fail CI.
EOF
)"
```

---

## Acceptance Criteria Check

| Criterion | Covered by |
|-----------|-----------|
| CI fails on `when: "($a.output == 'x') && $b.output == 'y'"` | Task 2 (CI wiring) + Task 1 `test_parentheses_rejected` |
| CI passes on `when: "$a.output == 'x' && $b.output == 'y'"` | Task 1 `test_current_workflow_passes` (production file passes) |
| Runs on every PR touching `.archon/workflows/*.yaml` | Task 2 (existing CI job triggers on all PRs) |
| Regression: exact PR #359 expression rejected | Task 1 `test_regression_pr359_expression_rejected` |
