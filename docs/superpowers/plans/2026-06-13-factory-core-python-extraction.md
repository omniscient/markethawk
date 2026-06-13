# Factory Core Python Extraction — Implementation Plan

**Date:** 2026-06-13
**Issue:** #337
**Spec:** [docs/superpowers/specs/2026-06-13-factory-core-python-extraction-design.md](../specs/2026-06-13-factory-core-python-extraction-design.md)

---

## Goal

Extract board ops, retry/circuit-breaker logic, and the three-tier de-conflict strategy from duplicated, untestable bash into a single tested Python package (`factory_core`). Entrypoint and scheduler become thin adapters. A new `factory-tests` CI job covers the package.

## Architecture

```
dark-factory/scripts/factory_core/
  __init__.py       — re-exports for import convenience
  board.py          — constants + find_board_item, set_board_status, post_or_update_comment
  deconflict.py     — tier1(), tier2(), hard_grep_survivors(), resolve_merge_conflicts()
  breaker.py        — get/increment/reset_retry, trip_to_blocked
  run_record.py     — moved from dark-factory/scripts/run_record.py (unchanged logic)
  cli.py            — argparse dispatch for all subcommands
```

## Tech Stack

Python 3.12 standard library + pytest + pytest-mock. No new dependencies beyond what CI already installs.

---

## File Structure

| File | Change |
|------|--------|
| `dark-factory/scripts/factory_core/__init__.py` | Create |
| `dark-factory/scripts/factory_core/board.py` | Create |
| `dark-factory/scripts/factory_core/deconflict.py` | Create |
| `dark-factory/scripts/factory_core/breaker.py` | Create |
| `dark-factory/scripts/factory_core/run_record.py` | Move from `scripts/run_record.py` |
| `dark-factory/scripts/factory_core/cli.py` | Create |
| `dark-factory/tests/test_factory_core_board.py` | Create |
| `dark-factory/tests/test_factory_core_deconflict.py` | Create |
| `dark-factory/tests/test_factory_core_breaker.py` | Create |
| `dark-factory/tests/test_run_record.py` | Update import (line 7–8) |
| `dark-factory/entrypoint.sh` | Remove tier fns; replace `_resolve_merge_conflicts` |
| `dark-factory/scheduler.sh` | Replace 5 functions with thin adapters |
| `.archon/workflows/archon-dark-factory.yaml` | Replace de-conflict node body |
| `.github/workflows/ci.yml` | Add `factory-tests` job |

---

## Task 1 — Package skeleton + board.py + board tests

**Files:** `dark-factory/scripts/factory_core/__init__.py`, `dark-factory/scripts/factory_core/board.py`, `dark-factory/tests/test_factory_core_board.py`

### Steps

**Step 1.1 — Write failing board tests**

```bash
pip install pytest pytest-mock
```

Create `dark-factory/tests/test_factory_core_board.py`:

```python
import json
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from factory_core import board


def _items(items):
    return subprocess.CompletedProcess([], 0, stdout=json.dumps({"items": items}), stderr="")


def _ok():
    return subprocess.CompletedProcess([], 0, stdout="", stderr="")


def test_find_board_item_found(monkeypatch):
    monkeypatch.setattr(subprocess, "run", lambda cmd, **kw: _items([
        {"id": "ITEM42", "content": {"number": 42, "type": "Issue"}},
    ]))
    assert board.find_board_item(42) == "ITEM42"


def test_find_board_item_wrong_number(monkeypatch):
    monkeypatch.setattr(subprocess, "run", lambda cmd, **kw: _items([
        {"id": "ITEM99", "content": {"number": 99, "type": "Issue"}},
    ]))
    assert board.find_board_item(42) == ""


def test_find_board_item_gh_failure(monkeypatch):
    monkeypatch.setattr(subprocess, "run", lambda cmd, **kw:
        subprocess.CompletedProcess([], 1, stdout="", stderr="error"))
    assert board.find_board_item(42) == ""


def test_set_board_status_calls_item_edit(monkeypatch):
    calls = []
    def fake(cmd, **kw):
        calls.append(cmd)
        if "item-list" in cmd:
            return _items([{"id": "ITEM42", "content": {"number": 42, "type": "Issue"}}])
        return _ok()
    monkeypatch.setattr(subprocess, "run", fake)
    board.set_board_status(42, "opt_abc")
    assert any("item-edit" in " ".join(c) for c in calls)
    edit = next(c for c in calls if "item-edit" in " ".join(c))
    assert "opt_abc" in edit
    assert "ITEM42" in edit


def test_set_board_status_no_item_skips_edit(monkeypatch):
    calls = []
    monkeypatch.setattr(subprocess, "run", lambda cmd, **kw: (calls.append(cmd), _items([]))[1])
    board.set_board_status(42, "opt_abc")
    assert not any("item-edit" in " ".join(c) for c in calls)


def test_post_or_update_comment_new_comment(monkeypatch):
    calls = []
    def fake(cmd, **kw):
        calls.append(cmd)
        return subprocess.CompletedProcess([], 0, stdout="", stderr="")
    monkeypatch.setattr(subprocess, "run", fake)
    board.post_or_update_comment(42, "<!-- marker -->", "body text")
    assert any("issue" in " ".join(c) and "comment" in " ".join(c) for c in calls)


def test_post_or_update_comment_updates_existing(monkeypatch):
    calls = []
    def fake(cmd, **kw):
        calls.append(cmd)
        if "--jq" in " ".join(cmd):
            return subprocess.CompletedProcess([], 0, stdout="12345\n", stderr="")
        return _ok()
    monkeypatch.setattr(subprocess, "run", fake)
    board.post_or_update_comment(42, "<!-- marker -->", "updated body")
    assert any("PATCH" in " ".join(c) for c in calls)
    assert any("12345" in " ".join(c) for c in calls)
```

Verify tests fail:
```bash
cd /workspace/markethawk
PYTHONPATH=dark-factory/scripts python -m pytest dark-factory/tests/test_factory_core_board.py -v 2>&1 | head -20
# Expected: ModuleNotFoundError: No module named 'factory_core'
```

