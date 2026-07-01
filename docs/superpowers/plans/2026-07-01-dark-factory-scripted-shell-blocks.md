# Plan: Extract Repeated Shell Blocks into Dark Factory Scripts

**Issue:** #670  
**Spec:** `docs/superpowers/specs/2026-07-01-dark-factory-scripted-shell-blocks-design.md`  
**Date:** 2026-07-01  
**Size:** M  

## Goal

Extract two copy-pasted shell blocks shared across dark-factory command files into standalone,
tested bash scripts in `dark-factory/scripts/`. Replace the inline blocks with one-liner
call-sites. Behavior is byte-for-byte equivalent to the original; no guard semantics change.

The two targets:
- **Memory-load block** — identical in `dark-factory-refine.md` (lines 39–55),
  `dark-factory-plan.md` (lines 31–47), and `dark-factory-implement.md` (lines 31–47);
  only `--phase` differs.
- **OOS gate block** — near-identical in `dark-factory-refine.md` (lines 111–136) and
  `dark-factory-plan.md` (lines 158–182); differs in `ALLOWED_PREFIXES` and commit noun.

## Architecture

Both scripts live in `dark-factory/scripts/`, following the `check_preview_creds.sh` /
`eval_agentmemory.sh` precedent (standalone bash, not `gate_lib.sh` functions). Tests use
`subprocess.run` in `tmp_path`-scoped git fixtures, following `test_memory_retrieve.py`
lines 924–945, so they run in the `factory-tests` CI job without CI config changes.

## Tech Stack

- **Scripts**: bash 5+ (no new dependencies)
- **Tests**: pytest + subprocess + tmp_path git fixtures (stdlib only)

## File Structure

| File | Action | Purpose |
|------|--------|---------|
| `dark-factory/scripts/load_memory_context.sh` | Create | Extracted memory-load block |
| `dark-factory/scripts/oos_excise.sh` | Create | Extracted OOS gate block |
| `dark-factory/tests/test_load_memory_context.py` | Create | pytest subprocess tests |
| `dark-factory/tests/test_oos_excise.py` | Create | pytest subprocess tests + behavior-parity test |
| `.archon/commands/dark-factory-refine.md` | Edit | Replace memory-load (39–55) and OOS (111–136) blocks |
| `.archon/commands/dark-factory-plan.md` | Edit | Replace memory-load (31–47) and OOS (158–182) blocks |
| `.archon/commands/dark-factory-implement.md` | Edit | Replace memory-load (31–47) block |

---

## Task 1: Write and test `load_memory_context.sh`

**Files:** `dark-factory/scripts/load_memory_context.sh`, `dark-factory/tests/test_load_memory_context.py`  
**Time:** ~45 min

### Step 1a — Write the failing test file

Create `dark-factory/tests/test_load_memory_context.py`:

