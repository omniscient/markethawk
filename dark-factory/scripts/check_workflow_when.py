"""Lint `when:` expressions in Archon workflow YAML files.

Archon's parser does not support parentheses or mixed &&/|| operators in `when:`
expressions.  PR #359 introduced a parenthesised expression that caused a 5-hour
factory outage (#397) because no CI step caught it before merge.

Supported grammar (from engine source / observed production behaviour):
  - Simple equality/inequality: ``$node.output == 'value'``
  - Same-operator chains:       ``$a == 'x' || $b == 'y' || $c == 'z'``

Not supported:
  - Parentheses (any ``(`` or ``)``)
  - Mixed ``&&`` and ``||`` in the same expression

Usage (CI)::

    python dark-factory/scripts/check_workflow_when.py .archon/workflows/archon-dark-factory.yaml

API::

    from check_workflow_when import check
    errors = check(path)   # returns [] on success
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Union

import yaml


def _collect_when_values(data: Any, _path: str = "") -> list[tuple[str, str]]:
    """Depth-first walk of *data*; collect all string values stored under a ``when`` key.

    Returns a list of ``(location_hint, expression)`` pairs where *location_hint*
    is a best-effort description of where in the YAML the expression lives.
    """
    results: list[tuple[str, str]] = []
    if isinstance(data, dict):
        for key, value in data.items():
            child_path = f"{_path}.{key}" if _path else key
            if key == "when" and isinstance(value, str):
                results.append((child_path, value))
            else:
                results.extend(_collect_when_values(value, child_path))
    elif isinstance(data, list):
        for i, item in enumerate(data):
            results.extend(_collect_when_values(item, f"{_path}[{i}]"))
    return results


def _lint_expression(expr: str) -> list[str]:
    """Return a list of violation descriptions for *expr*, or ``[]`` if valid."""
    violations: list[str] = []
    if "(" in expr or ")" in expr:
        violations.append(
            "contains parentheses — Archon's parser does not support parenthesised "
            "expressions (see #397)"
        )
    if "&&" in expr and "||" in expr:
        violations.append(
            "mixes '&&' and '||' operators — Archon only supports same-operator "
            "chains; use '&&' alone or '||' alone"
        )
    return violations


def check(workflow_path: Union[str, Path]) -> list[str]:
    """Lint all ``when:`` expressions in *workflow_path*.

    Returns a (possibly empty) list of human-readable error strings.
    Returns ``[]`` when the workflow passes all checks.
    """
    path = Path(workflow_path)
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        return [f"{path}: YAML parse error: {exc}"]
    except OSError as exc:
        return [f"{path}: cannot read file: {exc}"]

    errors: list[str] = []
    for location, expr in _collect_when_values(data):
        for violation in _lint_expression(expr):
            errors.append(f"{path}: when: at {location!r}: {violation}")

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