**Step 1.2 — Create package skeleton**

Create `dark-factory/scripts/factory_core/__init__.py`:

```python
from .board import (
    find_board_item,
    set_board_status,
    post_or_update_comment,
    OWNER,
    REPO,
    PROJECT_NUMBER,
    PROJECT_ID,
    STATUS_FIELD,
    STATUS_READY,
    STATUS_IN_PROGRESS,
    STATUS_IN_REVIEW,
    STATUS_BLOCKED,
    STATUS_DONE,
    STATUS_BACKLOG,
    STATUS_REFINED,
)
from .breaker import get_retry_count, increment_retry, reset_retry, trip_to_blocked
from .deconflict import resolve_merge_conflicts, tier1, tier2, hard_grep_survivors
from . import run_record

__all__ = [
    "find_board_item", "set_board_status", "post_or_update_comment",
    "OWNER", "REPO", "PROJECT_NUMBER", "PROJECT_ID", "STATUS_FIELD",
    "STATUS_READY", "STATUS_IN_PROGRESS", "STATUS_IN_REVIEW", "STATUS_BLOCKED",
    "STATUS_DONE", "STATUS_BACKLOG", "STATUS_REFINED",
    "get_retry_count", "increment_retry", "reset_retry", "trip_to_blocked",
    "resolve_merge_conflicts", "tier1", "tier2", "hard_grep_survivors",
    "run_record",
]
```

**Step 1.3 — Implement board.py**

Create `dark-factory/scripts/factory_core/board.py`:

```python
import json
import os
import subprocess
import tempfile

OWNER = "omniscient"
REPO = "markethawk"
PROJECT_NUMBER = 1
PROJECT_ID = "PVT_kwHOAAFds84BWh4w"
STATUS_FIELD = "PVTSSF_lAHOAAFds84BWh4wzhR1VaA"
STATUS_READY = "61e4505c"
STATUS_IN_PROGRESS = "47fc9ee4"
STATUS_IN_REVIEW = "df73e18b"
STATUS_BLOCKED = "93d87b2f"
STATUS_DONE = "98236657"
STATUS_BACKLOG = "f75ad846"
STATUS_REFINED = "0c79ebe5"


def find_board_item(issue_num: int) -> str:
    r = subprocess.run(
        ["gh", "project", "item-list", str(PROJECT_NUMBER),
         "--owner", OWNER, "--format", "json", "--limit", "200"],
        capture_output=True, text=True,
    )
    if r.returncode != 0:
        return ""
    try:
        for item in json.loads(r.stdout).get("items", []):
            c = item.get("content", {})
            if c.get("number") == issue_num and c.get("type") == "Issue":
                return item["id"]
    except (json.JSONDecodeError, KeyError):
        pass
    return ""


def set_board_status(issue_num: int, option_id: str) -> None:
    item_id = find_board_item(issue_num)
    if not item_id:
        return
    subprocess.run(
        ["gh", "project", "item-edit",
         "--project-id", PROJECT_ID,
         "--id", item_id,
         "--field-id", STATUS_FIELD,
         "--single-select-option-id", option_id],
        capture_output=True,
    )


def post_or_update_comment(issue_num: int, marker: str, body: str) -> None:
    r = subprocess.run(
        ["gh", "api", f"repos/{OWNER}/{REPO}/issues/{issue_num}/comments",
         "--jq", f'[.[] | select(.body | contains("{marker}"))] | last | .id // empty'],
        capture_output=True, text=True,
    )
    comment_id = r.stdout.strip() if r.returncode == 0 else ""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".md", delete=False) as fh:
        fh.write(body)
        tmp = fh.name
    try:
        if comment_id:
            subprocess.run(
                ["gh", "api",
                 f"repos/{OWNER}/{REPO}/issues/comments/{comment_id}",
                 "--method", "PATCH", "-F", f"body=@{tmp}"],
                capture_output=True,
            )
        else:
            subprocess.run(
                ["gh", "issue", "comment", str(issue_num), "--body-file", tmp],
                capture_output=True,
            )
    finally:
        os.unlink(tmp)
```

**Step 1.4 — Verify board tests pass**

```bash
PYTHONPATH=dark-factory/scripts python -m pytest dark-factory/tests/test_factory_core_board.py -v
# Expected: 7 passed
```

**Step 1.5 — Commit**

```bash
git add dark-factory/scripts/factory_core/__init__.py \
        dark-factory/scripts/factory_core/board.py \
        dark-factory/tests/test_factory_core_board.py
git commit -m "feat(#337): add factory_core package skeleton and board.py"
```

---

## Task 2 — deconflict.py + tests

**Files:** `dark-factory/scripts/factory_core/deconflict.py`, `dark-factory/tests/test_factory_core_deconflict.py`

### Steps

**Step 2.1 — Write failing deconflict tests**

Create `dark-factory/tests/test_factory_core_deconflict.py`:

```python
import os
import subprocess
import sys
from pathlib import Path

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

from unittest.mock import patch


def test_resolve_clean_merge_writes_artifact(tmp_path, monkeypatch):
    artifact_dir = tmp_path / "artifacts"
    artifact_dir.mkdir()
    def fake_run(cmd, **kw):
        if "fetch" in cmd:
            return subprocess.CompletedProcess([], 0, stdout="", stderr="")
        if "merge" in cmd and "origin/main" in cmd:
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
```

Verify tests fail:
```bash
PYTHONPATH=dark-factory/scripts python -m pytest dark-factory/tests/test_factory_core_deconflict.py -v 2>&1 | head -10
# Expected: ImportError or ModuleNotFoundError
```

**Step 2.2 — Implement deconflict.py**

Create `dark-factory/scripts/factory_core/deconflict.py`:

