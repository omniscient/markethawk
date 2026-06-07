# OR-Join Trigger-Rule Guard — Design

**Date:** 2026-06-07
**Status:** Pending review
**Issue:** #224
**Author:** Brainstormed with Claude (Opus 4.8)

## Problem

On 2026-06-04 a factory-self-generated commit (`ce9e4a3`) rewrote `.archon/workflows/archon-dark-factory.yaml` and silently introduced OR-join nodes that depended on mutually-exclusive siblings under the default `all_success` trigger_rule. The result: every dark-factory run produced no PR with no error — `anyFailed=false` but every downstream node was silently skipped.

The existing **"Validate Archon workflow YAML"** CI step checks YAML syntax only. It cannot catch this class of semantic error. Any future factory-generated conformance commit can reintroduce the same bug without CI objecting.

## Goal

Add a fast, zero-infrastructure CI check that catches OR-join trigger_rule regressions before they reach `main`.

## Non-Goals (v1)

- Automatic detection of *new* OR-join nodes added in future (fuller reachability analysis — file as a follow-up if wanted).
- Runtime detection inside the Archon executor.
- Checking workflow files other than `archon-dark-factory.yaml`.

## Requirements

1. A Python module `dark-factory/scripts/check_workflow_dag.py` implements the check and is importable so tests can exercise it without subprocess.
2. The existing **"Validate Archon workflow YAML"** CI step in `.github/workflows/ci.yml` calls the module after the syntax check — zero new CI jobs, zero new infrastructure.
3. The check asserts that each of the four known OR-join nodes declares a skip-tolerant `trigger_rule` (`none_failed_min_one_success` or `one_success`):

   | Node | Why it's an OR-join |
   |---|---|
   | `validate` | parents `preview-up` (new/continue) vs `preview-up-resolve` (resolve) are mutually exclusive |
   | `de-conflict` | parents `regen-codeindex` (continue) vs `setup-branch-resolve` (resolve) are mutually exclusive |
   | `status-in-review` | parents `push-and-pr`/`code-review` (new/continue) vs `push-resolve` (resolve) are mutually exclusive |
   | `report` | inherits OR-join from `status-in-review` and `code-review` (resolve skips `code-review`) |

4. A sync tripwire: if the total count of `trigger_rule`-bearing nodes in the workflow changes unexpectedly (currently 4), the check fails with a clear "update the OR-join allowlist" message.
5. The check passes on current `main` (all four nodes already carry `trigger_rule: none_failed_min_one_success`).
6. A regression test in `dark-factory/tests/test_workflow_or_join.py` provides an in-memory fixture reproducing the pre-fix `validate` node (`depends_on: [preview-up, preview-up-resolve]`, no `trigger_rule`) and asserts the check returns a non-empty error list.
7. A brief memory entry appended to `.archon/memory/dark-factory-ops.md` documenting the OR-join trigger_rule requirement.

## Architecture / Approach

### `dark-factory/scripts/check_workflow_dag.py`

A single importable module with:

```python
OR_JOIN_NODES = {
    "validate":        "none_failed_min_one_success",
    "de-conflict":     "none_failed_min_one_success",
    "status-in-review":"none_failed_min_one_success",
    "report":          "none_failed_min_one_success",
}
SKIP_TOLERANT = {"none_failed_min_one_success", "one_success"}

def check(workflow_path: Path) -> list[str]:
    """Return a list of error strings (empty = pass)."""
    ...
```

The `check()` function:
1. Parses the YAML with `yaml.safe_load`.
2. For each node id in `OR_JOIN_NODES`, asserts `trigger_rule` is in `SKIP_TOLERANT`.
3. Counts all nodes with a `trigger_rule` key; asserts the count equals `len(OR_JOIN_NODES)` (sync tripwire).
4. Returns all errors as strings (caller decides whether to raise/exit).

When run as `__main__`, exits 0 on pass, 1 with printed errors on fail.

### CI integration

The "Validate Archon workflow YAML" step in `.github/workflows/ci.yml` is extended: after the existing `yaml.safe_load` loop, it imports and calls `check_workflow_dag.check()` specifically on `.archon/workflows/archon-dark-factory.yaml`. The OR-join node enumeration is specific to this file; other workflow files are only syntax-checked. Errors from the DAG check are aggregated with the existing `errors` list; `sys.exit(1)` only fires if the combined list is non-empty.

Because `dark-factory/scripts/` has no `requirements.txt` of its own and `yaml` is already installed in the CI Python step, no additional dependency installation is required.

### `dark-factory/tests/test_workflow_or_join.py`

```python
from dark_factory.scripts.check_workflow_dag import check, OR_JOIN_NODES, SKIP_TOLERANT
# ... or import via importlib since there's no package __init__

def test_passes_on_real_workflow():
    errors = check(WF_PATH)
    assert errors == []

def test_regression_pre_fix_validate():
    """Reproduces ce9e4a3's pre-fix validate: depends_on=[preview-up,preview-up-resolve], no trigger_rule."""
    # Build an in-memory minimal workflow dict with the defective node
    ...
    errors = check_dict(workflow_dict)
    assert any("validate" in e for e in errors)
```

The test imports the same `check()` logic used by CI (or a `check_dict(workflow_dict)` overload for in-memory testing), so there is no duplication.

## Alternatives Considered

### Stronger: Intent-reachability analysis

Parse each node's `when:` expression, compute the set of intent values that can activate it, and flag any join node whose parents have disjoint intent sets. This would catch *future* OR-join bugs automatically.

**Rejected for this ticket (size:S):** The `when:` grammar requires a mini-parser; full reachability requires a DAG walk; the combined complexity exceeds one hour. This can be filed as a follow-up.

### Wiring into a new CI step

Add a separate "DAG semantics check" CI job rather than extending the existing YAML syntax step.

**Rejected:** The existing step already loads every workflow file and was explicitly called out in the issue acceptance criteria as the target integration point. A new job adds CI parallelism overhead for a 10-line check.

## Assumptions

- The `yaml` package is already available in the CI `test` job's Python environment (it is: the existing "Validate Archon workflow YAML" step calls `yaml.safe_load` inline).
- The four enumerated OR-join nodes remain the complete set as of `main`. If the factory adds a fifth OR-join node legitimately, the developer must also add it to `OR_JOIN_NODES` — the sync tripwire will prompt this.
- `dark-factory/tests/` runs locally (`pytest dark-factory/tests/`) but is not yet wired into the CI test job. The CI guard comes from the inline step extension, not from the pytest files. Both must pass for full coverage.

## Open Questions (non-blocking)

- Should the `dark-factory/tests/` pytest suite eventually be added to the CI `test` job as a separate step? Current state: it runs locally only, and the CI guard lives in the "Validate Archon workflow YAML" inline step. Either is fine for this ticket; leaving it as-is keeps scope small.