```python
"""Tests for dark-factory/scripts/load_memory_context.sh."""
import os
import subprocess
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "load_memory_context.sh"
REPO_ROOT = Path(__file__).resolve().parents[2]


def _make_env(tmp_path, *, issue_num="670", artifacts_dir=None, repo_root=None):
    if artifacts_dir is None:
        artifacts_dir = tmp_path / "artifacts"
        artifacts_dir.mkdir(exist_ok=True)
    if repo_root is None:
        repo_root = REPO_ROOT
    return {
        **os.environ,
        "ARTIFACTS_DIR": str(artifacts_dir),
        "ISSUE_NUM": str(issue_num),
        "REPO_ROOT": str(repo_root),
    }


class TestLoadMemoryContextHappyPath:
    def test_exits_zero(self, tmp_path):
        result = subprocess.run(
            ["bash", str(SCRIPT), "plan"],
            capture_output=True,
            text=True,
            env=_make_env(tmp_path),
        )
        assert result.returncode == 0, result.stderr

    def test_writes_memory_context_md(self, tmp_path):
        artifacts = tmp_path / "artifacts"
        artifacts.mkdir()
        subprocess.run(
            ["bash", str(SCRIPT), "plan"],
            capture_output=True,
            text=True,
            env=_make_env(tmp_path, artifacts_dir=artifacts),
            check=True,
        )
        assert (artifacts / "memory-context.md").exists()

    def test_stdout_matches_memory_context_md(self, tmp_path):
        artifacts = tmp_path / "artifacts"
        artifacts.mkdir()
        result = subprocess.run(
            ["bash", str(SCRIPT), "plan"],
            capture_output=True,
            text=True,
            env=_make_env(tmp_path, artifacts_dir=artifacts),
        )
        file_content = (artifacts / "memory-context.md").read_text()
        assert result.stdout.rstrip("\n") == file_content.rstrip("\n")

    def test_writes_memory_trace_json_when_retrieve_succeeds(self, tmp_path):
        artifacts = tmp_path / "artifacts"
        artifacts.mkdir()
        subprocess.run(
            ["bash", str(SCRIPT), "plan"],
            capture_output=True,
            text=True,
            env=_make_env(tmp_path, artifacts_dir=artifacts),
        )
        # memory-trace.json is written by memory_retrieve.py on success
        assert (artifacts / "memory-trace.json").exists()


class TestLoadMemoryContextFailSoft:
    def test_exits_zero_when_repo_root_missing(self, tmp_path):
        artifacts = tmp_path / "artifacts"
        artifacts.mkdir()
        env = _make_env(tmp_path, artifacts_dir=artifacts, repo_root=tmp_path / "nonexistent")
        result = subprocess.run(
            ["bash", str(SCRIPT), "plan"],
            capture_output=True,
            text=True,
            env=env,
        )
        assert result.returncode == 0

    def test_writes_empty_context_md_when_retrieve_fails(self, tmp_path):
        artifacts = tmp_path / "artifacts"
        artifacts.mkdir()
        env = _make_env(tmp_path, artifacts_dir=artifacts, repo_root=tmp_path / "nonexistent")
        subprocess.run(["bash", str(SCRIPT), "plan"], capture_output=True, text=True, env=env)
        assert (artifacts / "memory-context.md").exists()

    def test_exits_zero_without_issue_num(self, tmp_path):
        artifacts = tmp_path / "artifacts"
        artifacts.mkdir()
        env = _make_env(tmp_path, artifacts_dir=artifacts)
        del env["ISSUE_NUM"]
        result = subprocess.run(
            ["bash", str(SCRIPT), "plan"],
            capture_output=True,
            text=True,
            env=env,
        )
        assert result.returncode == 0


class TestLoadMemoryContextPhases:
    def test_accepts_refine_phase(self, tmp_path):
        result = subprocess.run(
            ["bash", str(SCRIPT), "refine"],
            capture_output=True,
            text=True,
            env=_make_env(tmp_path),
        )
        assert result.returncode == 0

    def test_accepts_implement_phase(self, tmp_path):
        result = subprocess.run(
            ["bash", str(SCRIPT), "implement"],
            capture_output=True,
            text=True,
            env=_make_env(tmp_path),
        )
        assert result.returncode == 0

    def test_fails_without_phase_arg(self, tmp_path):
        env = _make_env(tmp_path)
        result = subprocess.run(
            ["bash", str(SCRIPT)],
            capture_output=True,
            text=True,
            env=env,
        )
        assert result.returncode != 0
```

### Step 1b — Verify tests fail (script does not exist yet)

```bash
cd /workspace/markethawk
pytest dark-factory/tests/test_load_memory_context.py -v 2>&1 | head -30
```

Expected: errors like `No such file or directory: 'dark-factory/scripts/load_memory_context.sh'`

### Step 1c — Write `load_memory_context.sh`

Create `dark-factory/scripts/load_memory_context.sh`:

```bash
#!/usr/bin/env bash
# Wrapper for the memory-load block shared by dark-factory refine/plan/implement commands.
# Usage: bash "${REPO_ROOT}/dark-factory/scripts/load_memory_context.sh" <phase>
# Env: ARTIFACTS_DIR, ISSUE_NUM (optional), REPO_ROOT
# Stdout: memory context string (empty on failure — fail-soft preserved)
# Side effects: $ARTIFACTS_DIR/memory-context.md, $ARTIFACTS_DIR/memory-trace.json

PHASE="${1:?Usage: load_memory_context.sh <phase>}"

cd "${REPO_ROOT}"

AFFECTED=$(git diff --name-only origin/main...HEAD 2>/dev/null || echo "")

ISSUE_ARG=""
[[ "${ISSUE_NUM:-}" =~ ^[0-9]+$ ]] && ISSUE_ARG="--issue ${ISSUE_NUM}"

MEMORY_CONTEXT=$(python3 "${REPO_ROOT}/dark-factory/scripts/memory_retrieve.py" \
  --phase "$PHASE" \
  --files "$AFFECTED" \
  $ISSUE_ARG \
  --memory-dir "${REPO_ROOT}/.archon/memory" \
  --emit-trace-to "${ARTIFACTS_DIR}/memory-trace.json" 2>/dev/null || true)

mkdir -p "${ARTIFACTS_DIR}"
printf '%s\n' "$MEMORY_CONTEXT" > "${ARTIFACTS_DIR}/memory-context.md"
printf '%s\n' "$MEMORY_CONTEXT"
```