```python
import os
import subprocess
from pathlib import Path

_EXCLUDED_DIRS = frozenset({".git", "node_modules"})
_INCLUDED_EXTS = frozenset({
    ".py", ".ts", ".tsx", ".js", ".json",
    ".yaml", ".yml", ".sh", ".sql", ".md",
})


def tier1(filepath: str, clone_dir: str) -> bool:
    """Mechanical resolution for known file patterns. Returns True if resolved."""
    basename = os.path.basename(filepath)

    if filepath in ("codeindex.json", "symbolindex.json", "docs/codeindex-hotspots.md"):
        r = subprocess.run(["git", "checkout", "--theirs", filepath],
                           cwd=clone_dir, capture_output=True)
        if r.returncode != 0:
            return False
        subprocess.run(["git", "add", filepath], cwd=clone_dir, capture_output=True)
        return True

    if basename == "package-lock.json" and "frontend" in filepath:
        r = subprocess.run(["git", "checkout", "--theirs", filepath],
                           cwd=clone_dir, capture_output=True)
        if r.returncode != 0:
            return False
        frontend_dir = os.path.join(clone_dir, "frontend")
        subprocess.run(["npm", "install", "--silent"], cwd=frontend_dir, capture_output=True)
        subprocess.run(["git", "add", filepath], cwd=clone_dir, capture_output=True)
        return True

    if filepath == "backend/app/models/__init__.py":
        full = os.path.join(clone_dir, filepath)
        try:
            with open(full) as fh:
                content = fh.read()
            lines = content.split("\n")
            stripped = [l for l in lines
                        if not l.startswith("<<<<<<<")
                        and not l.startswith("=======")
                        and not l.startswith(">>>>>>>")]
            seen: set = set()
            final = []
            for line in stripped:
                s = line.strip()
                if s and (s.startswith("from ") or s.startswith("import ")):
                    if s not in seen:
                        seen.add(s)
                        final.append(line)
                else:
                    final.append(line)
            with open(full, "w") as fh:
                fh.write("\n".join(final))
            subprocess.run(["git", "add", filepath], cwd=clone_dir, capture_output=True)
            return True
        except OSError:
            return False

    if "alembic/versions/" in filepath and filepath.endswith(".py"):
        r = subprocess.run(["git", "checkout", "--theirs", filepath],
                           cwd=clone_dir, capture_output=True)
        if r.returncode != 0:
            return False
        subprocess.run(["git", "add", filepath], cwd=clone_dir, capture_output=True)
        return True

    return False


def tier2(filepath: str, issue_num: int, owner: str, repo: str, clone_dir: str) -> bool:
    """AI-assisted resolution using sentinel-wrapped output. Returns True if resolved."""
    full = os.path.join(clone_dir, filepath) if not os.path.isabs(filepath) else filepath
    if not os.path.exists(full):
        return False
    try:
        with open(full) as fh:
            conflict_content = fh.read()
    except OSError:
        return False

    r1 = subprocess.run(
        ["gh", "issue", "view", str(issue_num), "--repo", f"{owner}/{repo}",
         "--json", "body", "--jq", ".body"],
        capture_output=True, text=True,
    )
    issue_body = r1.stdout.strip() if r1.returncode == 0 else ""

    r2 = subprocess.run(["git", "log", "--oneline", "-15", "HEAD"],
                        cwd=clone_dir, capture_output=True, text=True)
    git_log = r2.stdout.strip() if r2.returncode == 0 else ""

    prompt = (
        "Resolve the git merge conflict markers in this file, preserving both intents "
        "(what the feature branch added AND what main added).\n\n"
        "Return the COMPLETE resolved file content between two marker lines, EXACTLY like this "
        "and nothing else:\n"
        "===BEGIN_RESOLVED_FILE===\n"
        "<complete resolved file content>\n"
        "===END_RESOLVED_FILE===\n\n"
        "No explanation, commentary, or markdown code fences — inside or outside the markers.\n\n"
        f"File: {filepath}\n\n"
        f"Issue context:\n{issue_body}\n\n"
        f"Recent git log:\n{git_log}\n\n"
        f"File content with conflict markers:\n{conflict_content}\n"
    )

    r3 = subprocess.run(
        ["claude", "-p", "--model", "sonnet"],
        input=prompt, capture_output=True, text=True,
    )
    if r3.returncode != 0:
        return False

    raw = r3.stdout
    if "===BEGIN_RESOLVED_FILE===" not in raw or "===END_RESOLVED_FILE===" not in raw:
        return False

    lines = raw.splitlines()
    in_block = False
    resolved_lines = []
    for line in lines:
        if line == "===BEGIN_RESOLVED_FILE===":
            in_block = True
            continue
        if line == "===END_RESOLVED_FILE===":
            in_block = False
            continue
        if in_block:
            resolved_lines.append(line)

    resolved = "\n".join(resolved_lines)
    if not resolved.strip():
        return False
    if any(l.startswith("<<<<<<<") or l.startswith(">>>>>>>") for l in resolved_lines):
        return False

    with open(full, "w") as fh:
        fh.write(resolved + "\n")
    subprocess.run(["git", "add", filepath], cwd=clone_dir, capture_output=True)
    return True


def hard_grep_survivors(root: str) -> list:
    """Return relative paths of files containing conflict markers, excluding .git/node_modules."""
    survivors = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in _EXCLUDED_DIRS]
        for filename in filenames:
            if os.path.splitext(filename)[1] not in _INCLUDED_EXTS:
                continue
            full = os.path.join(dirpath, filename)
            try:
                with open(full, encoding="utf-8", errors="ignore") as fh:
                    for line in fh:
                        if line.startswith("<<<<<<<"):
                            survivors.append(os.path.relpath(full, root))
                            break
            except OSError:
                pass
    return survivors


def _write_artifact(path: Path, verdict: str, files: int,
                    tier1_count: int, tier2_count: int, escalated: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        f"CONFLICT_VERDICT={verdict}\n"
        f"FILES_CONFLICTED={files}\n"
        f"TIER1_RESOLVED={tier1_count}\n"
        f"TIER2_RESOLVED={tier2_count}\n"
        f"ESCALATED={escalated}\n"
    )


def _escalate(issue_num: int, owner: str, repo: str, reason: str) -> None:
    from .board import set_board_status, STATUS_BLOCKED
    set_board_status(issue_num, STATUS_BLOCKED)
    body = (
        "## Dark Factory — Conflict Resolution Escalated\n\n"
        "The factory attempted automatic merge conflict resolution but could not complete it.\n\n"
        f"**Reason:** {reason}\n\n"
        "**To fix manually:**\n"
        "```bash\n"
        f"git checkout feat/issue-{issue_num}-*\n"
        "git fetch origin main\n"
        "git merge origin/main\n"
        "# Resolve conflicts manually, then push\n"
        "```\n\n"
        "---\n*Posted by MarketHawk Dark Factory*"
    )
    subprocess.run(
        ["gh", "issue", "comment", str(issue_num),
         "--repo", f"{owner}/{repo}", "--body", body],
        capture_output=True,
    )


