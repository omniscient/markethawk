# Archon `when:` Expression Linter Design

Date: 2026-06-13
Issue: #403

## Goal

Prevent malformed `when:` expressions in `.archon/workflows/*.yaml` from merging silently into `main`. PR #359 introduced a parenthesized compound expression that Archon's engine cannot parse, causing a 5-hour factory outage (#397). This spec adds a CI gate that catches that class of error before merge.

## Selected Approach

Add a standalone Python script `dark-factory/scripts/check_workflow_when.py` with a `check(path)` API that returns a list of error strings — mirroring the existing `check_workflow_dag.py` pattern. Call it from the existing "Validate Archon workflow YAML" CI step in `.github/workflows/ci.yml`. Write unit tests in `dark-factory/tests/test_workflow_when.py`.

This approach keeps the validation logic testable in isolation and keeps CI changes minimal (one call added to an existing step).

## Grammar Rules

The linter enforces two rejection conditions against every `when:` field value found anywhere in the workflow YAML:

1. **No parentheses** — reject if the expression contains `(` or `)`.
2. **No mixed operators** — reject if the expression contains both `&&` and `||`.

Same-operator chaining (e.g., `a == 'x' || b == 'y' || c == 'z'`) is **allowed**. The existing workflow already contains triple-OR expressions that are confirmed working in production. The issue's "single compound" wording undersells what Archon actually accepts; the two rejection conditions above match the observed grammar boundary and the exact pattern that caused #397.

Expressions that pass lint include:
- `$node.output == 'value'`
- `$a.output == 'x' && $b.output == 'y'`
- `$a.output == 'x' || $b.output == 'y' || $c.output == 'z'`

Expressions that fail lint include:
- `($a.output == 'x') && $b.output == 'y'`  (parentheses)
- `$a.output == 'x' && $b.output == 'y' || $c.output == 'z'`  (mixed operators)

## Implementation

### `dark-factory/scripts/check_workflow_when.py`

- `check(workflow_path: str | Path) -> list[str]` — load the YAML, walk all nodes, collect every `when:` value, apply the two rejection conditions, return error strings.
- `main(argv)` entry point for standalone CLI use: `python dark-factory/scripts/check_workflow_when.py .archon/workflows/*.yaml`
- The YAML walk should handle `when:` appearing at node level (the only current location), but the walk should be depth-first over all dict/list values so future YAML structure changes don't silently miss fields.

### `.github/workflows/ci.yml` — "Validate Archon workflow YAML" step

Append after the existing DAG check:

```python
sys.path.insert(0, 'dark-factory/scripts')
from check_workflow_when import check as when_check
when_errors = when_check('.archon/workflows/archon-dark-factory.yaml')
if when_errors:
    print('Archon workflow when: expression lint failed:')
    for e in when_errors:
        print(f'  {e}')
    sys.exit(1)
print('when: expression lint passed.')
```

### `dark-factory/tests/test_workflow_when.py`

Required test cases:
- **Happy path**: `archon-dark-factory.yaml` passes with zero errors.
- **Parentheses rejected**: expression with `(` or `)` produces an error.
- **Mixed operators rejected**: expression with both `&&` and `||` produces an error.
- **Same-operator chain allowed**: `a == 'x' || b == 'y' || c == 'z'` produces no errors.
- **Simple equality allowed**: `$node.output == 'value'` produces no errors.
- **Regression case**: the exact expression from PR #359 that caused #397 — `($parse-intent.output.intent == 'new' || $parse-intent.output.intent == 'continue') && $bench-mode-probe.output != 'stub'` — is rejected.

## Alternatives Considered

**Inline grep in CI** — a `grep -E` one-liner in `ci.yml` could check for `\(` or `&&.*\|\|`. Rejected: not testable, harder to extend, harder to read. The Python script approach is consistent with the existing checker pattern.

**Full grammar parser** — re-implement Archon's `when:` parser from the engine source. Rejected: the engine source is not in this repo; known only from observed behavior and post-mortem. The two-condition safety net is sufficient and avoids tight coupling to a parser we don't own.

## Out of Scope

- Linting `when:` expressions in workflow YAML files outside `.archon/workflows/`.
- Validating any other Archon YAML fields (covered by `check_workflow_dag.py` and YAML parse step).
- Adding path-filter triggers to CI (the `test` job already runs for all PRs; no change needed).

## Assumptions

- `when:` only appears at node level in all current workflow YAML files. The depth-first walk handles future structural changes defensively.
- The `factory-tests` CI job already runs `dark-factory/tests/` with `PYTHONPATH=dark-factory/scripts`, so new tests there are picked up automatically.
- The Archon grammar boundary is defined by the two observable failure conditions; no other unsupported syntax is known.