Make it executable:

```bash
chmod +x dark-factory/scripts/load_memory_context.sh
```

### Step 1d — Verify tests pass

```bash
pytest dark-factory/tests/test_load_memory_context.py -v
```

Expected output (all pass):
```
PASSED test_exits_zero
PASSED test_writes_memory_context_md
PASSED test_stdout_matches_memory_context_md
PASSED test_writes_memory_trace_json_when_retrieve_succeeds
PASSED test_exits_zero_when_repo_root_missing
PASSED test_writes_empty_context_md_when_retrieve_fails
PASSED test_exits_zero_without_issue_num
PASSED test_accepts_refine_phase
PASSED test_accepts_implement_phase
PASSED test_fails_without_phase_arg
```

### Step 1e — Commit

```bash
git add dark-factory/scripts/load_memory_context.sh dark-factory/tests/test_load_memory_context.py
git commit -m "feat: add load_memory_context.sh with pytest subprocess tests (#670)"
```

---

## Task 2: Write and test `oos_excise.sh`

**Files:** `dark-factory/scripts/oos_excise.sh`, `dark-factory/tests/test_oos_excise.py`  
**Time:** ~60 min

### Step 2a — Write the failing test file

Create `dark-factory/tests/test_oos_excise.py`:

```python
"""Tests for dark-factory/scripts/oos_excise.sh."""
import os
import subprocess
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "oos_excise.sh"


def _make_origin_and_repo(tmp_path):
    """Create a bare origin and a clone with user config and initial push."""
    origin = tmp_path / "origin.git"
    origin.mkdir()
    subprocess.run(["git", "init", "--bare"], cwd=origin, check=True, capture_output=True)

    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(
        ["git", "clone", str(origin), str(repo)], check=True, capture_output=True
    )
    subprocess.run(
        ["git", "config", "user.email", "test@example.com"],
        cwd=repo, check=True, capture_output=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Test"],
        cwd=repo, check=True, capture_output=True,
    )

    # Initial commit on main — becomes origin/main after push
    allowed = repo / "docs" / "superpowers" / "specs"
    allowed.mkdir(parents=True)
    (allowed / "baseline.md").write_text("# baseline\n")
    subprocess.run(["git", "add", "."], cwd=repo, check=True, capture_output=True)
    subprocess.run(
        ["git", "commit", "-m", "initial"], cwd=repo, check=True, capture_output=True
    )
    subprocess.run(
        ["git", "push", "origin", "HEAD:main"], cwd=repo, check=True, capture_output=True
    )
    subprocess.run(
        ["git", "branch", "--set-upstream-to=origin/main"],
        cwd=repo, check=True, capture_output=True,
    )
    return repo


def _make_env(repo, artifacts_dir, issue_num="670"):
    return {
        **os.environ,
        "ARTIFACTS_DIR": str(artifacts_dir),
        "ISSUE_NUM": str(issue_num),
        "REPO_ROOT": str(repo),
        "GIT_AUTHOR_NAME": "Test",
        "GIT_AUTHOR_EMAIL": "test@example.com",
        "GIT_COMMITTER_NAME": "Test",
        "GIT_COMMITTER_EMAIL": "test@example.com",
    }


class TestOosExciseNoViolations:
    def test_exits_zero_no_oos(self, tmp_path):
        repo = _make_origin_and_repo(tmp_path)
        artifacts = tmp_path / "artifacts"
        artifacts.mkdir()

        result = subprocess.run(
            ["bash", str(SCRIPT), "docs/superpowers/specs/", "refine"],
            capture_output=True,
            text=True,
            env=_make_env(repo, artifacts),
            cwd=repo,
        )
        assert result.returncode == 0

    def test_stdout_empty_when_no_oos(self, tmp_path):
        repo = _make_origin_and_repo(tmp_path)
        artifacts = tmp_path / "artifacts"
        artifacts.mkdir()

        result = subprocess.run(
            ["bash", str(SCRIPT), "docs/superpowers/specs/", "refine"],
            capture_output=True,
            text=True,
            env=_make_env(repo, artifacts),
            cwd=repo,
        )
        assert result.stdout.strip() == ""

    def test_no_out_of_scope_md_when_no_violations(self, tmp_path):
        repo = _make_origin_and_repo(tmp_path)
        artifacts = tmp_path / "artifacts"
        artifacts.mkdir()

        subprocess.run(
            ["bash", str(SCRIPT), "docs/superpowers/specs/", "refine"],
            capture_output=True,
            text=True,
            env=_make_env(repo, artifacts),
            cwd=repo,
        )
        assert not (artifacts / "out-of-scope.md").exists()

    def test_allowed_file_not_excised(self, tmp_path):
        repo = _make_origin_and_repo(tmp_path)
        artifacts = tmp_path / "artifacts"
        artifacts.mkdir()

        (repo / "docs" / "superpowers" / "specs" / "new-spec.md").write_text("# new\n")
        subprocess.run(["git", "add", "."], cwd=repo, check=True, capture_output=True)
        subprocess.run(
            ["git", "commit", "-m", "add spec"], cwd=repo, check=True, capture_output=True
        )

        result = subprocess.run(
            ["bash", str(SCRIPT), "docs/superpowers/specs/", "refine"],
            capture_output=True,
            text=True,
            env=_make_env(repo, artifacts),
            cwd=repo,
        )
        assert "new-spec.md" not in result.stdout


class TestOosExciseWithViolations:
    def _add_oos_commit(self, repo):
        (repo / "README.md").write_text("# readme\n")
        subprocess.run(["git", "add", "."], cwd=repo, check=True, capture_output=True)
        subprocess.run(
            ["git", "commit", "-m", "add readme"], cwd=repo, check=True, capture_output=True
        )

    def test_oos_filename_on_stdout(self, tmp_path):
        repo = _make_origin_and_repo(tmp_path)
        artifacts = tmp_path / "artifacts"
        artifacts.mkdir()
        self._add_oos_commit(repo)

        result = subprocess.run(
            ["bash", str(SCRIPT), "docs/superpowers/specs/", "refine"],
            capture_output=True,
            text=True,
            env=_make_env(repo, artifacts),
            cwd=repo,
        )
        assert "README.md" in result.stdout

    def test_out_of_scope_md_written(self, tmp_path):
        repo = _make_origin_and_repo(tmp_path)
        artifacts = tmp_path / "artifacts"
        artifacts.mkdir()
        self._add_oos_commit(repo)

        subprocess.run(
            ["bash", str(SCRIPT), "docs/superpowers/specs/", "refine"],
            capture_output=True,
            text=True,
            env=_make_env(repo, artifacts),
            cwd=repo,
        )
        assert (artifacts / "out-of-scope.md").exists()
        content = (artifacts / "out-of-scope.md").read_text()
        assert "README.md" in content
        assert "refine OOS gate" in content

    def test_excision_commit_created(self, tmp_path):
        repo = _make_origin_and_repo(tmp_path)
        artifacts = tmp_path / "artifacts"
        artifacts.mkdir()
        self._add_oos_commit(repo)

        commits_before = subprocess.run(
            ["git", "log", "--oneline"],
            cwd=repo, capture_output=True, text=True,
        ).stdout.strip().splitlines()

        subprocess.run(
            ["bash", str(SCRIPT), "docs/superpowers/specs/", "refine"],
            capture_output=True,
            text=True,
            env=_make_env(repo, artifacts),
            cwd=repo,
        )

        commits_after = subprocess.run(
            ["git", "log", "--oneline"],
            cwd=repo, capture_output=True, text=True,
        ).stdout.strip().splitlines()

        assert len(commits_after) == len(commits_before) + 1

    def test_commit_message_contains_commit_noun(self, tmp_path):
        repo = _make_origin_and_repo(tmp_path)
        artifacts = tmp_path / "artifacts"
        artifacts.mkdir()
        self._add_oos_commit(repo)

        subprocess.run(
            ["bash", str(SCRIPT), "docs/superpowers/specs/", "plan"],
            capture_output=True,
            text=True,
            env=_make_env(repo, artifacts),
            cwd=repo,
        )

        last_msg = subprocess.run(
            ["git", "log", "-1", "--pretty=%s"],
            cwd=repo, capture_output=True, text=True,
        ).stdout.strip()
        assert "plan run" in last_msg

    def test_commit_message_contains_issue_num(self, tmp_path):
        repo = _make_origin_and_repo(tmp_path)
        artifacts = tmp_path / "artifacts"
        artifacts.mkdir()
        self._add_oos_commit(repo)

        subprocess.run(
            ["bash", str(SCRIPT), "docs/superpowers/specs/", "refine"],
            capture_output=True,
            text=True,
            env=_make_env(repo, artifacts, issue_num="42"),
            cwd=repo,
        )

        last_msg = subprocess.run(
            ["git", "log", "-1", "--pretty=%s"],
            cwd=repo, capture_output=True, text=True,
        ).stdout.strip()
        assert "#42" in last_msg

    def test_multiple_allowed_prefixes(self, tmp_path):
        repo = _make_origin_and_repo(tmp_path)
        artifacts = tmp_path / "artifacts"
        artifacts.mkdir()

        mem_dir = repo / ".archon" / "memory"
        mem_dir.mkdir(parents=True)
        (mem_dir / "mem.md").write_text("# memory\n")
        (repo / "README.md").write_text("# readme\n")
        subprocess.run(["git", "add", "."], cwd=repo, check=True, capture_output=True)
        subprocess.run(
            ["git", "commit", "-m", "mixed"], cwd=repo, check=True, capture_output=True
        )

        result = subprocess.run(
            ["bash", str(SCRIPT), "docs/superpowers/specs/ .archon/memory/", "refine"],
            capture_output=True,
            text=True,
            env=_make_env(repo, artifacts),
            cwd=repo,
        )
        assert "README.md" in result.stdout
        assert ".archon/memory/mem.md" not in result.stdout


class TestOosExciseBehaviorParity:
    def test_excised_set_matches_inline_block_logic(self, tmp_path):
        """Parity: oos_excise.sh outputs same file set as the original inline block for given input."""
        repo = _make_origin_and_repo(tmp_path)
        artifacts = tmp_path / "artifacts"
        artifacts.mkdir()

        (repo / "docs" / "superpowers" / "specs" / "new.md").write_text("# new\n")
        (repo / "README.md").write_text("# readme\n")
        (repo / "NOTES.md").write_text("# notes\n")
        subprocess.run(["git", "add", "."], cwd=repo, check=True, capture_output=True)
        subprocess.run(
            ["git", "commit", "-m", "mixed"], cwd=repo, check=True, capture_output=True
        )

        # Compute what the inline block would produce
        all_changed = subprocess.run(
            ["git", "diff", "--name-only", "origin/main", "HEAD"],
            cwd=repo, capture_output=True, text=True,
        ).stdout.strip().splitlines()
        allowed_prefixes = ["docs/superpowers/specs/", ".archon/memory/"]
        expected_oos = {
            f for f in all_changed
            if f and not any(f.startswith(p) for p in allowed_prefixes)
        }

        result = subprocess.run(
            ["bash", str(SCRIPT), "docs/superpowers/specs/ .archon/memory/", "refine"],
            capture_output=True,
            text=True,
            env=_make_env(repo, artifacts),
            cwd=repo,
        )

        excised = set(result.stdout.strip().splitlines()) - {""}
        assert excised == expected_oos
```