def resolve_merge_conflicts(
    issue_num: int,
    clone_dir: str,
    owner: str,
    repo: str,
    artifacts_dir: str,
    ai_tier: bool = True,
) -> int:
    """
    Orchestrate Tier 1 → Tier 2 → hard-grep gate.
    Writes artifacts_dir/conflict_resolution.md.
    Returns 0 on success, 1 after escalation.
    """
    artifact_path = Path(artifacts_dir) / "conflict_resolution.md"

    subprocess.run(["git", "fetch", "origin", "main"],
                   cwd=clone_dir, capture_output=True)
    r = subprocess.run(
        ["git", "merge", "origin/main", "--no-edit", "--no-ff"],
        cwd=clone_dir, capture_output=True, text=True,
    )

    if r.returncode == 0:
        _write_artifact(artifact_path, "none", 0, 0, 0, 0)
        return 0

    r2 = subprocess.run(
        ["git", "diff", "--name-only", "--diff-filter=U"],
        cwd=clone_dir, capture_output=True, text=True,
    )
    conflicted = [f for f in r2.stdout.splitlines() if f]

    if not conflicted:
        subprocess.run(["git", "merge", "--abort"], cwd=clone_dir, capture_output=True)
        _escalate(issue_num, owner, repo,
                  "Merge failed with no resolvable conflict markers.")
        _write_artifact(artifact_path, "escalate", 0, 0, 0, 1)
        return 1

    tier1_count = 0
    tier2_needed = []
    for f in conflicted:
        if tier1(f, clone_dir):
            tier1_count += 1
        else:
            tier2_needed.append(f)

    # Alembic multi-head check after tier1
    backend_dir = os.path.join(clone_dir, "backend")
    r3 = subprocess.run(
        ["python", "-m", "alembic", "heads"],
        cwd=backend_dir, capture_output=True, text=True,
    )
    heads = [l for l in r3.stdout.splitlines()
             if l and l[:1] in "0123456789abcdef"]
    if len(heads) > 1:
        subprocess.run(
            ["python", "-m", "alembic", "merge", "heads",
             "-m", f"merge_branches_issue_{issue_num}"],
            cwd=backend_dir, capture_output=True,
        )
        subprocess.run(["git", "add", "backend/alembic/versions/"],
                       cwd=clone_dir, capture_output=True)

    tier2_count = 0
    ai_uncertain = []
    if tier2_needed and ai_tier:
        for f in tier2_needed:
            if tier2(f, issue_num, owner, repo, clone_dir):
                tier2_count += 1
            else:
                ai_uncertain.append(f)
    else:
        ai_uncertain = list(tier2_needed)

    survivors = hard_grep_survivors(clone_dir)

    if ai_uncertain or survivors:
        parts = []
        if ai_uncertain:
            parts.append(f"AI could not resolve: {', '.join(ai_uncertain)}.")
        if survivors:
            parts.append(f"Surviving markers in: {', '.join(survivors)}.")
        subprocess.run(["git", "merge", "--abort"], cwd=clone_dir, capture_output=True)
        _escalate(issue_num, owner, repo, " ".join(parts))
        _write_artifact(artifact_path, "escalate", len(conflicted),
                        tier1_count, tier2_count, 1)
        return 1

    subprocess.run(
        ["git", "commit", "-m",
         f"chore: merge origin/main, resolve conflicts [#{issue_num}]"],
        cwd=clone_dir, capture_output=True,
    )

    if tier2_count > 0:
        verdict = "tier2"
    elif tier1_count > 0:
        verdict = "tier1"
    else:
        verdict = "clean_merge"

    _write_artifact(artifact_path, verdict, len(conflicted),
                    tier1_count, tier2_count, 0)
    return 0
```

**Step 2.3 — Verify deconflict tests pass**

```bash
PYTHONPATH=dark-factory/scripts python -m pytest dark-factory/tests/test_factory_core_deconflict.py -v
# Expected: 15 passed
```

**Step 2.4 — Commit**

```bash
git add dark-factory/scripts/factory_core/deconflict.py \
        dark-factory/tests/test_factory_core_deconflict.py
git commit -m "feat(#337): add deconflict.py with tier1/tier2/hard_grep_survivors"
```

---

## Task 3 — breaker.py + tests

**Files:** `dark-factory/scripts/factory_core/breaker.py`, `dark-factory/tests/test_factory_core_breaker.py`

### Steps

**Step 3.1 — Write failing breaker tests**

Create `dark-factory/tests/test_factory_core_breaker.py`:

```python
import json
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from factory_core.breaker import (
    get_retry_count, increment_retry, reset_retry, trip_to_blocked,
)


def test_get_retry_count_missing_file(tmp_path):
    assert get_retry_count("42:refine", tmp_path / "state.json") == 0


def test_increment_creates_key(tmp_path):
    sf = tmp_path / "state.json"
    assert increment_retry("42:refine", sf) == 1
    assert get_retry_count("42:refine", sf) == 1


def test_increment_accumulates(tmp_path):
    sf = tmp_path / "state.json"
    increment_retry("42:refine", sf)
    increment_retry("42:refine", sf)
    assert get_retry_count("42:refine", sf) == 2


def test_increment_does_not_affect_other_keys(tmp_path):
    sf = tmp_path / "state.json"
    increment_retry("42:refine", sf)
    increment_retry("42:plan", sf)
    assert get_retry_count("42:refine", sf) == 1
    assert get_retry_count("42:plan", sf) == 1


