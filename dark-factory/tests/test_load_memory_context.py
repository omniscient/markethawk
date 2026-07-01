"""Tests for dark-factory/scripts/load_memory_context.sh."""
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "dark-factory" / "scripts" / "load_memory_context.sh"


def run_script(phase: str, env: dict) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["bash", str(SCRIPT), phase],
        capture_output=True,
        text=True,
        env=env,
    )


def base_env(tmp_path: Path) -> dict:
    import os
    e = os.environ.copy()
    e["ARTIFACTS_DIR"] = str(tmp_path)
    e["REPO_ROOT"] = str(REPO_ROOT)
    e.pop("ISSUE_NUM", None)
    return e


class TestLoadMemoryContextScript:
    def test_script_exists(self):
        assert SCRIPT.exists(), f"Script not found: {SCRIPT}"

    def test_script_is_executable_or_runnable_via_bash(self):
        result = subprocess.run(["bash", "-n", str(SCRIPT)], capture_output=True, text=True)
        assert result.returncode == 0, f"Syntax error: {result.stderr}"

    def test_happy_path_exits_zero(self, tmp_path):
        env = base_env(tmp_path)
        result = run_script("implement", env)
        assert result.returncode == 0, f"Script failed: {result.stderr}"

    def test_outputs_to_stdout(self, tmp_path):
        env = base_env(tmp_path)
        result = run_script("implement", env)
        assert result.returncode == 0
        # stdout may be empty if no relevant memory — that's fine; the key is it exits 0
        # and the stdout is the memory context string (may be empty)
        assert isinstance(result.stdout, str)

    def test_writes_memory_context_md(self, tmp_path):
        env = base_env(tmp_path)
        result = run_script("implement", env)
        assert result.returncode == 0
        ctx_file = tmp_path / "memory-context.md"
        assert ctx_file.exists(), "memory-context.md was not created"

    def test_memory_context_md_matches_stdout(self, tmp_path):
        env = base_env(tmp_path)
        result = run_script("implement", env)
        assert result.returncode == 0
        ctx_file = tmp_path / "memory-context.md"
        # The file content should match stdout (stdout has trailing newline from printf)
        file_content = ctx_file.read_text()
        # stdout may have an extra trailing newline from printf '%s\n'
        assert file_content.rstrip("\n") == result.stdout.rstrip("\n")

    def test_writes_memory_trace_json(self, tmp_path):
        env = base_env(tmp_path)
        result = run_script("implement", env)
        assert result.returncode == 0
        trace_file = tmp_path / "memory-trace.json"
        assert trace_file.exists(), "memory-trace.json was not created"

    def test_trace_json_is_valid_json(self, tmp_path):
        import json
        env = base_env(tmp_path)
        result = run_script("implement", env)
        assert result.returncode == 0
        trace_file = tmp_path / "memory-trace.json"
        data = json.loads(trace_file.read_text())
        assert "schema_version" in data

    def test_different_phases_accepted(self, tmp_path):
        for phase in ("implement", "plan", "refine"):
            tp = tmp_path / phase
            tp.mkdir()
            env = base_env(tp)
            result = run_script(phase, env)
            assert result.returncode == 0, f"Failed for phase={phase}: {result.stderr}"

    def test_issue_num_passed_when_set(self, tmp_path):
        import json
        env = base_env(tmp_path)
        env["ISSUE_NUM"] = "670"
        result = run_script("implement", env)
        assert result.returncode == 0
        trace_file = tmp_path / "memory-trace.json"
        data = json.loads(trace_file.read_text())
        # memory_retrieve.py stores issue as an integer in the trace
        assert data.get("issue") == 670

    def test_fail_soft_when_memory_retrieve_unavailable(self, tmp_path):
        """Script must not abort when memory_retrieve.py fails (fail-soft guarantee)."""
        import os
        env = base_env(tmp_path)
        # Point REPO_ROOT to a temp dir with no memory_retrieve.py → python3 call will fail
        fake_root = tmp_path / "fake_root"
        fake_root.mkdir()
        # Create a minimal git repo so git commands work
        subprocess.run(["git", "init", str(fake_root)], capture_output=True)
        subprocess.run(
            ["git", "remote", "add", "origin", str(fake_root)],
            cwd=str(fake_root), capture_output=True,
        )
        env["REPO_ROOT"] = str(fake_root)
        env["ARTIFACTS_DIR"] = str(tmp_path / "artifacts")
        (tmp_path / "artifacts").mkdir()
        result = run_script("implement", env)
        # Must exit 0 (fail-soft) even when memory_retrieve.py is absent
        assert result.returncode == 0, f"Script aborted instead of failing soft: {result.stderr}"

    def test_creates_artifacts_dir_if_missing(self, tmp_path):
        env = base_env(tmp_path)
        missing_dir = tmp_path / "not_yet_created"
        env["ARTIFACTS_DIR"] = str(missing_dir)
        result = run_script("implement", env)
        assert result.returncode == 0
        assert missing_dir.exists(), "ARTIFACTS_DIR was not created by the script"

    def test_missing_phase_arg_fails(self, tmp_path):
        import os
        env = base_env(tmp_path)
        result = subprocess.run(
            ["bash", str(SCRIPT)],
            capture_output=True,
            text=True,
            env=env,
        )
        assert result.returncode != 0, "Script should fail when phase arg is missing"