### Step 2b — Verify tests fail

```bash
pytest dark-factory/tests/test_oos_excise.py -v 2>&1 | head -30
```

Expected: errors like `No such file or directory: 'dark-factory/scripts/oos_excise.sh'`

### Step 2c — Write `oos_excise.sh`

Create `dark-factory/scripts/oos_excise.sh`:

```bash
#!/usr/bin/env bash
# OOS gate block shared by dark-factory refine and plan commands.
# Usage: bash "${REPO_ROOT}/dark-factory/scripts/oos_excise.sh" "<allowed-prefixes>" <commit-noun>
#   allowed-prefixes: space-separated string, e.g. "docs/superpowers/specs/ .archon/memory/"
#   commit-noun: "refine" or "plan" (appears in commit message and out-of-scope.md)
# Env: ARTIFACTS_DIR, ISSUE_NUM, REPO_ROOT
# Stdout: excised filenames one-per-line; empty if nothing excised
# Side effects: $ARTIFACTS_DIR/out-of-scope.md (if OOS found); excision git commit

ALLOWED_PREFIXES="${1:?Usage: oos_excise.sh <allowed-prefixes> <commit-noun>}"
COMMIT_NOUN="${2:?Usage: oos_excise.sh <allowed-prefixes> <commit-noun>}"

cd "${REPO_ROOT}"

OOS_FILES=$(git diff --name-only origin/main HEAD 2>/dev/null | while read -r f; do
  ALLOWED=false
  for prefix in $ALLOWED_PREFIXES; do
    case "$f" in "$prefix"*) ALLOWED=true; break;; esac
  done
  $ALLOWED || echo "$f"
done)

if [ -n "$OOS_FILES" ]; then
  echo "OOS gate: excising out-of-scope files: $OOS_FILES" >&2
  for f in $OOS_FILES; do
    if git show origin/main:"$f" > /dev/null 2>&1; then
      git checkout origin/main -- "$f"
    else
      git rm -f --cached "$f" 2>/dev/null; rm -f "$f"
    fi
  done
  git commit -m "chore: excise out-of-scope files from ${COMMIT_NOUN} run (#${ISSUE_NUM})" --allow-empty
  mkdir -p "${ARTIFACTS_DIR}"
  echo "$OOS_FILES" | while read -r f; do
    echo "- $f: removed by ${COMMIT_NOUN} OOS gate (should not have been created/modified)" >> "${ARTIFACTS_DIR}/out-of-scope.md"
  done
fi

[ -z "$OOS_FILES" ] || echo "$OOS_FILES"
```