def test_reset_removes_key(tmp_path):
    sf = tmp_path / "state.json"
    increment_retry("42:refine", sf)
    reset_retry("42:refine", sf)
    assert get_retry_count("42:refine", sf) == 0


def test_reset_noop_when_missing(tmp_path):
    sf = tmp_path / "state.json"
    reset_retry("42:refine", sf)  # should not raise


def test_implement_key_is_bare_issue_number(tmp_path):
    # implement phase → bare key "42", not "42:implement"
    sf = tmp_path / "state.json"
    increment_retry("42", sf)
    assert get_retry_count("42", sf) == 1
    assert get_retry_count("42:implement", sf) == 0


def test_state_file_is_valid_json(tmp_path):
    sf = tmp_path / "state.json"
    increment_retry("42:refine", sf)
    data = json.loads(sf.read_text())
    assert data == {"42:refine": 1}


def test_atomic_write_survives_existing_file(tmp_path):
    sf = tmp_path / "state.json"
    sf.write_text('{"existing": 5}')
    increment_retry("42:refine", sf)
    data = json.loads(sf.read_text())
    assert data["existing"] == 5
    assert data["42:refine"] == 1


def test_trip_to_blocked_resets_retry(tmp_path, monkeypatch):
    sf = tmp_path / "state.json"
    increment_retry("42", sf)
    monkeypatch.setattr(subprocess, "run",
        lambda cmd, **kw: subprocess.CompletedProcess([], 0, stdout="", stderr=""))
    with patch("factory_core.board.set_board_status"):
        trip_to_blocked(42, "implement", "test reason", sf)
    assert get_retry_count("42", sf) == 0


def test_trip_to_blocked_phase_key_naming(tmp_path, monkeypatch):
    sf = tmp_path / "state.json"
    increment_retry("42:refine", sf)
    monkeypatch.setattr(subprocess, "run",
        lambda cmd, **kw: subprocess.CompletedProcess([], 0, stdout="", stderr=""))
    with patch("factory_core.board.set_board_status"):
        trip_to_blocked(42, "refine", "test reason", sf)
    assert get_retry_count("42:refine", sf) == 0


def test_trip_to_blocked_posts_comment(tmp_path, monkeypatch):
    sf = tmp_path / "state.json"
    calls = []
    monkeypatch.setattr(subprocess, "run",
        lambda cmd, **kw: (calls.append(cmd),
                           subprocess.CompletedProcess([], 0, stdout="", stderr=""))[1])
    with patch("factory_core.board.set_board_status"):
        trip_to_blocked(42, "plan", "retry limit reached", sf)
    assert any("comment" in " ".join(c) for c in calls)
```

Verify fail:
```bash
PYTHONPATH=dark-factory/scripts python -m pytest dark-factory/tests/test_factory_core_breaker.py -v 2>&1 | head -10
```

**Step 3.2 — Implement breaker.py**

Create `dark-factory/scripts/factory_core/breaker.py`:

```python
import json
import os
import subprocess
from pathlib import Path

_DEFAULT_STATE = Path(
    os.environ.get("STATE_FILE", "/var/lib/dark-factory/scheduler-state.json")
)


def get_retry_count(key: str, state_file: Path = _DEFAULT_STATE) -> int:
    if not state_file.exists():
        return 0
    try:
        return int(json.loads(state_file.read_text()).get(key, 0))
    except (json.JSONDecodeError, ValueError, OSError):
        return 0


def increment_retry(key: str, state_file: Path = _DEFAULT_STATE) -> int:
    new = get_retry_count(key, state_file) + 1
    _write_key(key, new, state_file)
    return new


def reset_retry(key: str, state_file: Path = _DEFAULT_STATE) -> None:
    if not state_file.exists():
        return
    try:
        data = json.loads(state_file.read_text())
        data.pop(key, None)
        _atomic_write(state_file, data)
    except (json.JSONDecodeError, OSError):
        pass


def _write_key(key: str, value: int, state_file: Path) -> None:
    state_file.parent.mkdir(parents=True, exist_ok=True)
    try:
        data = json.loads(state_file.read_text()) if state_file.exists() else {}
        data[key] = value
        _atomic_write(state_file, data)
    except (json.JSONDecodeError, OSError):
        pass


def _atomic_write(path: Path, data: dict) -> None:
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data))
    tmp.rename(path)


def _make_key(issue_num: int, phase: str) -> str:
    return str(issue_num) if phase == "implement" else f"{issue_num}:{phase}"


def trip_to_blocked(
    issue_num: int,
    phase: str,
    reason: str,
    state_file: Path = _DEFAULT_STATE,
    owner: str = "omniscient",
    repo: str = "markethawk",
) -> None:
    from .board import set_board_status, STATUS_BLOCKED

    key = _make_key(issue_num, phase)
    attempts = get_retry_count(key, state_file)

    retry_cmds = {
        "refine": f"Refine issue #{issue_num}",
        "plan": f"Plan issue #{issue_num}",
        "resolve": f"Deconflict issue #{issue_num}",
    }
    retry_cmd = retry_cmds.get(phase, f"Fix issue #{issue_num}")

    set_board_status(issue_num, STATUS_BLOCKED)

    for label in ("needs-discussion", "factory-regression"):
        subprocess.run(
            ["gh", "issue", "edit", str(issue_num),
             "--repo", f"{owner}/{repo}", "--add-label", label],
            capture_output=True,
        )

    body = (
        f"## Scheduler — Circuit-Breaker Tripped (`{phase}`)\n\n"
        f"The scheduler attempted **{phase}** **{attempts} time(s)** without success "
        f"and cannot recover automatically.\n\n"
        f"**Reason:** {reason}\n\n"
        "This ticket has been moved to **Blocked** and labelled `needs-discussion` "
        "to pause automation.\n\n"
        "**To resume:**\n"
        "1. Investigate the failure comments above and fix the root cause.\n"
        "2. Remove the `needs-discussion` label — the scheduler resumes on its next poll.\n\n"
        "```bash\n"
        f"# Or re-run manually:\n"
        f"docker compose --profile factory run --rm dark-factory \"{retry_cmd}\"\n"
        "```\n\n"
        "---\n*Posted by MarketHawk Backlog Scheduler*"
    )
    subprocess.run(
        ["gh", "issue", "comment", str(issue_num),
         "--repo", f"{owner}/{repo}", "--body", body],
        capture_output=True,
    )

    reset_retry(key, state_file)
