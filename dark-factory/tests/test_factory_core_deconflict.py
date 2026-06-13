import os
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from factory_core.deconflict import tier1, tier2, hard_grep_survivors


# ---------------------------------------------------------------------------
# tier1 — allowlist files
# ---------------------------------------------------------------------------

def test_tier1_codeindex_calls_checkout_theirs(monkeypatch):
    calls = []
    monkeypatch.setattr(subprocess, "run", lambda cmd, **kw: (calls.append(cmd),
        subprocess.CompletedProcess([], 0, stdout="", stderr=""))[1])
    assert tier1("codeindex.json", "/repo") is True
    assert any("--theirs" in c for c in calls)
    assert any("codeindex.json" in c for c in calls)


def test_tier1_symbolindex_calls_checkout_theirs(monkeypatch):
    calls = []
    monkeypatch.setattr(subprocess, "run", lambda cmd, **kw: (calls.append(cmd),
        subprocess.CompletedProcess([], 0, stdout="", stderr=""))[1])
    assert tier1("symbolindex.json", "/repo") is True


def test_tier1_alembic_migration(monkeypatch):
    calls = []
    monkeypatch.setattr(subprocess, "run", lambda cmd, **kw: (calls.append(cmd),
        subprocess.CompletedProcess([], 0, stdout="", stderr=""))[1])
    assert tier1("backend/alembic/versions/abc123_add_foo.py", "/repo") is True
    assert any("--theirs" in c for c in calls)


def test_tier1_models_init_merges_imports(tmp_path):
    models_init = tmp_path / "backend" / "app" / "models" / "__init__.py"
    models_init.parent.mkdir(parents=True)
    models_init.write_text(
        "<<<<<<< HEAD\n"
        "from .foo import Foo\n"
        "=======\n"
        "from .bar import Bar\n"
        ">>>>>>> feature\n"
    )
    subprocess.run(["git", "init"], cwd=tmp_path, capture_output=True)
    subprocess.run(["git", "config", "user.email", "t@t"], cwd=tmp_path, capture_output=True)
    subprocess.run(["git", "config", "user.name", "T"], cwd=tmp_path, capture_output=True)

    result = tier1("backend/app/models/__init__.py", str(tmp_path))
    assert result is True
    content = models_init.read_text()
    assert "<<<<<<<" not in content
    assert "from .foo import Foo" in content
    assert "from .bar import Bar" in content


def test_tier1_models_init_deduplicates_imports(tmp_path):
    models_init = tmp_path / "backend" / "app" / "models" / "__init__.py"
    models_init.parent.mkdir(parents=True)
    models_init.write_text(
        "<<<<<<< HEAD\n"
        "from .foo import Foo\n"
        "from .bar import Bar\n"
        "=======\n"
        "from .bar import Bar\n"
        "from .baz import Baz\n"
        ">>>>>>> feature\n"
    )
    subprocess.run(["git", "init"], cwd=tmp_path, capture_output=True)
    subprocess.run(["git", "config", "user.email", "t@t"], cwd=tmp_path, capture_output=True)
    subprocess.run(["git", "config", "user.name", "T"], cwd=tmp_path, capture_output=True)

    tier1("backend/app/models/__init__.py", str(tmp_path))
    content = models_init.read_text()
    assert content.count("from .bar import Bar") == 1


def test_tier1_unknown_file_returns_false(tmp_path):
    assert tier1("src/random.py", str(tmp_path)) is False


# ---------------------------------------------------------------------------
# tier2 — sentinel contract
# ---------------------------------------------------------------------------

SENTINEL_RESPONSE = (
    "Some preamble Claude adds\n"
    "===BEGIN_RESOLVED_FILE===\n"
    "resolved content line 1\n"
    "resolved content line 2\n"
    "===END_RESOLVED_FILE===\n"
)


def test_tier2_sentinel_success(tmp_path, monkeypatch):
    f = tmp_path / "foo.py"
    f.write_text("<<<<<<< HEAD\nold\n=======\nnew\n>>>>>>> feature\n")

    def fake_run(cmd, **kw):
        if "claude" in " ".join(cmd):
            return subprocess.CompletedProcess([], 0, stdout=SENTINEL_RESPONSE, stderr="")
        return subprocess.CompletedProcess([], 0, stdout="", stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)
    assert tier2("foo.py", 42, "omniscient", "markethawk", str(tmp_path)) is True
    content = f.read_text()
    assert "resolved content line 1" in content
    assert "<<<<<<<" not in content


def test_tier2_no_sentinel_returns_false(tmp_path, monkeypatch):
    f = tmp_path / "foo.py"
    original = "<<<<<<< HEAD\nold\n=======\nnew\n>>>>>>> feature\n"
    f.write_text(original)

    def fake_run(cmd, **kw):
        if "claude" in " ".join(cmd):
            return subprocess.CompletedProcess([], 0,
                stdout="Here is the resolved content (no sentinels): resolved content", stderr="")
        return subprocess.CompletedProcess([], 0, stdout="", stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)
    assert tier2("foo.py", 42, "omniscient", "markethawk", str(tmp_path)) is False
    assert f.read_text() == original