Make it executable:

```bash
chmod +x dark-factory/scripts/oos_excise.sh
```

### Step 2d — Verify tests pass

```bash
pytest dark-factory/tests/test_oos_excise.py -v
```

Expected output (all pass):
```
PASSED test_exits_zero_no_oos
PASSED test_stdout_empty_when_no_oos
PASSED test_no_out_of_scope_md_when_no_violations
PASSED test_allowed_file_not_excised
PASSED test_oos_filename_on_stdout
PASSED test_out_of_scope_md_written
PASSED test_excision_commit_created
PASSED test_commit_message_contains_commit_noun
PASSED test_commit_message_contains_issue_num
PASSED test_multiple_allowed_prefixes
PASSED test_excised_set_matches_inline_block_logic
```

### Step 2e — Run both test files together

```bash
pytest dark-factory/tests/test_load_memory_context.py dark-factory/tests/test_oos_excise.py -v
```

All tests must pass before committing.

### Step 2f — Commit

```bash
git add dark-factory/scripts/oos_excise.sh dark-factory/tests/test_oos_excise.py
git commit -m "feat: add oos_excise.sh with pytest subprocess tests + behavior-parity assertion (#670)"
```

---

## Task 3: Replace inline blocks in command files

**Files:** `.archon/commands/dark-factory-refine.md`, `.archon/commands/dark-factory-plan.md`,
`.archon/commands/dark-factory-implement.md`  
**Time:** ~30 min