```

**Step 3.3 — Verify breaker tests pass**

```bash
PYTHONPATH=dark-factory/scripts python -m pytest dark-factory/tests/test_factory_core_breaker.py -v
# Expected: 13 passed
```

**Step 3.4 — Commit**

```bash
git add dark-factory/scripts/factory_core/breaker.py \
        dark-factory/tests/test_factory_core_breaker.py
git commit -m "feat(#337): add breaker.py with retry state and trip_to_blocked"
```

---

## Task 4 — Move run_record.py into package + update test import

**Files:** `dark-factory/scripts/factory_core/run_record.py` (moved), `dark-factory/tests/test_run_record.py`

### Steps

**Step 4.1 — Move the file**

```bash
git mv dark-factory/scripts/run_record.py \
        dark-factory/scripts/factory_core/run_record.py
```

**Step 4.2 — Update test import**

In `dark-factory/tests/test_run_record.py`, replace lines 7–8:

Old:
```python
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import run_record as rr
```

New:
```python
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from factory_core import run_record as rr
```

**Step 4.3 — Verify run_record tests still pass**

```bash
PYTHONPATH=dark-factory/scripts python -m pytest dark-factory/tests/test_run_record.py -v
# Expected: all existing tests pass (no failures)
```

**Step 4.4 — Commit**

```bash
git add dark-factory/scripts/factory_core/run_record.py \
        dark-factory/tests/test_run_record.py
git commit -m "feat(#337): move run_record.py into factory_core package; update test import"
```

---

## Task 5 — cli.py

**Files:** `dark-factory/scripts/factory_core/cli.py`

### Steps

**Step 5.1 — Create cli.py**

```python
#!/usr/bin/env python3
"""factory_core CLI — thin dispatch layer for shell adapters."""
import argparse
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def _board_move(args):
    from factory_core.board import set_board_status
    set_board_status(args.issue, args.status)


def _deconflict(args):
    from factory_core.deconflict import resolve_merge_conflicts
    clone_dir = os.environ.get("CLONE_DIR", "/workspace/markethawk")
    artifacts_dir = os.environ.get("ARTIFACTS_DIR", f"/tmp/artifacts/{args.issue}")
    if args.repo:
        owner, _, repo = args.repo.partition("/")
    else:
        owner = os.environ.get("FACTORY_OWNER", "omniscient")
        repo = os.environ.get("FACTORY_REPO", "markethawk")
    rc = resolve_merge_conflicts(
        issue_num=args.issue,
        clone_dir=clone_dir,
        owner=owner,
        repo=repo,
        artifacts_dir=artifacts_dir,
        ai_tier=not args.no_ai_tier,
    )
    sys.exit(rc)


def _breaker_get(args):
    from factory_core.breaker import get_retry_count
    state_file = Path(os.environ.get("STATE_FILE",
                                     "/var/lib/dark-factory/scheduler-state.json"))
    print(get_retry_count(args.key, state_file))


def _breaker_incr(args):
    from factory_core.breaker import increment_retry
    state_file = Path(os.environ.get("STATE_FILE",
                                     "/var/lib/dark-factory/scheduler-state.json"))
    print(increment_retry(args.key, state_file))


def _breaker_reset(args):
    from factory_core.breaker import reset_retry
    state_file = Path(os.environ.get("STATE_FILE",
                                     "/var/lib/dark-factory/scheduler-state.json"))
    reset_retry(args.key, state_file)


def _breaker_trip(args):
    from factory_core.breaker import trip_to_blocked
    state_file = Path(os.environ.get("STATE_FILE",
                                     "/var/lib/dark-factory/scheduler-state.json"))
    trip_to_blocked(
        issue_num=args.issue,
        phase=args.phase,
        reason=args.reason,
        state_file=state_file,
    )


def _run_record(args):
    sys.argv = ["run_record"] + args.run_record_args
    from factory_core import run_record
    run_record.main()


def main():
    parser = argparse.ArgumentParser(prog="factory-core")
    sub = parser.add_subparsers(dest="cmd", required=True)

    bm = sub.add_parser("board-move")
    bm.add_argument("--issue", type=int, required=True)
    bm.add_argument("--status", required=True)
    bm.set_defaults(func=_board_move)

    dc = sub.add_parser("deconflict")
    dc.add_argument("--issue", type=int, required=True)
    dc.add_argument("--repo", default="")
    dc.add_argument("--no-ai-tier", action="store_true")
    dc.set_defaults(func=_deconflict)

    bg = sub.add_parser("breaker-get")
    bg.add_argument("--key", required=True)
    bg.set_defaults(func=_breaker_get)

    bi = sub.add_parser("breaker-incr")
    bi.add_argument("--key", required=True)
    bi.set_defaults(func=_breaker_incr)

    br = sub.add_parser("breaker-reset")
    br.add_argument("--key", required=True)
    br.set_defaults(func=_breaker_reset)

    bt = sub.add_parser("breaker-trip")
    bt.add_argument("--issue", type=int, required=True)
    bt.add_argument("--phase", required=True)
    bt.add_argument("--reason", required=True)
    bt.set_defaults(func=_breaker_trip)

    rr = sub.add_parser("run-record")
    rr.add_argument("run_record_args", nargs=argparse.REMAINDER)
    rr.set_defaults(func=_run_record)

    parsed = parser.parse_args()
    parsed.func(parsed)


if __name__ == "__main__":
    main()
```

**Step 5.2 — Smoke-test CLI**

```bash
PYTHONPATH=dark-factory/scripts python dark-factory/scripts/factory_core/cli.py --help
# Expected: usage: factory-core [-h] {board-move,deconflict,breaker-get,...} ...