def test_tier2_malformed_sentinel_returns_false(tmp_path, monkeypatch):
    f = tmp_path / "foo.py"
    f.write_text("<<<<<<< HEAD\nold\n=======\nnew\n>>>>>>> feature\n")

    def fake_run(cmd, **kw):
        if "claude" in " ".join(cmd):
            # Only BEGIN, no END
            return subprocess.CompletedProcess([], 0,
                stdout="===BEGIN_RESOLVED_FILE===\nresolved\n", stderr="")
        return subprocess.CompletedProcess([], 0, stdout="", stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)
    assert tier2("foo.py", 42, "omniscient", "markethawk", str(tmp_path)) is False


def test_tier2_claude_error_returns_false(tmp_path, monkeypatch):
    f = tmp_path / "foo.py"
    f.write_text("<<<<<<< HEAD\nold\n=======\nnew\n>>>>>>> feature\n")

    monkeypatch.setattr(subprocess, "run", lambda cmd, **kw:
        subprocess.CompletedProcess([], 1, stdout="", stderr="claude error"))
    assert tier2("foo.py", 42, "omniscient", "markethawk", str(tmp_path)) is False


# ---------------------------------------------------------------------------
# hard_grep_survivors — exclusion rules
# ---------------------------------------------------------------------------

def test_hard_grep_survivors_finds_markers(tmp_path):
    (tmp_path / "foo.py").write_text("<<<<<<< HEAD\nold\n=======\nnew\n>>>>>>> f\n")
    result = hard_grep_survivors(str(tmp_path))
    assert "foo.py" in result


def test_hard_grep_survivors_excludes_node_modules(tmp_path):
    (tmp_path / "node_modules").mkdir()
    (tmp_path / "node_modules" / "bar.js").write_text("<<<<<<< HEAD\n")
    result = hard_grep_survivors(str(tmp_path))
    assert not any("node_modules" in r for r in result)


def test_hard_grep_survivors_excludes_git(tmp_path):
    (tmp_path / ".git").mkdir()
    (tmp_path / ".git" / "ORIG_HEAD").write_text("<<<<<<< HEAD\n")
    result = hard_grep_survivors(str(tmp_path))
    assert not any(".git" in r for r in result)


def test_hard_grep_survivors_clean_returns_empty(tmp_path):
    (tmp_path / "clean.py").write_text("def foo(): pass\n")
    assert hard_grep_survivors(str(tmp_path)) == []


def test_hard_grep_survivors_skips_unlisted_extensions(tmp_path):
    (tmp_path / "binary.exe").write_bytes(b"<<<<<<< HEAD\n")
    result = hard_grep_survivors(str(tmp_path))
    assert "binary.exe" not in result


# ---------------------------------------------------------------------------
# resolve_merge_conflicts — orchestrator
# ---------------------------------------------------------------------------

def test_resolve_clean_merge_writes_artifact(tmp_path, monkeypatch):
    artifact_dir = tmp_path / "artifacts"
    artifact_dir.mkdir()

    def fake_run(cmd, **kw):
        cmd_str = " ".join(cmd)
        if "fetch" in cmd_str:
            return subprocess.CompletedProcess([], 0, stdout="", stderr="")
        if "merge" in cmd_str and "origin/main" in cmd_str:
            return subprocess.CompletedProcess([], 0, stdout="Already up to date.", stderr="")
        return subprocess.CompletedProcess([], 0, stdout="", stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)
    from factory_core.deconflict import resolve_merge_conflicts
    rc = resolve_merge_conflicts(42, str(tmp_path), "omniscient", "markethawk", str(artifact_dir))
    assert rc == 0
    artifact = (artifact_dir / "conflict_resolution.md").read_text()
    assert "CONFLICT_VERDICT=none" in artifact
    assert "ESCALATED=0" in artifact


def test_resolve_escalation_on_no_conflicted_files(tmp_path, monkeypatch):
    artifact_dir = tmp_path / "artifacts"
    artifact_dir.mkdir()

    def fake_run(cmd, **kw):
        cmd_str = " ".join(cmd)
        if "fetch" in cmd_str:
            return subprocess.CompletedProcess([], 0, stdout="", stderr="")
        if "merge" in cmd_str and "origin/main" in cmd_str:
            return subprocess.CompletedProcess([], 1, stdout="error", stderr="")
        if "diff" in cmd_str and "--diff-filter=U" in cmd_str:
            return subprocess.CompletedProcess([], 0, stdout="", stderr="")
        return subprocess.CompletedProcess([], 0, stdout="", stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)
    with patch("factory_core.board.set_board_status"):
        from factory_core.deconflict import resolve_merge_conflicts
        rc = resolve_merge_conflicts(42, str(tmp_path), "omniscient", "markethawk", str(artifact_dir))
    assert rc == 1
    artifact = (artifact_dir / "conflict_resolution.md").read_text()
    assert "CONFLICT_VERDICT=escalate" in artifact
    assert "ESCALATED=1" in artifact