### Step 3a — Update `dark-factory-refine.md`

**Edit 1 — Replace memory-load block (lines 39–55).**

Find this exact block (inside a ` ```bash ` fence, starting after line 38 which reads `7. Compute the affected file set and load memory context:`):

```bash
AFFECTED=$(git diff --name-only origin/main...HEAD 2>/dev/null || echo "")
REPO_ROOT=$(git rev-parse --show-toplevel)

ISSUE_ARG=""
[[ "$ISSUE_NUM" =~ ^[0-9]+$ ]] && ISSUE_ARG="--issue $ISSUE_NUM"

MEMORY_CONTEXT=$(python3 "${REPO_ROOT}/dark-factory/scripts/memory_retrieve.py" \
  --phase refine \
  --files "$AFFECTED" \
  $ISSUE_ARG \
  --memory-dir "${REPO_ROOT}/.archon/memory" \
  --emit-trace-to "$ARTIFACTS_DIR/memory-trace.json" 2>/dev/null || true)

mkdir -p "$ARTIFACTS_DIR"
printf '%s\n' "$MEMORY_CONTEXT" > "$ARTIFACTS_DIR/memory-context.md"
```

Replace with:

```bash
REPO_ROOT=$(git rev-parse --show-toplevel)
MEMORY_CONTEXT=$(bash "${REPO_ROOT}/dark-factory/scripts/load_memory_context.sh" refine)
```

**Edit 2 — Replace OOS gate block (lines 111–136).**

Find this exact block (inside a ` ```bash ` fence, starting after line 110 which reads `5. Run the OOS gate — detect and revert any files committed outside the refine allowlist:`):