PYTHONPATH=dark-factory/scripts python dark-factory/scripts/factory_core/cli.py breaker-get --help
# Expected: usage: factory-core breaker-get [-h] --key KEY
```

**Step 5.3 — Commit**

```bash
git add dark-factory/scripts/factory_core/cli.py
git commit -m "feat(#337): add factory_core cli.py with argparse dispatch"
```

---

## Task 6 — Slim entrypoint.sh

**Files:** `dark-factory/entrypoint.sh`

Remove `_conflict_tier1`, `_conflict_tier2`, `_conflict_escalate`, and replace `_resolve_merge_conflicts` body with a thin adapter. Keep `find_board_item`, `set_board_status`, `post_or_update_comment` as shell functions (invoked pre-clone). Keep all `STATUS_*` and board constants (still needed for pre-clone board ops).

### Steps

**Step 6.0 — Verify extracted constants match source files**

Before any edits, confirm the constants in `board.py` match what's in `entrypoint.sh` and `scheduler.sh`:

```bash
grep -E "PROJECT_ID=|STATUS_FIELD=|STATUS_IN_PROGRESS=|STATUS_IN_REVIEW=|STATUS_BLOCKED=" \
  dark-factory/entrypoint.sh dark-factory/scheduler.sh

# Expected output:
# dark-factory/entrypoint.sh:PROJECT_ID="PVT_kwHOAAFds84BWh4w"
# dark-factory/entrypoint.sh:STATUS_FIELD="PVTSSF_lAHOAAFds84BWh4wzhR1VaA"
# dark-factory/entrypoint.sh:STATUS_IN_PROGRESS="47fc9ee4"
# dark-factory/entrypoint.sh:STATUS_IN_REVIEW="df73e18b"
# dark-factory/entrypoint.sh:STATUS_BLOCKED="93d87b2f"
# dark-factory/scheduler.sh:PROJECT_ID="PVT_kwHOAAFds84BWh4w"
# dark-factory/scheduler.sh:STATUS_FIELD="PVTSSF_lAHOAAFds84BWh4wzhR1VaA"
# dark-factory/scheduler.sh:STATUS_IN_PROGRESS="47fc9ee4"
# dark-factory/scheduler.sh:STATUS_IN_REVIEW="df73e18b"
# dark-factory/scheduler.sh:STATUS_BLOCKED="93d87b2f"

# If any value differs from board.py, update board.py before proceeding.
```

**Step 6.1 — Replace `_resolve_merge_conflicts` body**

Find the function at ~line 506. Replace the entire body (keeping the function declaration) with the Python delegation:

Old body (lines ~507–585 — the multi-tier bash logic):
```bash
_resolve_merge_conflicts() {
  echo "[deconflict] Fetching origin/main..."
  git fetch origin main 2>&1 || true
  ... (entire ~80-line body) ...
}
```

New:
```bash
_resolve_merge_conflicts() {
  python3 "$CLONE_DIR/dark-factory/scripts/factory_core/cli.py" \
    deconflict --issue "$ISSUE_NUM" || return $?
}
```

**Step 6.2 — Delete the three tier helper functions**

Delete these three complete function blocks from entrypoint.sh:
- `_conflict_tier1()` (lines ~393–437, ~45 lines)
- `_conflict_tier2()` (lines ~441–476, ~36 lines)
- `_conflict_escalate()` (lines ~480–501, ~22 lines)

After deletion verify the file compiles:
```bash
bash -n dark-factory/entrypoint.sh
# Expected: no output (syntax OK)
```

**Step 6.3 — Verify line count dropped substantially**

```bash
wc -l dark-factory/entrypoint.sh
# Before: ~808 lines. After removing ~130 lines of tier functions + 80 lines body → ~600 lines.
```

**Step 6.4 — Commit**

```bash
git add dark-factory/entrypoint.sh
git commit -m "feat(#337): slim entrypoint.sh — delegate _resolve_merge_conflicts to factory_core"
```

---

## Task 7 — Slim scheduler.sh

**Files:** `dark-factory/scheduler.sh`

Replace 5 functions with thin adapters per spec. Remove `PROJECT_ID` and `STATUS_FIELD` constants (now internal to board.py). Keep all `STATUS_*` option IDs (still passed as arguments).

### Steps

**Step 7.1 — Replace `set_board_status`**

Old (lines ~407–417):
```bash
set_board_status() {
  local issue_num="$1"
  local option_id="$2"
  local item_id
  item_id=$(gh project item-list "$PROJECT_NUMBER" --owner "$OWNER" --format json --limit 200 2>/dev/null \
    | jq -r ".items[] | select(.content.number == $issue_num and .content.type == \"Issue\") | .id")
  if [ -n "$item_id" ]; then
    gh project item-edit --project-id "$PROJECT_ID" --id "$item_id" \
      --field-id "$STATUS_FIELD" --single-select-option-id "$option_id" >/dev/null 2>&1 || true
  fi
}
```

New:
```bash
set_board_status() {
  local issue_num="$1" option_id="$2"
  python3 "$CLONE_DIR/dark-factory/scripts/factory_core/cli.py" \
    board-move --issue "$issue_num" --status "$option_id" || true
}
```

**Step 7.2 — Replace `get_retry_count`, `increment_retry`, `reset_retry`**

Old (lines ~103–123):
```bash
get_retry_count() {
  local issue_num="$1"
  jq -r --arg n "$issue_num" '.[$n] // 0' "$STATE_FILE"
}
increment_retry() {
  local issue_num="$1"
  local current
  current=$(get_retry_count "$issue_num")
  local new_count=$((current + 1))
  local tmp
  tmp=$(mktemp)
  jq --arg n "$issue_num" --argjson c "$new_count" '.[$n] = $c' "$STATE_FILE" > "$tmp" && mv "$tmp" "$STATE_FILE"
}
reset_retry() {
  local issue_num="$1"
  local tmp
  tmp=$(mktemp)
  jq --arg n "$issue_num" 'del(.[$n])' "$STATE_FILE" > "$tmp" && mv "$tmp" "$STATE_FILE"
}
```

New:
```bash
get_retry_count() {
  python3 "$CLONE_DIR/dark-factory/scripts/factory_core/cli.py" \
    breaker-get --key "$1"
}
increment_retry() {
  python3 "$CLONE_DIR/dark-factory/scripts/factory_core/cli.py" \
    breaker-incr --key "$1"
}
reset_retry() {
  python3 "$CLONE_DIR/dark-factory/scripts/factory_core/cli.py" \
    breaker-reset --key "$1"
}
```

**Step 7.3 — Replace `trip_to_blocked`**

Old (lines ~424–484, ~61 lines):
```bash
trip_to_blocked() {
  local issue_num="$1"
  local phase="$2"
  local reason="${3:-repeated dispatch failure}"
  ... (full 61-line body) ...
}
```

New:
```bash
trip_to_blocked() {
  python3 "$CLONE_DIR/dark-factory/scripts/factory_core/cli.py" \
    breaker-trip --issue "$1" --phase "$2" --reason "$3" || true
}
```

**Step 7.4 — Remove `PROJECT_ID` and `STATUS_FIELD` constants**

These are now internalized in `board.py`. Find and remove:
```bash
PROJECT_ID="PVT_kwHOAAFds84BWh4w"
STATUS_FIELD="PVTSSF_lAHOAAFds84BWh4wzhR1VaA"
```

Verify no remaining references in scheduler.sh:
```bash
grep -n "PROJECT_ID\|STATUS_FIELD" dark-factory/scheduler.sh
# Expected: no output
```

**Step 7.5 — Syntax-check and commit**

```bash
bash -n dark-factory/scheduler.sh
# Expected: no output

