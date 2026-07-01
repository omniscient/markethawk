"""
Semantic DAG validation for Archon workflow YAML files.

Checks that OR-join nodes — nodes whose depends_on list contains mutually-exclusive
upstream branches — declare a skip-tolerant trigger_rule instead of the default
all_success.  Under all_success a skipped upstream causes the join to be skipped
too, silently aborting the remainder of the workflow.

Usage (CI):
    python dark-factory/scripts/check_workflow_dag.py .archon/workflows/archon-dark-factory.yaml

API:
    from dark_factory.scripts.check_workflow_dag import check
    errors = check(path)   # returns [] on success
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Union

import yaml

# OR-join nodes that are known to depend on mutually-exclusive upstream branches.
# Any intent run skips exactly one of their upstreams, so they MUST declare a
# skip-tolerant trigger_rule.
REQUIRED_OR_JOIN_NODES: frozenset[str] = frozenset(
    {"validate", "de-conflict", "status-in-review", "report", "budget-implement", "implement"}
)

# Accepted skip-tolerant rule values.
SKIP_TOLERANT_RULES: frozenset[str] = frozenset(
    {"none_failed_min_one_success", "one_success"}
)


def check(workflow_path: Union[str, Path]) -> list[str]:
    """Validate OR-join trigger_rule semantics in *workflow_path*.

    Returns a (possibly empty) list of human-readable error strings.
    Returns [] when the workflow passes all checks.
    """
    path = Path(workflow_path)
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        return [f"{path}: YAML parse error: {exc}"]
    except OSError as exc:
        return [f"{path}: cannot read file: {exc}"]

    nodes = data.get("nodes", [])
    if not isinstance(nodes, list):
        return [f"{path}: 'nodes' is not a list"]

    node_by_id: dict[str, dict] = {n["id"]: n for n in nodes if isinstance(n, dict) and "id" in n}

    errors: list[str] = []

    # Check 1: each known OR-join node must exist and carry a skip-tolerant trigger_rule.
    for node_id in sorted(REQUIRED_OR_JOIN_NODES):
        node = node_by_id.get(node_id)
        if node is None:
            errors.append(
                f"{path}: OR-join node '{node_id}' not found in workflow — "
                "update REQUIRED_OR_JOIN_NODES in check_workflow_dag.py"
            )
            continue
        rule = node.get("trigger_rule")
        if rule not in SKIP_TOLERANT_RULES:
            errors.append(
                f"{path}: OR-join node '{node_id}' has trigger_rule={rule!r} "
                f"(must be one of {sorted(SKIP_TOLERANT_RULES)}); "
                "without a skip-tolerant rule a skipped upstream branch "
                "silently aborts the rest of the workflow"
            )

    # Sync tripwire: the count of trigger_rule-bearing nodes must equal the size of
    # REQUIRED_OR_JOIN_NODES.  If a new OR-join node is added to the workflow with a
    # trigger_rule but without being added to REQUIRED_OR_JOIN_NODES, this fires.
    nodes_with_rule = [n for n in nodes if isinstance(n, dict) and "trigger_rule" in n]
    expected = len(REQUIRED_OR_JOIN_NODES)
    if len(nodes_with_rule) != expected:
        extras = [n.get("id", "<unknown>") for n in nodes_with_rule
                  if n.get("id") not in REQUIRED_OR_JOIN_NODES]
        errors.append(
            f"{path}: expected {expected} nodes with trigger_rule "
            f"(one per OR-join in REQUIRED_OR_JOIN_NODES), found {len(nodes_with_rule)}; "
            f"update REQUIRED_OR_JOIN_NODES in check_workflow_dag.py "
            f"(unexpected node(s): {extras})"
        )

    return errors


def main(argv: list[str] | None = None) -> int:
    args = argv if argv is not None else sys.argv[1:]
    if not args:
        print("Usage: check_workflow_dag.py <workflow.yaml> [...]", file=sys.stderr)
        return 2

    all_errors: list[str] = []
    for path in args:
        all_errors.extend(check(path))

    if all_errors:
        print("Archon workflow DAG validation failed:", file=sys.stderr)
        for err in all_errors:
            print(f"  {err}", file=sys.stderr)
        return 1

    print(f"DAG trigger_rule check passed for {len(args)} workflow file(s).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