```bash
ALLOWED_PREFIXES="docs/superpowers/specs/ .archon/memory/"
OOS_FILES=$(git diff --name-only origin/main HEAD 2>/dev/null | while read -r f; do
  ALLOWED=false
  for prefix in $ALLOWED_PREFIXES; do
    case "$f" in "$prefix"*) ALLOWED=true; break;; esac
  done
  $ALLOWED || echo "$f"
done)
if [ -n "$OOS_FILES" ]; then
  echo "OOS gate: excising out-of-scope files: $OOS_FILES"
  for f in $OOS_FILES; do
    if git show origin/main:"$f" > /dev/null 2>&1; then
      git checkout origin/main -- "$f"
    else
      git rm -f --cached "$f" 2>/dev/null; rm -f "$f"
    fi
  done
  git commit -m "chore: excise out-of-scope files from refine run (#$ISSUE_NUM)" --allow-empty
  mkdir -p "$ARTIFACTS_DIR"
  echo "$OOS_FILES" | while read -r f; do
    echo "- $f: removed by refine OOS gate (should not have been created/modified)" >> "$ARTIFACTS_DIR/out-of-scope.md"
  done
fi
```

Replace with:

```bash
OOS_FILES=$(bash "${REPO_ROOT}/dark-factory/scripts/oos_excise.sh" \
  "docs/superpowers/specs/ .archon/memory/" refine)
```

### Step 3b — Update `dark-factory-plan.md`

**Edit 1 — Replace memory-load block (lines 31–47).**

Find this exact block:

```bash
AFFECTED=$(git diff --name-only origin/main...HEAD 2>/dev/null || echo "")
REPO_ROOT=$(git rev-parse --show-toplevel)

ISSUE_ARG=""
[[ "$ISSUE_NUM" =~ ^[0-9]+$ ]] && ISSUE_ARG="--issue $ISSUE_NUM"

MEMORY_CONTEXT=$(python3 "${REPO_ROOT}/dark-factory/scripts/memory_retrieve.py" \
  --phase plan \
  --files "$AFFECTED" \
  $ISSUE_ARG \
  --memory-dir "${REPO_ROOT}/.archon/memory" \
  --emit-trace-to "$ARTIFACTS_DIR/memory-trace.json" 2>/dev/null || true)

mkdir -p "$ARTIFACTS_DIR"
printf '%s\n' "$MEMORY_CONTEXT" > "$ARTIFACTS_DIR/memory-context.md"
```

Replace with:

```bash
REPO_ROOT=$(git rev-parse --show-toplevel)
MEMORY_CONTEXT=$(bash "${REPO_ROOT}/dark-factory/scripts/load_memory_context.sh" plan)
```

**Edit 2 — Replace OOS gate block (lines 158–182).**

Find this exact block (inside a ` ```bash ` fence under Phase 4 step 4):

```bash
ALLOWED_PREFIXES="docs/superpowers/plans/"
OOS_FILES=$(git diff --name-only origin/main HEAD 2>/dev/null | while read -r f; do
  ALLOWED=false
  for prefix in $ALLOWED_PREFIXES; do
    case "$f" in "$prefix"*) ALLOWED=true; break;; esac
  done
  $ALLOWED || echo "$f"
done)
if [ -n "$OOS_FILES" ]; then
  echo "OOS gate: excising out-of-scope files: $OOS_FILES"
  for f in $OOS_FILES; do
    if git show origin/main:"$f" > /dev/null 2>&1; then
      git checkout origin/main -- "$f"
    else
      git rm -f --cached "$f" 2>/dev/null; rm -f "$f"
    fi
  done
  git commit -m "chore: excise out-of-scope files from plan run (#$ISSUE_NUM)" --allow-empty
  mkdir -p "$ARTIFACTS_DIR"
  echo "$OOS_FILES" | while read -r f; do
    echo "- $f: removed by plan OOS gate (should not have been created/modified)" >> "$ARTIFACTS_DIR/out-of-scope.md"
  done