wc -l dark-factory/scheduler.sh
# Before: ~1102 lines. After removing ~100 lines of logic → ~1000 lines.

git add dark-factory/scheduler.sh
git commit -m "feat(#337): slim scheduler.sh — delegate board/breaker ops to factory_core"
```

---

## Task 8 — Replace DAG de-conflict node body

**Files:** `.archon/workflows/archon-dark-factory.yaml`

Replace the ~135-line `de-conflict` node bash body with a single Python call. Preserve all existing node metadata: `depends_on`, `trigger_rule: none_failed_min_one_success`, `when`, `timeout`.

### Steps

**Step 8.1 — Locate the node**

```bash
grep -n "id: de-conflict" .archon/workflows/archon-dark-factory.yaml
# Expected: ~line 378
```

**Step 8.2 — Replace node bash body**

Find the `bash: |` block (lines ~379–519) and replace with:

```yaml
  - id: de-conflict
    bash: |
      ISSUE=$(jq -r '.resolved_number' "$ARTIFACTS_DIR/issue.json")
      ARTIFACTS_DIR="${ARTIFACTS_DIR:-/tmp/artifacts/${ISSUE}}"
      mkdir -p "$ARTIFACTS_DIR"
      python3 "$CLONE_DIR/dark-factory/scripts/factory_core/cli.py" \
        deconflict --issue "$ISSUE"
    depends_on: [regen-codeindex, setup-branch-resolve]
    trigger_rule: none_failed_min_one_success
    when: $parse-intent.output.intent == 'continue' || $parse-intent.output.intent == 'resolve'
    timeout: 300000
```

**Step 8.3 — Validate YAML**

```bash
python3 -c "import yaml; yaml.safe_load(open('.archon/workflows/archon-dark-factory.yaml'))"
# Expected: no output (valid YAML)
```

**Step 8.4 — Run DAG check**

```bash
PYTHONPATH=dark-factory/scripts python3 -c "
from check_workflow_dag import check
errors = check('.archon/workflows/archon-dark-factory.yaml')
if errors:
    for e in errors: print(e)
else:
    print('DAG check passed')
"
# Expected: DAG check passed
```

**Step 8.5 — Commit**

```bash
git add .archon/workflows/archon-dark-factory.yaml
git commit -m "feat(#337): replace DAG de-conflict node with factory_core cli.py delegation"
```

---

## Task 9 — Add factory-tests CI job

**Files:** `.github/workflows/ci.yml`

### Steps

**Step 9.1 — Append new job**

In `.github/workflows/ci.yml`, after the `migration-check` job, add:

```yaml
  factory-tests:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"

      - name: Install test deps
        run: pip install pytest pytest-mock

      - name: Run factory tests
        run: python -m pytest dark-factory/tests/ -v
        env:
          PYTHONPATH: dark-factory/scripts
```

**Step 9.2 — Validate YAML**

```bash
python3 -c "import yaml; yaml.safe_load(open('.github/workflows/ci.yml'))"
# Expected: no output
```

**Step 9.3 — Run factory tests locally to confirm**

```bash
PYTHONPATH=dark-factory/scripts python -m pytest dark-factory/tests/ -v
# Expected: all factory_core tests pass (board, deconflict, breaker, run_record)
```

**Step 9.4 — Commit**

```bash
git add .github/workflows/ci.yml
git commit -m "feat(#337): add factory-tests CI job for dark-factory/tests/"
```

---

## Task Summary

| # | Task | Files | Key Steps |
|---|------|-------|-----------|
| 1 | Package skeleton + board.py + tests | 3 new | Tests → skeleton → board.py → verify |
| 2 | deconflict.py + tests | 2 new | Tests (tier1/2/hard_grep) → impl → verify |
| 3 | breaker.py + tests | 2 new | Tests (retry state + trip) → impl → verify |
| 4 | Move run_record.py + update import | 1 move + 1 edit | `git mv` → fix import → verify |
| 5 | cli.py | 1 new | Implement → smoke-test |
| 6 | Slim entrypoint.sh | 1 edit | Replace body + delete tier fns |
| 7 | Slim scheduler.sh | 1 edit | Replace 5 fns + remove 2 constants |
| 8 | Replace DAG de-conflict node | 1 edit | Replace bash body → validate YAML + DAG |
| 9 | Add factory-tests CI job | 1 edit | Add job → validate YAML → run locally |

**Total tasks:** 9 | **Total steps:** 33

---

*Plan generated by MarketHawk Refinement Pipeline — 2026-06-13*
