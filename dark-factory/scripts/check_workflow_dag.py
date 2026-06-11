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
    {"validate", "de-conflict", "status-in-review", "report"}
)

# Accepted skip-tolerant rule values.
# all_done is intentionally excluded: it runs the join even when upstream nodes fail,
# masking real errors. Only rules that tolerate skips while still enforcing upstream
# success are accepted.
SKIP_TOLERANT_RULES: frozenset[str] = frozenset(
    {"none_failed_min_one_success", "one_success"}
)


def _has_when(node_by_id: dict[str, dict], dep_id: str) -> bool:
    """Return True if the node identified by *dep_id* carries a 'when:' condition."""
    dep = node_by_id.get(dep_id)
    if dep is None:
        return False  # unknown upstream → treat as unconditional (conservative)
    return bool(dep.get("when"))


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

    # Check 2: structural OR-join detection for nodes NOT in the allowlist.
    # A node whose every upstream carries a 'when:' condition may receive a skip from
    # a mutually-exclusive sibling branch under the default all_success rule.  Flag any
    # such node that lacks a skip-tolerant trigger_rule.
    # (Nodes with at least one unconditional upstream are AND-joins; all_success is correct.)
    for node in nodes:
        if not isinstance(node, dict):
            continue
        node_id = node.get("id", "<unknown>")
        if node_id in REQUIRED_OR_JOIN_NODES:
            continue  # already covered by check 1
        depends_on = node.get("depends_on", [])
        if not isinstance(depends_on, list) or len(depends_on) <= 1:
            continue
        if all(_has_when(node_by_id, dep) for dep in depends_on):
            rule = node.get("trigger_rule")
            if rule not in SKIP_TOLERANT_RULES:
                errors.append(
                    f"{path}: node '{node_id}' has {len(depends_on)} conditional upstreams "
                    f"(all have 'when:') but trigger_rule={rule!r} is not skip-tolerant "
                    f"(must be one of {sorted(SKIP_TOLERANT_RULES)}); "
                    "if any upstream is skipped due to a mutually-exclusive intent branch, "
                    "all_success will silently abort the rest of the workflow"
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