fi
```

Replace with:

```bash
OOS_FILES=$(bash "${REPO_ROOT}/dark-factory/scripts/oos_excise.sh" \
  "docs/superpowers/plans/" plan)
```

### Step 3c — Update `dark-factory-implement.md`

**Edit 1 — Replace memory-load block (lines 31–47).**

Find this exact block:

```bash
AFFECTED=$(git diff --name-only origin/main...HEAD 2>/dev/null || echo "")
REPO_ROOT=$(git rev-parse --show-toplevel)

ISSUE_ARG=""
[[ "$ISSUE_NUM" =~ ^[0-9]+$ ]] && ISSUE_ARG="--issue $ISSUE_NUM"

MEMORY_CONTEXT=$(python3 "${REPO_ROOT}/dark-factory/scripts/memory_retrieve.py" \
  --phase implement \
  --files "$AFFECTED" \
  $ISSUE_ARG \
  --memory-dir "${REPO_ROOT}/.archon/memory" \
  --emit-trace-to "$ARTIFACTS_DIR/memory-trace.json" 2>/dev/null || true)

mkdir -p "$ARTIFACTS_DIR"
printf '%s\n' "$MEMORY_CONTEXT" > "$ARTIFACTS_DIR/memory-context.md"
```

Replace with:

```bash
REPO_ROOT=$(git rev-parse --show-toplevel)
MEMORY_CONTEXT=$(bash "${REPO_ROOT}/dark-factory/scripts/load_memory_context.sh" implement)
```

### Step 3d — Verify no regressions

Run both new test files one final time to confirm they still pass after the command-file edits:

```bash
pytest dark-factory/tests/test_load_memory_context.py dark-factory/tests/test_oos_excise.py -v
```

All tests must pass.

### Step 3e — Spot-check that call-sites exist in each edited file

```bash
grep -n "load_memory_context.sh" .archon/commands/dark-factory-refine.md \
  .archon/commands/dark-factory-plan.md \
  .archon/commands/dark-factory-implement.md
# Expected: one hit per file

grep -n "oos_excise.sh" .archon/commands/dark-factory-refine.md \
  .archon/commands/dark-factory-plan.md
# Expected: one hit per file (implement.md has no OOS block — zero hits there is correct)

grep -n "memory_retrieve.py" .archon/commands/dark-factory-refine.md \
  .archon/commands/dark-factory-plan.md \
  .archon/commands/dark-factory-implement.md
# Expected: only hits in memory_write.py blocks (refine.md Phase 5), NOT in Phase 1 load blocks
```

If `memory_retrieve.py` still appears in lines ~31–55 of plan.md or implement.md, the edit was incomplete — re-apply.

### Step 3f — Commit

```bash
git add .archon/commands/dark-factory-refine.md \
  .archon/commands/dark-factory-plan.md \
  .archon/commands/dark-factory-implement.md
git commit -m "refactor: replace inline memory-load and OOS blocks with script call-sites (#670)"
```

---

## Verification Summary

After all three tasks are complete, confirm:

```bash
# All new tests pass
pytest dark-factory/tests/test_load_memory_context.py dark-factory/tests/test_oos_excise.py -v

# Scripts are executable
test -x dark-factory/scripts/load_memory_context.sh && echo OK
test -x dark-factory/scripts/oos_excise.sh && echo OK

# Inline blocks removed from all three files
grep -c "memory_retrieve.py" .archon/commands/dark-factory-plan.md     # must be 0
grep -c "memory_retrieve.py" .archon/commands/dark-factory-implement.md # must be 0
# (refine.md has memory_retrieve.py in the memory-write section — non-zero is expected there)
grep -c "ALLOWED_PREFIXES=" .archon/commands/dark-factory-refine.md    # must be 0
grep -c "ALLOWED_PREFIXES=" .archon/commands/dark-factory-plan.md      # must be 0
```
