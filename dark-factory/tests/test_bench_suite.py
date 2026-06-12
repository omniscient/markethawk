"""Tests for the replay benchmark suite (issue #335).

Covers:
- suite.json schema validation
- pass^k formula correctness
- BENCH_MODE workflow stub behavior in archon-dark-factory.yaml
- find_eligible.py module importability
"""

import json
import sys
from pathlib import Path

import pytest
import yaml

_BENCH_DIR = Path(__file__).resolve().parents[1] / "bench"
_SUITE_FILE = _BENCH_DIR / "suite.json"
_WORKFLOW_PATH = (
    Path(__file__).resolve().parents[2]
    / ".archon" / "workflows" / "archon-dark-factory.yaml"
)
_SCRIPTS_DIR = Path(__file__).resolve().parents[1] / "scripts"
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))


# ---------------------------------------------------------------------------
# suite.json schema
# ---------------------------------------------------------------------------

class TestSuiteJson:
    def test_suite_file_exists(self):
        assert _SUITE_FILE.exists(), f"suite.json not found at {_SUITE_FILE}"

    def test_suite_loads_as_json(self):
        data = json.loads(_SUITE_FILE.read_text())
        assert isinstance(data, dict)

    def test_suite_has_tasks_key(self):
        data = json.loads(_SUITE_FILE.read_text())
        assert "tasks" in data, "suite.json must have a 'tasks' key"

    def test_suite_has_at_least_ten_tasks(self):
        data = json.loads(_SUITE_FILE.read_text())
        assert len(data["tasks"]) >= 10, (
            f"Suite must have ≥10 tasks, got {len(data['tasks'])}"
        )

    def test_each_task_has_required_fields(self):
        required = {"issue", "title", "size", "pre_pr_sha", "golden_pr", "oracle_tests", "oracle_cmd"}
        data = json.loads(_SUITE_FILE.read_text())
        for task in data["tasks"]:
            missing = required - set(task.keys())
            assert not missing, f"Task #{task.get('issue', '?')} missing fields: {missing}"

    def test_each_task_size_is_valid(self):
        valid_sizes = {"S", "M", "L"}
        data = json.loads(_SUITE_FILE.read_text())
        for task in data["tasks"]:
            assert task["size"] in valid_sizes, (
                f"Task #{task['issue']} has invalid size: {task['size']!r}"
            )

    def test_each_task_has_oracle_tests(self):
        data = json.loads(_SUITE_FILE.read_text())
        for task in data["tasks"]:
            assert len(task["oracle_tests"]) >= 1, (
                f"Task #{task['issue']} must have at least one oracle test"
            )

    def test_each_task_oracle_cmd_is_valid(self):
        valid_cmds = {"pytest", "bash", "jest"}
        data = json.loads(_SUITE_FILE.read_text())
        for task in data["tasks"]:
            assert task["oracle_cmd"] in valid_cmds, (
                f"Task #{task['issue']} has invalid oracle_cmd: {task['oracle_cmd']!r}"
            )

    def test_each_task_pre_pr_sha_is_hex(self):
        data = json.loads(_SUITE_FILE.read_text())
        for task in data["tasks"]:
            sha = task["pre_pr_sha"]
            assert len(sha) == 40 and all(c in "0123456789abcdef" for c in sha), (
                f"Task #{task['issue']} pre_pr_sha is not a 40-char hex SHA: {sha!r}"
            )

    def test_issue_numbers_are_unique(self):
        data = json.loads(_SUITE_FILE.read_text())
        issues = [t["issue"] for t in data["tasks"]]
        assert len(issues) == len(set(issues)), f"Duplicate issue numbers in suite.json"

    def test_results_gitignore_exists(self):
        gitignore = _BENCH_DIR / ".gitignore"
        assert gitignore.exists(), ".gitignore not found in bench/"
        content = gitignore.read_text()
        assert "results/*.json" in content, ".gitignore must exclude results/*.json"


# ---------------------------------------------------------------------------
# pass^k formula
# ---------------------------------------------------------------------------

class TestPassK:
    def _pass_k(self, c: int, n: int, k: int) -> float:
        return round((c / n) ** k, 4) if n > 0 else 0.0

    def test_perfect_score(self):
        assert self._pass_k(3, 3, 3) == 1.0

    def test_zero_passes(self):
        assert self._pass_k(0, 3, 3) == 0.0

    def test_single_pass_out_of_three(self):
        # (1/3)^3 ≈ 0.037
        result = self._pass_k(1, 3, 3)
        assert abs(result - round((1 / 3) ** 3, 4)) < 1e-6

    def test_seventy_percent_single_run_honest_ceiling(self):
        # 70% single-run success → only ~34% for 3 clean runs
        c = 2  # 2/3 ≈ 67% (close to 70%)
        n = 3
        k = 3
        result = self._pass_k(c, n, k)
        # (2/3)^3 ≈ 0.2963 — under 34%, confirming the harsh pass^k metric
        assert result < 0.40

    def test_n_equals_zero_returns_zero(self):
        assert self._pass_k(0, 0, 3) == 0.0

    def test_k_equals_one_equals_pass_rate(self):
        # pass^1 = c/n (just the single-run pass rate)
        assert abs(self._pass_k(2, 3, 1) - round(2 / 3, 4)) < 1e-6


