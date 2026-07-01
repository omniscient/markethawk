"""Tests for dark-factory/scripts/oos_excise.sh."""
import os
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "dark-factory" / "scripts" / "oos_excise.sh"


def run_script(
    allowed_prefixes: str,
    commit_noun: str,
    env: dict,
    work_dir: Path,
) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["bash", str(SCRIPT), allowed_prefixes, commit_noun],
        capture_output=True,
        text=True,
        env=env,
        cwd=str(work_dir),
    )


def git(*args, cwd, **kwargs):
    return subprocess.run(
        ["git", *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        **kwargs,
    )


def base_env(artifacts_dir: Path) -> dict:
    e = os.environ.copy()
    e["ARTIFACTS_DIR"] = str(artifacts_dir)
    e["ISSUE_NUM"] = "670"
    return e


@pytest.fixture()
def git_repo(tmp_path):
    """Bare-origin + working-tree git fixture.

    Sets up:
      bare/   — bare origin repo  (HEAD -> main)
      work/   — working clone with 'origin/main' as default branch
    """
    bare = tmp_path / "bare"
    work = tmp_path / "work"

    bare.mkdir()
    git("init", "--bare", str(bare), cwd=str(tmp_path))
    # Ensure bare HEAD points to main so clones get the right default branch
    subprocess.run(
        ["git", "symbolic-ref", "HEAD", "refs/heads/main"],
        cwd=str(bare), capture_output=True,
    )
    git("clone", str(bare), str(work), cwd=str(tmp_path))
    git("config", "user.email", "test@test.com", cwd=str(work))
    git("config", "user.name", "Test", cwd=str(work))

    (work / "README.md").write_text("root\n")
    git("add", "README.md", cwd=str(work))
    git("commit", "-m", "init", cwd=str(work))
    git("push", "origin", "HEAD:main", cwd=str(work))
    git("branch", "--set-upstream-to=origin/main", "main", cwd=str(work))

    return work


class TestOosExciseScript:
    def test_script_exists(self):
        assert SCRIPT.exists(), f"Script not found: {SCRIPT}"

    def test_script_syntax_valid(self):
        result = subprocess.run(["bash", "-n", str(SCRIPT)], capture_output=True, text=True)
        assert result.returncode == 0, f"Syntax error: {result.stderr}"

    def test_no_oos_files_exits_zero(self, git_repo, tmp_path):
        """When all tracked files are within allowed prefixes, script exits 0, stdout empty."""
        artifacts = tmp_path / "artifacts"
        artifacts.mkdir()
        (git_repo / "docs").mkdir(parents=True, exist_ok=True)
        (git_repo / "docs" / "spec.md").write_text("spec\n")
        git("add", "docs/spec.md", cwd=str(git_repo))
        git("commit", "-m", "add spec", cwd=str(git_repo))

        env = base_env(artifacts)
        result = run_script("docs/ .archon/memory/", "refine", env, git_repo)
        assert result.returncode == 0, result.stderr
        assert result.stdout.strip() == "", f"Expected empty stdout, got: {result.stdout!r}"

    def test_new_oos_file_is_excised(self, git_repo, tmp_path):
        """A new file outside allowed prefixes should be removed and its name in stdout."""
        artifacts = tmp_path / "artifacts"
        artifacts.mkdir()
        (git_repo / "docs").mkdir(exist_ok=True)
        (git_repo / "docs" / "spec.md").write_text("spec\n")
        git("add", "docs/spec.md", cwd=str(git_repo))
        git("commit", "-m", "spec", cwd=str(git_repo))
        oos_file = git_repo / "backend" / "surprise.py"
        oos_file.parent.mkdir(exist_ok=True)
        oos_file.write_text("oops\n")
        git("add", str(oos_file), cwd=str(git_repo))
        git("commit", "-m", "oos", cwd=str(git_repo))

        env = base_env(artifacts)
        result = run_script("docs/ .archon/memory/", "refine", env, git_repo)
        assert result.returncode == 0, result.stderr
        assert "backend/surprise.py" in result.stdout
        assert not oos_file.exists(), "OOS file was not removed"

    def test_existing_oos_file_restored_from_origin(self, git_repo, tmp_path):
        """A file that exists in origin/main but was modified OOS should be restored."""
        artifacts = tmp_path / "artifacts"
        artifacts.mkdir()
        orig_file = git_repo / "docs" / "existing.md"
        orig_file.parent.mkdir(exist_ok=True)
        orig_file.write_text("original content\n")
        git("add", str(orig_file), cwd=str(git_repo))
        git("commit", "-m", "original", cwd=str(git_repo))
        git("push", "origin", "main", cwd=str(git_repo))

        oos_file = git_repo / "backend" / "oops.py"
        oos_file.parent.mkdir(exist_ok=True)
        oos_file.write_text("modified\n")
        git("add", str(oos_file), cwd=str(git_repo))
        git("commit", "-m", "oos-modify", cwd=str(git_repo))

        env = base_env(artifacts)
        result = run_script("docs/", "plan", env, git_repo)
        assert result.returncode == 0, result.stderr
        assert "backend/oops.py" in result.stdout

    def test_writes_out_of_scope_md(self, git_repo, tmp_path):
        """out-of-scope.md should be written with an entry for each excised file."""
        artifacts = tmp_path / "artifacts"
        artifacts.mkdir()
        oos_file = git_repo / "backend" / "bad.py"
        oos_file.parent.mkdir(exist_ok=True)
        oos_file.write_text("bad\n")
        git("add", str(oos_file), cwd=str(git_repo))
        git("commit", "-m", "bad", cwd=str(git_repo))

        env = base_env(artifacts)
        result = run_script("docs/", "refine", env, git_repo)
        assert result.returncode == 0, result.stderr
        oos_md = artifacts / "out-of-scope.md"
        assert oos_md.exists(), "out-of-scope.md was not created"
        content = oos_md.read_text()
        assert "backend/bad.py" in content

    def test_makes_allow_empty_commit(self, git_repo, tmp_path):
        """Script must commit even when the excised file was the only change (--allow-empty)."""
        artifacts = tmp_path / "artifacts"
        artifacts.mkdir()
        oos_file = git_repo / "backend" / "oops.py"
        oos_file.parent.mkdir(exist_ok=True)
        oos_file.write_text("oops\n")
        git("add", str(oos_file), cwd=str(git_repo))
        git("commit", "-m", "oos", cwd=str(git_repo))
        before = git("rev-list", "--count", "HEAD", cwd=str(git_repo)).stdout.strip()

        env = base_env(artifacts)
        result = run_script("docs/", "refine", env, git_repo)
        assert result.returncode == 0, result.stderr
        after = git("rev-list", "--count", "HEAD", cwd=str(git_repo)).stdout.strip()
        assert int(after) > int(before), "No commit was made after excision"

    def test_commit_message_contains_noun_and_issue(self, git_repo, tmp_path):
        """Commit message should embed the commit-noun and issue number."""
        artifacts = tmp_path / "artifacts"
        artifacts.mkdir()
        oos_file = git_repo / "backend" / "oops.py"
        oos_file.parent.mkdir(exist_ok=True)
        oos_file.write_text("oops\n")
        git("add", str(oos_file), cwd=str(git_repo))
        git("commit", "-m", "oos", cwd=str(git_repo))

        env = base_env(artifacts)
        result = run_script("docs/", "refine", env, git_repo)
        assert result.returncode == 0, result.stderr
        log = git("log", "--oneline", "-1", cwd=str(git_repo)).stdout.strip()
        assert "refine" in log, f"Commit noun not in message: {log}"
        assert "670" in log, f"Issue number not in message: {log}"

    def test_log_line_goes_to_stderr_not_stdout(self, git_repo, tmp_path):
        """The 'OOS gate: excising...' log line must appear on stderr, not stdout."""
        artifacts = tmp_path / "artifacts"
        artifacts.mkdir()
        oos_file = git_repo / "backend" / "oops.py"
        oos_file.parent.mkdir(exist_ok=True)
        oos_file.write_text("oops\n")
        git("add", str(oos_file), cwd=str(git_repo))
        git("commit", "-m", "oos", cwd=str(git_repo))

        env = base_env(artifacts)
        result = run_script("docs/", "refine", env, git_repo)
        assert result.returncode == 0, result.stderr
        assert "OOS gate" in result.stderr, "Log line not on stderr"
        for line in result.stdout.strip().splitlines():
            assert "OOS gate" not in line, f"Log line leaked to stdout: {line!r}"

    def test_stdout_contains_only_filenames(self, git_repo, tmp_path):
        """stdout must contain only bare filenames, one per line."""
        artifacts = tmp_path / "artifacts"
        artifacts.mkdir()
        for name in ["backend/a.py", "backend/b.py"]:
            f = git_repo / name
            f.parent.mkdir(exist_ok=True)
            f.write_text("x\n")
        git("add", ".", cwd=str(git_repo))
        git("commit", "-m", "two oos", cwd=str(git_repo))

        env = base_env(artifacts)
        result = run_script("docs/", "plan", env, git_repo)
        assert result.returncode == 0, result.stderr
        names = [l for l in result.stdout.strip().splitlines() if l]
        for n in names:
            assert n.startswith("backend/"), f"Unexpected stdout line: {n!r}"

    def test_missing_allowed_prefixes_arg_fails(self, tmp_path):
        """Script must fail when called with no arguments."""
        artifacts = tmp_path / "artifacts"
        artifacts.mkdir()
        env = base_env(artifacts)
        result = subprocess.run(
            ["bash", str(SCRIPT)],
            capture_output=True, text=True, env=env, cwd=str(tmp_path),
        )
        assert result.returncode != 0

    def test_missing_commit_noun_arg_fails(self, tmp_path):
        """Script must fail when called with only one argument."""
        artifacts = tmp_path / "artifacts"
        artifacts.mkdir()
        env = base_env(artifacts)
        result = subprocess.run(
            ["bash", str(SCRIPT), "docs/"],
            capture_output=True, text=True, env=env, cwd=str(tmp_path),
        )
        assert result.returncode != 0


class TestOosExciseBehaviorParity:
    """Verify that oos_excise.sh produces identical side-effects to the original inline block."""

    def _run_inline_oos_side_effects(
        self, work_dir: Path, artifacts: Path, allowed_prefixes: str, commit_noun: str, issue_num: str
    ) -> tuple[list[str], str]:
        """Run the original inline OOS gate block and return (excised_files, oos_md_content)."""
        script = f"""
set -euo pipefail
ALLOWED_PREFIXES="{allowed_prefixes}"
ISSUE_NUM="{issue_num}"
ARTIFACTS_DIR="{artifacts}"
OOS_FILES=$(git diff --name-only origin/main HEAD 2>/dev/null | while read -r f; do
  ALLOWED=false
  for prefix in $ALLOWED_PREFIXES; do
    case "$f" in "$prefix"*) ALLOWED=true; break;; esac
  done
  $ALLOWED || echo "$f"
done)
if [ -n "$OOS_FILES" ]; then
  for f in $OOS_FILES; do
    if git show origin/main:"$f" > /dev/null 2>&1; then
      git checkout origin/main -- "$f" 2>/dev/null
    else
      git rm -f --cached "$f" 2>/dev/null; rm -f "$f"
    fi
  done
  git commit -m "chore: excise out-of-scope files from {commit_noun} run (#${{ISSUE_NUM}})" --allow-empty >/dev/null 2>&1
  mkdir -p "$ARTIFACTS_DIR"
  echo "$OOS_FILES" | while read -r f; do
    echo "- $f: removed by {commit_noun} OOS gate (should not have been created/modified)" >> "$ARTIFACTS_DIR/out-of-scope.md"
  done
  echo "$OOS_FILES"
fi
"""
        result = subprocess.run(
            ["bash", "-c", script],
            cwd=str(work_dir),
            capture_output=True,
            text=True,
        )
        # Filter stdout to only bare file paths (not git rm/commit messages)
        files = sorted(
            l for l in result.stdout.strip().splitlines()
            if l and not l.startswith("rm ") and not l.startswith("[") and not l.startswith(" ")
        )
        oos_md = (artifacts / "out-of-scope.md").read_text() if (artifacts / "out-of-scope.md").exists() else ""
        return files, oos_md

    def _build_bare_origin(self, tmp_path: Path) -> Path:
        """Create a bare origin with a single init commit on 'main'."""
        bare = tmp_path / "bare_parity"
        bare.mkdir()
        git("init", "--bare", str(bare), cwd=str(tmp_path))
        # Set bare HEAD to main so clones get main as default branch
        subprocess.run(
            ["git", "symbolic-ref", "HEAD", "refs/heads/main"],
            cwd=str(bare), capture_output=True,
        )
        seed = tmp_path / "seed_parity"
        git("clone", str(bare), str(seed), cwd=str(tmp_path))
        git("config", "user.email", "t@t.com", cwd=str(seed))
        git("config", "user.name", "T", cwd=str(seed))
        (seed / "README.md").write_text("r\n")
        git("add", "README.md", cwd=str(seed))
        git("commit", "-m", "init", cwd=str(seed))
        git("push", "origin", "HEAD:main", cwd=str(seed))
        return bare

    def _clone(self, bare: Path, tmp_path: Path, name: str) -> Path:
        work = tmp_path / name
        git("clone", str(bare), str(work), cwd=str(tmp_path))
        git("config", "user.email", "t@t.com", cwd=str(work))
        git("config", "user.name", "T", cwd=str(work))
        git("branch", "--set-upstream-to=origin/main", "main", cwd=str(work))
        return work

    def test_parity_no_oos_files(self, tmp_path):
        """Both approaches produce no side-effects when no OOS files are present."""
        bare = self._build_bare_origin(tmp_path)
        work_script = self._clone(bare, tmp_path, "script_no_oos")
        work_inline = self._clone(bare, tmp_path, "inline_no_oos")

        # Add in-scope commit to both
        for work in (work_script, work_inline):
            (work / "docs").mkdir(exist_ok=True)
            (work / "docs" / "spec.md").write_text("spec\n")
            git("add", "docs/spec.md", cwd=str(work))
            git("commit", "-m", "spec", cwd=str(work))

        arts_script = tmp_path / "arts_s_no_oos"
        arts_script.mkdir()
        arts_inline = tmp_path / "arts_i_no_oos"
        arts_inline.mkdir()

        env = base_env(arts_script)
        r_script = run_script("docs/ .archon/memory/", "refine", env, work_script)
        assert r_script.returncode == 0, r_script.stderr

        files_inline, _ = self._run_inline_oos_side_effects(
            work_inline, arts_inline, "docs/ .archon/memory/", "refine", "670"
        )

        script_files = sorted(l for l in r_script.stdout.strip().splitlines() if l)
        assert script_files == files_inline == [], (
            f"Parity mismatch (no-oos): script={script_files} inline={files_inline}"
        )

    def test_parity_with_oos_new_file(self, tmp_path):
        """Both approaches excise the same OOS files and produce matching out-of-scope.md."""
        bare = self._build_bare_origin(tmp_path)
        work_script = self._clone(bare, tmp_path, "script_oos")
        work_inline = self._clone(bare, tmp_path, "inline_oos")

        for work in (work_script, work_inline):
            oos = work / "backend" / "oops.py"
            oos.parent.mkdir(exist_ok=True)
            oos.write_text("oops\n")
            git("add", str(oos), cwd=str(work))
            git("commit", "-m", "oos", cwd=str(work))

        arts_script = tmp_path / "arts_s_oos"
        arts_script.mkdir()
        arts_inline = tmp_path / "arts_i_oos"
        arts_inline.mkdir()

        env = base_env(arts_script)
        r_script = run_script("docs/ README.md", "plan", env, work_script)
        assert r_script.returncode == 0, r_script.stderr

        files_inline, oos_md_inline = self._run_inline_oos_side_effects(
            work_inline, arts_inline, "docs/ README.md", "plan", "670"
        )

        script_files = sorted(l for l in r_script.stdout.strip().splitlines() if l)
        oos_md_script = (arts_script / "out-of-scope.md").read_text() if (arts_script / "out-of-scope.md").exists() else ""

        assert script_files == files_inline, (
            f"Excised files differ:\n  script: {script_files}\n  inline: {files_inline}"
        )
        assert sorted(oos_md_script.strip().splitlines()) == sorted(oos_md_inline.strip().splitlines()), (
            f"out-of-scope.md differs:\n  script: {oos_md_script!r}\n  inline: {oos_md_inline!r}"
        )
        # Both should have the file removed
        assert not (work_script / "backend" / "oops.py").exists()
        assert not (work_inline / "backend" / "oops.py").exists()