# ---------------------------------------------------------------------------
# Workflow BENCH_MODE stub behavior
# ---------------------------------------------------------------------------

class TestBenchModeWorkflow:
    def _load_workflow(self) -> dict:
        return yaml.safe_load(_WORKFLOW_PATH.read_text())

    def _get_node(self, workflow: dict, node_id: str) -> dict:
        for node in workflow.get("nodes", []):
            if node.get("id") == node_id:
                return node
        pytest.fail(f"Node '{node_id}' not found in workflow")

    def test_preview_up_has_bench_mode_guard(self):
        wf = self._load_workflow()
        node = self._get_node(wf, "preview-up")
        bash = node.get("bash", "")
        assert "BENCH_MODE" in bash, (
            "preview-up must check BENCH_MODE to stub preview stack for bench runs"
        )

    def test_preview_up_bench_stub_exits_zero(self):
        wf = self._load_workflow()
        node = self._get_node(wf, "preview-up")
        bash = node.get("bash", "")
        # Stub path must: check stub, write preview_env.sh, exit 0
        assert "stub" in bash, "preview-up must handle BENCH_MODE=stub"
        assert "write_preview_env" in bash or "preview_env.sh" in bash, (
            "preview-up stub must write preview_env.sh for downstream nodes"
        )
        assert "exit 0" in bash, "preview-up stub path must exit 0"

    def test_push_and_pr_has_bench_mode_guard(self):
        wf = self._load_workflow()
        node = self._get_node(wf, "push-and-pr")
        bash = node.get("bash", "")
        assert "BENCH_MODE" in bash, (
            "push-and-pr must check BENCH_MODE to skip push/PR creation in bench runs"
        )

    def test_push_and_pr_bench_stub_exits_zero(self):
        wf = self._load_workflow()
        node = self._get_node(wf, "push-and-pr")
        bash = node.get("bash", "")
        assert "stub" in bash, "push-and-pr must handle BENCH_MODE=stub"
        assert "exit 0" in bash, "push-and-pr stub path must exit 0"

    def test_classify_preview_skipped_in_bench_mode(self):
        """classify-preview must not fire its LLM call when BENCH_MODE=stub.

        The spec (Architecture §2) requires classify-preview to be gated so no
        Haiku call fires during bench runs. Implemented via a bench-mode-probe
        dependency whose output is checked in the when condition.
        """
        wf = self._load_workflow()
        node = self._get_node(wf, "classify-preview")
        when_cond = node.get("when", "")
        deps = node.get("depends_on", [])
        assert "bench-mode-probe" in when_cond, (
            "classify-preview must gate on bench-mode-probe output to prevent "
            "LLM calls during BENCH_MODE=stub replay runs"
        )
        assert "bench-mode-probe" in deps, (
            "classify-preview must depend on bench-mode-probe"
        )

    def test_bench_mode_probe_node_exists(self):
        """bench-mode-probe bash node must exist and output 'stub' when BENCH_MODE=stub."""
        wf = self._load_workflow()
        node = self._get_node(wf, "bench-mode-probe")
        bash = node.get("bash", "")
        assert "BENCH_MODE" in bash, "bench-mode-probe must check BENCH_MODE env var"
        assert "stub" in bash, "bench-mode-probe must output 'stub' for BENCH_MODE=stub"

    def test_gate_nodes_unchanged(self):
        """validate, conformance, code-review, status-in-review, report must not have BENCH_MODE guards."""
        wf = self._load_workflow()
        gate_nodes = ["validate", "conformance", "code-review", "status-in-review", "report"]
        for nid in gate_nodes:
            node = self._get_node(wf, nid)
            # Gate nodes can be 'bash' or 'command' type
            content = node.get("bash", "") + node.get("command", "") + node.get("prompt", "")
            assert "BENCH_MODE" not in content, (
                f"Gate node '{nid}' must NOT have BENCH_MODE guards — it must run unchanged in bench mode"
            )

    def test_or_join_nodes_still_present(self):
        """OR-join nodes must still be present and have correct trigger_rules after our BENCH_MODE additions."""
        from check_workflow_dag import check  # noqa: PLC0415
        errors = check(_WORKFLOW_PATH)
        assert errors == [], (
            f"OR-join check failed after BENCH_MODE modifications:\n" + "\n".join(errors)
        )


# ---------------------------------------------------------------------------
# find_eligible.py importability
# ---------------------------------------------------------------------------

def test_find_eligible_importable():
    """find_eligible.py must be importable without errors."""
    bench_dir = Path(__file__).resolve().parents[1] / "bench"
    if str(bench_dir) not in sys.path:
        sys.path.insert(0, str(bench_dir))
    import find_eligible  # noqa: F401
    assert hasattr(find_eligible, "get_pre_pr_sha")
    assert hasattr(find_eligible, "compute_pass_k" if hasattr(find_eligible, "compute_pass_k") else "verify_fail_pass")


def test_find_eligible_has_required_functions():
    bench_dir = Path(__file__).resolve().parents[1] / "bench"
    if str(bench_dir) not in sys.path:
        sys.path.insert(0, str(bench_dir))
    import find_eligible
    for fn in ("get_pre_pr_sha", "get_pr_test_files", "get_size_label", "fetch_closed_issues_with_prs"):
        assert hasattr(find_eligible, fn), f"find_eligible.py missing function: {fn}"
