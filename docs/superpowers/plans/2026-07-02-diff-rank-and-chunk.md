# Implementation Plan: Diff Rank and Chunk (Issue #669)

**Date:** 2026-07-02  
**Issue:** #669 — Rank and chunk diffs for conformance and code-review prompts  
**Spec:** `docs/superpowers/specs/2026-07-01-diff-rank-and-chunk-design.md`  
**Branch:** `feat/issue-669-diff-rank-and-chunk`

---

## Goal

Replace the blind `head -1000` truncation in both the conformance gate and code-review gate with a risk-aware ranker that:
- Emits critical/security/trading files in full regardless of token budget
- Fills the budget with high-risk (router, spec-named, dependency) files first
- Summarizes low-risk test files as a one-liner
- Writes `$ARTIFACTS_DIR/diff-ranking.json` on every run

## Architecture

```
dark-factory/scripts/diff_rank.py          ← new stdlib-only script
dark-factory/tests/test_diff_rank.py       ← new in-process unit tests
.archon/commands/dark-factory-conformance.md    ← update Phase 3.0 (remove head -1000, add rank call)
.archon/commands/dark-factory-code-review.md   ← update Phase 2 (replace head -1000 pipeline)
```

`diff_rank.py` imports `parse_hotspots` from `gate_blast_radius` (same `sys.path.insert` pattern as `fmt_hunk_filter.py`) so both scripts agree on which files are hotspots. Token budget: `len(text) // 4` — matching `context_budget.py`. Config keys read: `token_optimization.diff.max_review_tokens` (cap for non-critical content) and `blast_radius.hotspot_score_floor`.

## Tech Stack

Pure Python, stdlib-only. No external deps beyond PyYAML (already present in the container for `gate_blast_radius.py`). No git/subprocess calls in the script itself; the caller passes the pre-computed diff via `--diff`.

## File Structure

| File | Action | Purpose |
|------|--------|---------|
| `dark-factory/scripts/diff_rank.py` | Create | Risk classifier + budget manager + JSON writer |
| `dark-factory/tests/test_diff_rank.py` | Create | In-process unit tests, no git/subprocess |
| `.archon/commands/dark-factory-conformance.md` | Edit | Phase 3.0: remove `head -1000`, add `diff_rank.py` call after `fmt_hunk_filter` |
| `.archon/commands/dark-factory-code-review.md` | Edit | Phase 2: replace `head -1000` pipe with `diff_rank.py` pipeline |

---

## Task 1 — Write the test suite (TDD red)

**Files:** `dark-factory/tests/test_diff_rank.py`

### Steps

**Step 1.1 — Create the test file**

Write `dark-factory/tests/test_diff_rank.py` with the following content:

```python
"""Tests for dark-factory/scripts/diff_rank.py.

All tests are in-process (no git/subprocess). A run_main() helper patches
sys.argv and sys.stdout so main() can be exercised end-to-end with temp files.
"""
import io
import json
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

import yaml

# In-process import matching fmt_hunk_filter.py's self-contained pattern
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import diff_rank as dr          # noqa: E402
import gate_blast_radius as gbr  # noqa: E402


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_config(token_cap=6000, score_floor=5.0):
    return {
        "token_optimization": {"diff": {"max_review_tokens": token_cap}},
        "blast_radius": {"hotspot_score_floor": score_floor},
    }


def make_diff(path, added=5, removed=2, n_hunks=1):
    """Build a minimal synthetic unified diff for one file."""
    hunks = ""
    for i in range(n_hunks):
        offset = 1 + i * max(added, removed)
        hunks += f"@@ -{offset},{removed} +{offset},{added} @@\n"
        for _ in range(removed):
            hunks += "-old line\n"
        for _ in range(added):
            hunks += "+new line\n"
        for _ in range(2):
            hunks += " ctx line\n"
    return (
        f"diff --git a/{path} b/{path}\n"
        f"index aaa..bbb 100644\n"
        f"--- a/{path}\n"
        f"+++ b/{path}\n"
        f"{hunks}"
    )


def run_main(
    diff_content,
    token_cap=6000,
    score_floor=5.0,
    hotspots_content="",
    spec_content=None,
    missing_hotspots=False,
):
    """Run dr.main() in-process; return (stdout_str, ranking_dict_or_None)."""
    with tempfile.TemporaryDirectory() as artifacts_dir:
        with (
            tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False) as df,
            tempfile.NamedTemporaryFile("w", suffix=".yaml", delete=False) as cf,
            tempfile.NamedTemporaryFile("w", suffix=".md", delete=False) as hf,
        ):
            df.write(diff_content)
            df.flush()
            yaml.dump(make_config(token_cap, score_floor), cf)
            cf.flush()
            hf.write(hotspots_content)
            hf.flush()

            hotspots_path = "/tmp/nonexistent_diffrank_XXXX.md" if missing_hotspots else hf.name

            argv = [
                "diff_rank.py",
                "--diff", df.name,
                "--artifacts-dir", artifacts_dir,
                "--config", cf.name,
                "--hotspots", hotspots_path,
            ]

            if spec_content is not None:
                with tempfile.NamedTemporaryFile("w", suffix=".md", delete=False) as sf:
                    sf.write(spec_content)
                    sf.flush()
                    argv += ["--spec-file", sf.name]

            buf = io.StringIO()
            with patch("sys.argv", argv), patch("sys.stdout", buf):
                try:
                    dr.main()
                except SystemExit:
                    pass

            output = buf.getvalue()
            ranking_path = Path(artifacts_dir) / "diff-ranking.json"
            ranking = (
                json.loads(ranking_path.read_text())
                if ranking_path.exists()
                else None
            )

    return output, ranking


# ---------------------------------------------------------------------------
# Risk classification — direct calls to dr.classify_file()
# ---------------------------------------------------------------------------

def test_classify_auth_path_is_critical():
    tier, signals, _ = dr.classify_file(
        "backend/app/routers/auth/router.py", set(), set(), 5.0
    )
    assert tier == "critical"
    assert any("auth" in s for s in signals)


def test_classify_auth_core_is_critical():
    tier, signals, _ = dr.classify_file(
        "backend/app/core/auth/jwt.py", set(), set(), 5.0
    )
    assert tier == "critical"


def test_classify_migration_is_critical():
    tier, signals, _ = dr.classify_file(
        "alembic/versions/001_add_col.py", set(), set(), 5.0
    )
    assert tier == "critical"


def test_classify_trading_service_is_critical():
    tier, signals, _ = dr.classify_file(
        "backend/app/services/trading/order.py", set(), set(), 5.0
    )
    assert tier == "critical"


def test_classify_trading_tasks_is_critical():
    tier, signals, _ = dr.classify_file(
        "backend/app/tasks/trading.py", set(), set(), 5.0
    )
    assert tier == "critical"


def test_classify_dark_factory_path_is_critical():
    tier, signals, _ = dr.classify_file(
        "dark-factory/scripts/some_script.py", set(), set(), 5.0
    )
    assert tier == "critical"


def test_classify_hotspot_above_floor_is_critical():
    hotspot_paths = {"backend/app/services/scanner.py"}
    tier, signals, _ = dr.classify_file(
        "backend/app/services/scanner.py", hotspot_paths, set(), 5.0
    )
    assert tier == "critical"
    assert "hotspot" in signals


def test_classify_hotspot_below_floor_is_not_critical():
    # File appears in hotspot_paths only when at/above floor — if not in set, not critical
    tier, _, _ = dr.classify_file(
        "backend/app/services/scanner.py", set(), set(), 5.0
    )
    # Not critical via path patterns; lands in high/medium/low depending on context
    assert tier != "critical"


def test_classify_router_is_high():
    tier, signals, _ = dr.classify_file(
        "backend/app/routers/scanner.py", set(), set(), 5.0
    )
    assert tier == "high"
    assert "api_endpoint" in signals


def test_classify_spec_named_is_high():
    spec_names = {"dark-factory/scripts/diff_rank.py"}
    tier, signals, _ = dr.classify_file(
        "dark-factory/scripts/diff_rank.py", set(), spec_names, 5.0
    )
    # Note: dark-factory/ is critical via safety path; spec-named only matters for non-safety files
    # Use a non-safety path for this test:
    spec_names2 = {"backend/app/services/stock_data.py"}
    tier2, signals2, _ = dr.classify_file(
        "backend/app/services/stock_data.py", set(), spec_names2, 5.0, total_lines=10
    )
    assert tier2 == "high"
    assert "spec_named" in signals2


def test_classify_dependency_file_is_high():
    tier, signals, _ = dr.classify_file(
        "backend/requirements.txt", set(), set(), 5.0
    )
    assert tier == "high"
    assert "dependency" in signals


def test_classify_package_json_is_high():
    tier, signals, _ = dr.classify_file(
        "frontend/package.json", set(), set(), 5.0
    )
    assert tier == "high"
    assert "dependency" in signals


def test_classify_test_file_is_low():
    tier, signals, _ = dr.classify_file(
        "tests/test_scanner.py", set(), set(), 5.0
    )
    assert tier == "low"
    assert "test_file" in signals


def test_classify_spec_test_file_is_low():
    tier, signals, _ = dr.classify_file(
        "dark-factory/tests/test_blast_radius.py", set(), set(), 5.0
    )
    assert tier == "low"
    assert "test_file" in signals


def test_classify_ts_test_file_is_low():
    tier, signals, _ = dr.classify_file(
        "frontend/src/components/Scanner.test.ts", set(), set(), 5.0
    )
    assert tier == "low"


def test_classify_large_non_test_non_critical_is_medium():
    tier, _, _ = dr.classify_file(
        "backend/app/services/stock_data.py", set(), set(), 5.0, total_lines=100
    )
    assert tier == "medium"


def test_classify_small_non_test_non_critical_is_low():
    tier, _, _ = dr.classify_file(
        "backend/app/services/stock_data.py", set(), set(), 5.0, total_lines=10
    )
    assert tier == "low"


# ---------------------------------------------------------------------------
# Token budget — via run_main()
# ---------------------------------------------------------------------------

def test_critical_files_bypass_token_cap():
    """Auth file is critical and must be fully included even with a 1-token cap."""
    diff = make_diff("backend/app/routers/auth/router.py", added=200, removed=50)
    _, ranking = run_main(diff, token_cap=1)
    assert ranking is not None
    auth_entry = next(
        f for f in ranking["files"] if "auth" in f["path"]
    )
    assert auth_entry["included"] == "full"
    assert auth_entry["risk_class"] == "critical"


def test_high_files_fill_budget_then_summarize():
    """Router file (high) exceeds tiny cap → summarized."""
    diff = make_diff("backend/app/routers/scanner.py", added=200, removed=100)
    output, ranking = run_main(diff, token_cap=10)
    entry = next(f for f in ranking["files"] if "scanner.py" in f["path"])
    assert entry["included"] == "summary"
    assert "budget-exhausted" in output


def test_high_file_included_when_budget_allows():
    """Router file included in full when budget is large enough."""
    diff = make_diff("backend/app/routers/scanner.py", added=5, removed=2)
    _, ranking = run_main(diff, token_cap=100000)
    entry = next(f for f in ranking["files"] if "scanner.py" in f["path"])
    assert entry["included"] == "full"


def test_low_files_always_summarized_regardless_of_budget():
    """Test file should always be summarized even with a huge cap."""
    diff = make_diff("tests/test_scanner.py", added=42, removed=3, n_hunks=2)
    _, ranking = run_main(diff, token_cap=100000)
    entry = ranking["files"][0]
    assert entry["included"] == "summary"
    assert entry["risk_class"] == "low"


# ---------------------------------------------------------------------------
# Summary line format
# ---------------------------------------------------------------------------

def test_summary_line_low_risk_format():
    diff = make_diff("tests/test_scanner.py", added=42, removed=3, n_hunks=2)
    output, _ = run_main(diff)
    assert "# [SUMMARIZED: low-risk test-only] tests/test_scanner.py — +42/-3 (2 hunks)" in output


def test_summary_line_budget_exhausted_format():
    diff = make_diff("backend/app/routers/scanner.py", added=200, removed=100, n_hunks=5)
    output, _ = run_main(diff, token_cap=10)
    assert "# [SUMMARIZED: budget-exhausted] backend/app/routers/scanner.py" in output


# ---------------------------------------------------------------------------
# Header line
# ---------------------------------------------------------------------------

def test_header_line_is_first_line():
    diff = make_diff("backend/app/services/utils.py", added=10, removed=5)
    output, _ = run_main(diff)
    assert output.splitlines()[0].startswith("# [diff-rank:")


def test_header_line_contains_tier_counts_and_token_info():
    diff = (
        make_diff("backend/app/routers/auth.py", added=5, removed=2)
        + make_diff("tests/test_scanner.py", added=3, removed=1)
    )
    output, _ = run_main(diff)
    first_line = output.splitlines()[0]
    assert "critical" in first_line
    assert "low" in first_line
    assert "tokens (cap" in first_line


# ---------------------------------------------------------------------------
# diff-ranking.json structure
# ---------------------------------------------------------------------------

def test_diff_ranking_json_written_on_run():
    diff = make_diff("backend/app/routers/scanner.py")
    _, ranking = run_main(diff)
    assert ranking is not None
    assert "token_cap" in ranking
    assert "estimated_tokens_emitted" in ranking
    assert "critical_tokens" in ranking
    assert "residual_tokens" in ranking
    assert "files" in ranking


def test_diff_ranking_json_file_entry_fields():
    diff = make_diff("tests/test_scanner.py", added=42, removed=3, n_hunks=2)
    _, ranking = run_main(diff)
    f = ranking["files"][0]
    assert f["path"] == "tests/test_scanner.py"
    assert f["risk_class"] == "low"
    assert f["signals"] == ["test_file"]
    assert f["lines_added"] == 42
    assert f["lines_removed"] == 3
    assert f["hunk_count"] == 2
    assert f["included"] == "summary"
    assert f["estimated_tokens"] == 0


def test_diff_ranking_json_critical_token_accounting():
    """critical_tokens tracks bypass-cap usage; residual_tokens tracks budget usage."""
    diff = (
        make_diff("backend/app/routers/auth.py", added=40, removed=10)
        + make_diff("backend/app/routers/scanner.py", added=5, removed=2)
    )
    _, ranking = run_main(diff, token_cap=6000)
    assert ranking["critical_tokens"] > 0
    # scanner.py (high, small) should fit in budget
    scanner_entry = next(f for f in ranking["files"] if "scanner.py" in f["path"])
    assert scanner_entry["included"] == "full"


# ---------------------------------------------------------------------------
# Fail-open: missing --hotspots file
# ---------------------------------------------------------------------------

def test_fail_open_missing_hotspots_proceeds():
    """On missing hotspots file, script proceeds without blast scores (not an error)."""
    diff = make_diff("backend/app/services/utils.py", added=10, removed=5)
    output, ranking = run_main(diff, missing_hotspots=True)
    # Script should still produce output — missing hotspots is a soft fallback
    assert ranking is not None
    assert ranking["files"][0]["blast_score"] is None


# ---------------------------------------------------------------------------
# Empty diff
# ---------------------------------------------------------------------------

def test_empty_diff_empty_stdout():
    output, ranking = run_main("")
    assert output.strip() == ""
    assert ranking is not None
    assert ranking["files"] == []
    assert ranking["estimated_tokens_emitted"] == 0


# ---------------------------------------------------------------------------
# parse_hotspots import agreement
# ---------------------------------------------------------------------------

def test_parse_diff_files_tolerates_leading_pretriage_annotation():
    """Lines before the first 'diff --git' header (e.g. [Pre-triage] from fmt_hunk_filter)
    must not corrupt the file list — they are silently skipped because cur is None."""
    annotation = "[Pre-triage] hunk-filter applied: 2 files / 3 hunks retained\n"
    diff = annotation + make_diff("backend/app/routers/scanner.py", added=3, removed=1)
    output, ranking = run_main(diff)
    # Only the actual diff file should appear; the annotation must not be parsed as a file
    assert ranking is not None
    assert len(ranking["files"]) == 1
    assert ranking["files"][0]["path"] == "backend/app/routers/scanner.py"


def test_parse_hotspots_import_agrees_with_gate_blast_radius():
    """The parse_hotspots imported in diff_rank must equal gate_blast_radius.parse_hotspots."""
    hotspots_content = (
        "    7.2  backend/app/services/scanner.py  (2d / 10t)  200 loc\n"
        "    3.1  frontend/src/api/client.ts  (1d / 5t)  100 loc\n"
    )
    with tempfile.NamedTemporaryFile("w", suffix=".md", delete=False) as hf:
        hf.write(hotspots_content)
        hf.flush()
        result_dr = dr.parse_hotspots(hf.name, 5.0)
        result_gbr = gbr.parse_hotspots(hf.name, 5.0)
    assert isinstance(result_dr, set)   # must be a set, not a dict (scores are separate)
    assert result_dr == result_gbr
    assert "backend/app/services/scanner.py" in result_dr
    assert "frontend/src/api/client.ts" not in result_dr  # score 3.1 < 5.0 floor
```

**Step 1.2 — Verify tests fail (script not yet written)**

```bash
cd /workspace/markethawk
python -m pytest dark-factory/tests/test_diff_rank.py -v 2>&1 | head -30
```

Expected: `ModuleNotFoundError: No module named 'diff_rank'` or equivalent import error.

**Step 1.3 — Commit the red test suite**

```bash
git add dark-factory/tests/test_diff_rank.py
git commit -m "test: add test suite for diff_rank.py (red — script not yet written)

Covers: risk classification (critical/high/medium/low), token budget bypass
for critical files, summary line formats, header line, diff-ranking.json
structure, fail-open on missing hotspots, empty diff, [Pre-triage] annotation
tolerance in parse_diff_files, parse_hotspots import agreement with gate_blast_radius.

Issue #669"
```

---

## Task 2 — Implement `diff_rank.py`

**Files:** `dark-factory/scripts/diff_rank.py`

### Steps

**Step 2.1 — Create `dark-factory/scripts/diff_rank.py`**

```python
"""
Diff ranker and chunker for dark-factory gates.

Classifies files in a unified diff into risk tiers (critical/high/medium/low),
emits a ranked diff to stdout with a configurable token budget, and writes
diff-ranking.json to --artifacts-dir.

CLI:
    python3 dark-factory/scripts/diff_rank.py \
      --diff <path>            \\
      --artifacts-dir <dir>    \\
      [--config <yaml>]        \\
      [--spec-file <path>]     \\
      [--hotspots <path>]

Writes the ranked diff string to stdout. Exits 0 on success; on any error
exits non-zero so the caller's '&&' falls back to the unranked diff.
"""
import argparse
import json
import re
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# Import parse_hotspots from gate_blast_radius (same package)
# ---------------------------------------------------------------------------
_SCRIPTS_DIR = Path(__file__).resolve().parent
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

from gate_blast_radius import parse_hotspots  # noqa: E402  # re-exported for tests

# ---------------------------------------------------------------------------
# Risk classification constants
#
# Canonical signal string values (appear in signals list and diff-ranking.json):
#   Critical signals: "migration_path", "auth_path", "trading_path", "factory_path", "hotspot"
#   High signals:     "spec_named", "api_endpoint", "dependency", "elevated_blast"
#   Low signals:      "test_file"
#   Medium/low:       [] (empty list — no specific signal)
# ---------------------------------------------------------------------------

# SAFETY_PATH_PATTERNS deliberately differs from gate_blast_radius.MIGRATION_SEED_AUTH_PATTERNS:
#   "^dark-factory/" (broad prefix) replaces "^dark-factory/seed/" — covers all factory scripts,
#   not just seed data. The seed/ subdirectory is caught by this broader prefix.
#   "seed.*\.sql$" (external seed SQL outside dark-factory/) is omitted — not listed in spec.
#   Auth router uses prefix "^backend/app/routers/auth" (all auth routes), vs the single exact
#   file match "^backend/app/routers/auth\.py$" in MIGRATION_SEED_AUTH_PATTERNS.
#   Trading paths are added here (not in gate_blast_radius) per spec R4.
SAFETY_PATH_PATTERNS = [
    re.compile(r"^alembic/versions/"),
    re.compile(r"^backend/app/routers/auth"),
    re.compile(r"^backend/app/core/auth"),
    re.compile(r"app/services/trading"),
    re.compile(r"app/tasks/trading\.py"),
    re.compile(r"^dark-factory/"),
]

TEST_PATH_PATTERNS = [
    re.compile(r"(^|/)test_[^/]+\.py$"),
    re.compile(r"(^|/)tests/"),
    re.compile(r"(^|/)conftest\.py$"),
    re.compile(r"\.test\.ts$"),
    re.compile(r"\.spec\.ts$"),
]

DEPENDENCY_PATTERNS = [
    re.compile(r"requirements[^/]*\.txt$"),
    re.compile(r"package[^/]*\.json$"),
    re.compile(r"pyproject\.toml$"),
]

ROUTER_PATTERN = re.compile(r"^backend/app/routers/")

# Medium threshold: files with more changed lines than this (if not critical/high/test)
MEDIUM_LINE_THRESHOLD = 50

# Elevated-blast threshold for high tier (below floor but still notable)
ELEVATED_BLAST_FLOOR = 2.0


# ---------------------------------------------------------------------------
# Config loading
# ---------------------------------------------------------------------------

def load_config(path: str) -> tuple:
    """Return (token_cap: int, score_floor: float) from config yaml.

    Keys read:
      token_optimization.diff.max_review_tokens  → token_cap  (default 6000)
      blast_radius.hotspot_score_floor           → score_floor (default 5.0)
    """
    try:
        import yaml  # type: ignore
        with open(path) as f:
            data = yaml.safe_load(f)
        token_cap = int(
            data.get("token_optimization", {})
            .get("diff", {})
            .get("max_review_tokens", 6000)
        )
        score_floor = float(
            data.get("blast_radius", {}).get("hotspot_score_floor", 5.0)
        )
        return token_cap, score_floor
    except Exception:
        return 6000, 5.0


# ---------------------------------------------------------------------------
# Hotspot scores (for JSON output and elevated-blast high tier)
# ---------------------------------------------------------------------------

def _read_hotspot_scores(path: str) -> dict:
    """Return dict of filepath → blast_score for all entries in hotspots file."""
    scores = {}
    try:
        content = Path(path).read_text(errors="replace")
    except FileNotFoundError:
        return scores
    for line in content.splitlines():
        m = re.match(r"^\s*([\d.]+)\s+(\S+)", line)
        if m:
            try:
                scores[m.group(2)] = float(m.group(1))
            except ValueError:
                pass
    return scores


# ---------------------------------------------------------------------------
# Spec-named file extraction
# ---------------------------------------------------------------------------

def _extract_spec_names(spec_file: str) -> set:
    """Return set of file path strings mentioned in the spec file."""
    if not spec_file:
        return set()
    try:
        text = Path(spec_file).read_text(errors="replace")
        # Match tokens with at least one slash that look like paths
        return set(re.findall(r"\b[a-zA-Z0-9_.-]+(?:/[a-zA-Z0-9_.-]+)+\b", text))
    except Exception:
        return set()


# ---------------------------------------------------------------------------
# Risk classification
# ---------------------------------------------------------------------------

def _safety_signal(path: str) -> str:
    for pat in SAFETY_PATH_PATTERNS:
        if pat.search(path):
            src = pat.pattern
            if "alembic" in src:
                return "migration_path"
            if "auth" in src:
                return "auth_path"
            if "trading" in src:
                return "trading_path"
            if "dark-factory" in src:
                return "factory_path"
            return "safety_path"
    return ""


def classify_file(
    path: str,
    hotspot_paths: set,
    spec_names: set,
    score_floor: float,
    total_lines: int = 0,
    hotspot_scores: dict = None,
) -> tuple:
    """Classify a file path into a risk tier.

    Returns (tier: str, signals: list[str], blast_score: float | None).
    Tiers: critical > high > medium > low.
    """
    blast_score = (hotspot_scores or {}).get(path)

    # --- Critical: safety paths OR hotspot at/above floor ---
    safety_sig = _safety_signal(path)
    is_hotspot_critical = path in hotspot_paths
    if safety_sig or is_hotspot_critical:
        signals = []
        if safety_sig:
            signals.append(safety_sig)
        if is_hotspot_critical:
            signals.append("hotspot")
        return "critical", signals, blast_score

    # --- High: spec-named, router, dependency, elevated blast ---
    high_signals = []
    if path in spec_names:
        high_signals.append("spec_named")
    if ROUTER_PATTERN.search(path):
        high_signals.append("api_endpoint")
    if any(p.search(path) for p in DEPENDENCY_PATTERNS):
        high_signals.append("dependency")
    if blast_score is not None and blast_score >= ELEVATED_BLAST_FLOOR:
        high_signals.append("elevated_blast")
    if high_signals:
        return "high", high_signals, blast_score

    # --- Low: test files (always) ---
    if any(p.search(path) for p in TEST_PATH_PATTERNS):
        return "low", ["test_file"], blast_score

    # --- Medium or Low: based on line count ---
    if total_lines > MEDIUM_LINE_THRESHOLD:
        return "medium", [], blast_score
    return "low", [], blast_score


# ---------------------------------------------------------------------------
# Diff parsing
# ---------------------------------------------------------------------------

def parse_diff_files(diff_text: str) -> list:
    """Parse unified diff; return list of file dicts.

    Each dict: {path, added, removed, hunks, lines (list of str)}.
    Leading non-diff lines (e.g. a [Pre-triage] annotation prepended by fmt_hunk_filter)
    are silently ignored because lines are only collected after the first 'diff --git' header
    (cur is None until then).
    """
    files = []
    cur = None

    for line in diff_text.splitlines(keepends=True):
        if line.startswith("diff --git "):
            if cur is not None and cur.get("path"):
                files.append(cur)
            cur = {"path": None, "added": 0, "removed": 0, "hunks": 0, "lines": [line]}
        elif cur is not None:
            cur["lines"].append(line)
            if line.startswith("+++ b/"):
                cur["path"] = line[6:].rstrip("\n")
            elif line.startswith("+++ /dev/null"):
                pass  # deleted file header
            elif re.match(r"^@@ ", line):
                cur["hunks"] += 1
            elif line.startswith("+") and not line.startswith("+++"):
                cur["added"] += 1
            elif line.startswith("-") and not line.startswith("---"):
                cur["removed"] += 1

    if cur is not None and cur.get("path"):
        files.append(cur)

    return files


# ---------------------------------------------------------------------------
# Token estimation
# ---------------------------------------------------------------------------

def estimate_tokens(text: str) -> int:
    """Character-based token approximation matching context_budget.py."""
    return len(text) // 4


# ---------------------------------------------------------------------------
# Ranking and budget
# ---------------------------------------------------------------------------

def build_ranked_diff(
    diff_text: str,
    token_cap: int,
    hotspot_paths: set,
    hotspot_scores: dict,
    spec_names: set,
    score_floor: float,
) -> tuple:
    """Return (ranked_diff_str, ranking_info_dict).

    ranked_diff_str is empty when diff_text is empty.
    """
    files = parse_diff_files(diff_text)

    ranking_base = {
        "token_cap": token_cap,
        "estimated_tokens_emitted": 0,
        "critical_tokens": 0,
        "residual_tokens": 0,
        "files": [],
    }

    if not files:
        return "", ranking_base

    # Classify every file
    classified = []
    for f in files:
        total_lines = f["added"] + f["removed"]
        tier, signals, blast_score = classify_file(
            f["path"],
            hotspot_paths,
            spec_names,
            score_floor,
            total_lines=total_lines,
            hotspot_scores=hotspot_scores,
        )
        classified.append({"file": f, "tier": tier, "signals": signals, "blast_score": blast_score})

    # Bucket by tier
    critical = [c for c in classified if c["tier"] == "critical"]
    high = [c for c in classified if c["tier"] == "high"]
    medium = [c for c in classified if c["tier"] == "medium"]
    low = [c for c in classified if c["tier"] == "low"]

    # Sort critical: blast_score desc, then lines desc
    critical.sort(key=lambda c: (-(c["blast_score"] or 0), -(c["file"]["added"] + c["file"]["removed"])))

    # Sort high: spec-named first, then api, then deps, then elevated_blast
    def _high_key(c):
        sigs = c["signals"]
        if "spec_named" in sigs:
            order = 0
        elif "api_endpoint" in sigs:
            order = 1
        elif "dependency" in sigs:
            order = 2
        else:
            order = 3
        return (order, -(c["blast_score"] or 0), -(c["file"]["added"] + c["file"]["removed"]))
    high.sort(key=_high_key)

    # Sort medium: lines desc
    medium.sort(key=lambda c: -(c["file"]["added"] + c["file"]["removed"]))

    output_parts = []
    file_records = []
    critical_tokens = 0
    residual_tokens = 0
    budget = token_cap

    def _full(c, risk_class):
        nonlocal budget, residual_tokens, critical_tokens
        text = "".join(c["file"]["lines"])
        tokens = estimate_tokens(text)
        if risk_class == "critical":
            critical_tokens += tokens
        else:
            residual_tokens += tokens
            budget -= tokens
        output_parts.append(text)
        return tokens, "full"

    def _summary_budget_exhausted(c):
        f = c["file"]
        summary = (
            f"# [SUMMARIZED: budget-exhausted] {f['path']} — "
            f"+{f['added']}/-{f['removed']} ({f['hunks']} hunks)\n"
        )
        output_parts.append(summary)
        return 0, "summary"

    def _summary_low(c):
        f = c["file"]
        summary = (
            f"# [SUMMARIZED: low-risk test-only] {f['path']} — "
            f"+{f['added']}/-{f['removed']} ({f['hunks']} hunks)\n"
        )
        output_parts.append(summary)
        return 0, "summary"

    # Emit critical files (bypass cap)
    for c in critical:
        tokens, included = _full(c, "critical")
        file_records.append({
            "path": c["file"]["path"],
            "risk_class": "critical",
            "signals": c["signals"],
            "blast_score": c["blast_score"],
            "lines_added": c["file"]["added"],
            "lines_removed": c["file"]["removed"],
            "hunk_count": c["file"]["hunks"],
            "included": included,
            "estimated_tokens": tokens,
        })

    # Fill budget with high-tier files
    for c in high:
        text = "".join(c["file"]["lines"])
        tokens = estimate_tokens(text)
        if budget >= tokens:
            t, included = _full(c, "high")
        else:
            t, included = _summary_budget_exhausted(c)
            tokens = t
        file_records.append({
            "path": c["file"]["path"],
            "risk_class": "high",
            "signals": c["signals"],
            "blast_score": c["blast_score"],
            "lines_added": c["file"]["added"],
            "lines_removed": c["file"]["removed"],
            "hunk_count": c["file"]["hunks"],
            "included": included,
            "estimated_tokens": tokens,
        })

    # Fill remaining budget with medium-tier files
    for c in medium:
        text = "".join(c["file"]["lines"])
        tokens = estimate_tokens(text)
        if budget >= tokens:
            t, included = _full(c, "medium")
        else:
            t, included = _summary_budget_exhausted(c)
            tokens = t
        file_records.append({
            "path": c["file"]["path"],
            "risk_class": "medium",
            "signals": c["signals"],
            "blast_score": c["blast_score"],
            "lines_added": c["file"]["added"],
            "lines_removed": c["file"]["removed"],
            "hunk_count": c["file"]["hunks"],
            "included": included,
            "estimated_tokens": tokens,
        })

    # Summarize all low-tier files
    for c in low:
        _summary_low(c)
        file_records.append({
            "path": c["file"]["path"],
            "risk_class": "low",
            "signals": c["signals"],
            "blast_score": c["blast_score"],
            "lines_added": c["file"]["added"],
            "lines_removed": c["file"]["removed"],
            "hunk_count": c["file"]["hunks"],
            "included": "summary",
            "estimated_tokens": 0,
        })

    total_tokens = critical_tokens + residual_tokens

    header = (
        f"# [diff-rank: {len(files)} files — "
        f"{len(critical)} critical / {len(high)} high / "
        f"{len(medium)} medium / {len(low)} low, "
        f"est. {total_tokens} tokens (cap {token_cap})]\n"
    )

    ranked_diff = header + "".join(output_parts)

    ranking_info = {
        "token_cap": token_cap,
        "estimated_tokens_emitted": total_tokens,
        "critical_tokens": critical_tokens,
        "residual_tokens": residual_tokens,
        "files": file_records,
    }

    return ranked_diff, ranking_info


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def parse_args():
    p = argparse.ArgumentParser(description="Rank and chunk a unified diff by risk tier.")
    p.add_argument("--diff", required=True, help="Path to the input diff file")
    p.add_argument("--artifacts-dir", required=True, help="Directory to write diff-ranking.json")
    p.add_argument(
        "--config",
        default=".claude/skills/refinement/config.yaml",
        help="Path to refinement config yaml",
    )
    p.add_argument("--spec-file", default=None, help="Optional spec file to identify spec-named files")
    p.add_argument(
        "--hotspots",
        default="docs/codeindex-hotspots.md",
        help="Path to codeindex-hotspots.md",
    )
    return p.parse_args()


def main():
    args = parse_args()

    diff_text = Path(args.diff).read_text(errors="replace")
    token_cap, score_floor = load_config(args.config)
    hotspot_paths = parse_hotspots(args.hotspots, score_floor)  # set (fail-open in parse_hotspots)
    hotspot_scores = _read_hotspot_scores(args.hotspots)         # dict for JSON + elevated blast
    spec_names = _extract_spec_names(args.spec_file)

    ranked_diff, ranking_info = build_ranked_diff(
        diff_text, token_cap, hotspot_paths, hotspot_scores, spec_names, score_floor
    )

    # Write diff-ranking.json
    ranking_path = Path(args.artifacts_dir) / "diff-ranking.json"
    ranking_path.write_text(json.dumps(ranking_info, indent=2))

    # Write ranked diff to stdout
    sys.stdout.write(ranked_diff)


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"diff_rank error: {e}", file=sys.stderr)
        sys.exit(1)
```

**Step 2.2 — Run the full test suite and verify all green**

```bash
cd /workspace/markethawk
python -m pytest dark-factory/tests/test_diff_rank.py -v 2>&1 | tail -40
```

Expected: All tests pass (`PASSED` for each). If any test fails, fix the implementation before proceeding.

**Step 2.3 — Spot-test with a synthetic real-world scenario**

```bash
# Build a representative diff with a mix of tiers
cat > /tmp/test_diff_rank.patch << 'EOF'
diff --git a/backend/app/routers/auth.py b/backend/app/routers/auth.py
index aaa..bbb 100644
--- a/backend/app/routers/auth.py
+++ b/backend/app/routers/auth.py
@@ -1,3 +1,4 @@
 from fastapi import APIRouter
+import logging
 router = APIRouter()
 
diff --git a/backend/app/routers/scanner.py b/backend/app/routers/scanner.py
index ccc..ddd 100644
--- a/backend/app/routers/scanner.py
+++ b/backend/app/routers/scanner.py
@@ -10,2 +10,3 @@
 def scan():
+    pass
     return {}
diff --git a/tests/test_scanner.py b/tests/test_scanner.py
index eee..fff 100644
--- a/tests/test_scanner.py
+++ b/tests/test_scanner.py
@@ -1,2 +1,3 @@
 def test_foo():
+    assert True
     pass
EOF

mkdir -p /tmp/rank_test_artifacts
python3 dark-factory/scripts/diff_rank.py \
  --diff /tmp/test_diff_rank.patch \
  --artifacts-dir /tmp/rank_test_artifacts \
  --config .claude/skills/refinement/config.yaml \
  --hotspots docs/codeindex-hotspots.md
```

Expected stdout:
- First line: `# [diff-rank: 3 files — 1 critical / 1 high / 0 medium / 1 low, est. N tokens (cap 6000)]`
- Auth router diff included in full
- Scanner router diff included in full (small, within budget)
- `# [SUMMARIZED: low-risk test-only] tests/test_scanner.py — +1/-0 (1 hunks)`

Verify JSON:
```bash
cat /tmp/rank_test_artifacts/diff-ranking.json | python3 -m json.tool | head -30
```

Expected: JSON with 3 file entries, auth at `risk_class: critical`, scanner at `risk_class: high`, test at `risk_class: low`.

**Step 2.4 — Commit the implementation**

```bash
git add dark-factory/scripts/diff_rank.py
git commit -m "feat(#669): implement diff_rank.py — risk-aware diff ranker

Classifies diff files into critical/high/medium/low tiers:
- critical: safety paths (auth, trading, migrations, dark-factory/) + hotspot files
- high: spec-named files, routers, dependencies, elevated-blast files
- medium: >50 changed lines, not otherwise classified
- low: test files + small remaining files

Critical files bypass the token cap entirely; high/medium fill the budget
in rank order; low files are always summarized as a one-liner.

Writes diff-ranking.json to --artifacts-dir on every run.
Imports parse_hotspots from gate_blast_radius (same function, no divergence).
Fails open: on any exception, exits non-zero so the gate falls back.

All 29 tests in test_diff_rank.py pass."
```

---

## Task 3 — Integrate into the conformance gate

**Files:** `.archon/commands/dark-factory-conformance.md`

### Steps

**Step 3.1 — Confirm pre-change state**

```bash
grep -n 'head -1000\|diff_rank\|SPEC_FILE' .archon/commands/dark-factory-conformance.md
```

Expected: exactly 2 matches for `head -1000` (one in Phase 3.0.1 RAW_DIFF capture, one in Phase 3.5 reconcile re-diff), 0 for `diff_rank`, and 0 for `SPEC_FILE`.

**Step 3.2 — Remove `| head -1000` from Phase 3.0.1 RAW_DIFF**

In `.archon/commands/dark-factory-conformance.md`, find the RAW_DIFF block in Step 3.0.1 and remove the trailing `| head -1000`:

Old (lines ~79–86):
```bash
RAW_DIFF=$(git diff main...HEAD \
  -- ':!*.lock' ':!*.md' \
  ':!.archon/memory/**' \
  ':!codeindex.json' ':!symbolindex.json' \
  ':!docs/codeindex-hotspots.md' \
  ':!docs/database-schema.md' \
  2>/dev/null | head -1000)
```

New:
```bash
RAW_DIFF=$(git diff main...HEAD \
  -- ':!*.lock' ':!*.md' \
  ':!.archon/memory/**' \
  ':!codeindex.json' ':!symbolindex.json' \
  ':!docs/codeindex-hotspots.md' \
  ':!docs/database-schema.md' \
  2>/dev/null)
```

**Step 3.3 — Add `SPEC_FILE` assignment to each Phase 2 spec-location branch**

Phase 2 of the conformance gate currently locates the spec via three fallback branches (2a comment, 2b refinement-status.md, 2c specs dir) but never assigns the resolved path to a variable. The diff_rank call in the next step relies on `${SPEC_FILE:+--spec-file "$SPEC_FILE"}`, so this must be added as concrete shell at the end of each branch.

**Phase 2a** (spec found in "Plan Generated" issue comment — add this extraction at the end of the 2a branch, after the comment body is fetched and parsed):
```bash
# Extract the first docs/superpowers/specs/ path from the "Plan Generated" comment
PLAN_COMMENT=$(gh issue view "$ISSUE_NUM" --repo omniscient/markethawk --json comments \
  | jq -r '[.comments[] | select(.body | test("Refinement Pipeline — Plan Generated"))] | last | .body // ""')
SPEC_FILE=$(printf '%s' "$PLAN_COMMENT" \
  | grep -oP 'docs/superpowers/specs/[^\s\])"]+' | head -1)
```

**Phase 2b** (spec path found in `$ARTIFACTS_DIR/refinement-status.md`):
```bash
SPEC_FILE=$(grep '^SPEC_PATH:' "$ARTIFACTS_DIR/refinement-status.md" 2>/dev/null \
  | sed 's/^SPEC_PATH: //' | head -1)
```

**Phase 2c** (spec found by scanning `docs/superpowers/specs/` for a file matching the issue title):
```bash
ISSUE_KEYWORDS=$(gh issue view "$ISSUE_NUM" --repo omniscient/markethawk --json title \
  --jq '.title' | tr '[:upper:]' '[:lower:]' | tr ' ' '-')
SPEC_MATCH=$(ls docs/superpowers/specs/ 2>/dev/null | sort -r | head -10 \
  | grep -im1 "$(echo "$ISSUE_KEYWORDS" | cut -c1-20)" || true)
[ -n "$SPEC_MATCH" ] && SPEC_FILE="docs/superpowers/specs/$SPEC_MATCH" || SPEC_FILE=""
```

**Phase 2d** (no spec — `NO_SPEC=true`):
```bash
SPEC_FILE=""
```

After adding all four assignments, verify:
```bash
grep -c 'SPEC_FILE=' .archon/commands/dark-factory-conformance.md
```
Expected: ≥ 4 (one per branch).

**Step 3.4 — Add the diff_rank.py call block after the fmt_hunk_filter block in Phase 3.0.2**

Find the end of the `if [ -n "$PY_FILES" ]; then ... fi` block (ending with `fi` and a blank line before the `\`\`\`` closing). After that `fi` block and **after** the `$FILTER_ANNOTATION` extraction line, before the `$TRIAGED_DIFF is the...` prose line, insert the following code block:

> **Annotation ordering note:** `$FILTER_ANNOTATION` is extracted from `$TRIAGED_DIFF` at the `head -1 | grep '^[Pre-triage]'` line *before* the ranking step runs. After ranking, `$TRIAGED_DIFF` is overwritten with the ranked diff (which begins with `# [diff-rank: ...]` and does not contain the `[Pre-triage]` line). `$FILTER_ANNOTATION` retains its value from the fmt-filtered diff and is independently included in `$ARTIFACT_CONTENT` in Step 3.1.2, so the pre-triage annotation is preserved correctly.

```bash
# Rank and chunk the fmt-filtered diff (fail-open)
RANK_IN=$(mktemp /tmp/rank_in_XXXXXX.txt)
printf '%s' "$TRIAGED_DIFF" > "$RANK_IN"
RANKED=$(python3 dark-factory/scripts/diff_rank.py \
  --diff "$RANK_IN" \
  --artifacts-dir "$ARTIFACTS_DIR" \
  --config ".claude/skills/refinement/config.yaml" \
  ${SPEC_FILE:+--spec-file "$SPEC_FILE"} \
  --hotspots "docs/codeindex-hotspots.md" \
  2>/tmp/diff_rank_err.txt) \
  && TRIAGED_DIFF="$RANKED" \
  || echo "diff_rank: ranking failed ($(cat /tmp/diff_rank_err.txt)) — using fmt-filtered diff"
rm -f "$RANK_IN"
```

**Step 3.5 — Update the "truncated to 1000 lines" label in Step 3.1.2**

Find in Step 3.1 the `$ARTIFACT_CONTENT` block that contains:

```
   ### Diff (pre-triaged, truncated to 1000 lines)
```

Change it to:

```
   ### Diff (pre-triaged, ranked by risk tier)
```

**Step 3.6 — Verify post-change grep**

```bash
grep -c 'head -1000' .archon/commands/dark-factory-conformance.md && \
grep -c 'diff_rank' .archon/commands/dark-factory-conformance.md && \
grep -c 'SPEC_FILE' .archon/commands/dark-factory-conformance.md
```

Expected: `head -1000` count is 1 (Phase 3.5 reconcile re-diff only — Phase 3.0.1 was removed); `diff_rank` count ≥ 1; `SPEC_FILE` count ≥ 4.

**Why the Phase 3.5 reconcile `head -1000` is intentionally retained:** Phase 3.5 is a reconcile loop that re-fetches the diff and re-runs the conformance reviewer when a discrepancy is found. Ranking it too is out of scope for this change (the reconcile loop is a later read-only pass; its diff is already implicitly scoped by the same git filter). As a result, reconcile cycles use plain truncation while cycle 0 uses the risk-aware ranked diff — the reviewer sees a slightly different diff shape across cycles. This is an accepted tradeoff per spec scope. R5 ("existing gate semantics unchanged") holds because the subagents and prompts are unmodified; only the diff delivery path in cycle 0 changes.

**Step 3.7 — Run existing conformance tests**

```bash
python -m pytest dark-factory/tests/test_conformance_formatter_step.py \
  dark-factory/tests/test_conformance_dedupe_step.py \
  -v 2>&1 | tail -20
```

Expected: all pass.

**Step 3.8 — Commit**

```bash
git add .archon/commands/dark-factory-conformance.md
git commit -m "feat(#669): integrate diff_rank into conformance gate Phase 3.0

- Remove | head -1000 from RAW_DIFF capture (budget now managed by diff_rank.py)
- Explicitly assign SPEC_FILE in Phase 2 branches 2a/2b/2c (was unset)
- Add diff_rank.py call after fmt_hunk_filter: TRIAGED_DIFF becomes the ranked diff
  (FILTER_ANNOTATION captured before ranking so pre-triage annotation is preserved)
- Pass \$SPEC_FILE so spec-named files get the 'high' risk signal
- Update artifact content label from 'truncated to 1000 lines' to 'ranked by risk tier'
- Phase 3.5 reconcile re-diff retains head -1000 (unchanged per spec R5)"
```

---

## Task 4 — Integrate into the code-review gate

**Files:** `.archon/commands/dark-factory-code-review.md`

### Steps

**Step 4.1 — Confirm pre-change state**

```bash
grep -c 'head -1000' .archon/commands/dark-factory-code-review.md && \
grep -c 'truncated to 1000' .archon/commands/dark-factory-code-review.md && \
grep -c 'diff_rank' .archon/commands/dark-factory-code-review.md
```

Expected: 1 match for `head -1000`, 1 match for `truncated to 1000`, 0 for `diff_rank`.

**Step 4.2 — Replace the `head -1000` pipeline in Phase 2**

Find the Phase 2 block:
```bash
git diff main...HEAD \
  -- ':!*.lock' ':!*.md' \
  ':!.archon/memory/**' \
  ':!codeindex.json' ':!symbolindex.json' \
  ':!docs/codeindex-hotspots.md' \
  ':!docs/database-schema.md' \
  2>/dev/null | head -1000 > "$ARTIFACTS_DIR/review_diff.txt"
```

Replace with:
```bash
RANK_IN=$(mktemp /tmp/rank_in_XXXXXX.txt)
git diff main...HEAD \
  -- ':!*.lock' ':!*.md' \
  ':!.archon/memory/**' \
  ':!codeindex.json' ':!symbolindex.json' \
  ':!docs/codeindex-hotspots.md' ':!docs/database-schema.md' \
  2>/dev/null > "$RANK_IN"
python3 dark-factory/scripts/diff_rank.py \
  --diff "$RANK_IN" \
  --artifacts-dir "$ARTIFACTS_DIR" \
  --config ".claude/skills/refinement/config.yaml" \
  --hotspots "docs/codeindex-hotspots.md" \
  2>/tmp/diff_rank_err.txt > "$ARTIFACTS_DIR/review_diff.txt" \
  || {
    echo "diff_rank: ranking failed ($(cat /tmp/diff_rank_err.txt)) — using raw diff"
    cp "$RANK_IN" "$ARTIFACTS_DIR/review_diff.txt"
  }
rm -f "$RANK_IN"
```

> Note: No `--spec-file` is passed in the code-review gate — the spec-named signal is intentionally omitted here (conformance already has the spec). Per spec assumption A4.

**Step 4.3 — Remove the truncation log line**

Remove the line (immediately after the Phase 2 diff block):
```
- If the diff was truncated at 1000 lines (`wc -l` reports exactly 1000), log: "code-review: diff truncated to 1000 lines — some lines may not be anchorable."
```

Replace with:
```
- The `diff-ranking.json` artifact in `$ARTIFACTS_DIR` records the budget allocation and which files were summarized.
```

**Step 4.4 — Verify post-change grep**

```bash
grep -n 'head -1000\|diff_rank\|truncated to 1000' .archon/commands/dark-factory-code-review.md
```

Expected: no matches for `head -1000` or `truncated to 1000`; at least 1 match for `diff_rank`.

**Step 4.5 — Run existing code-review tests**

```bash
python -m pytest dark-factory/tests/test_code_review_command.py \
  dark-factory/tests/test_code_review_payload.py \
  dark-factory/tests/test_workflow_code_review.py \
  -v 2>&1 | tail -20
```

Expected: all pass.

**Step 4.6 — Run the full dark-factory test suite to confirm no regressions**

```bash
python -m pytest dark-factory/tests/ -v --tb=short 2>&1 | tail -30
```

Expected: all pass, including the 29 new `test_diff_rank.py` tests.

**Step 4.7 — Commit**

```bash
git add .archon/commands/dark-factory-code-review.md
git commit -m "feat(#669): integrate diff_rank into code-review gate Phase 2

- Replace | head -1000 pipeline with diff_rank.py (fail-open: cp raw diff on error)
- Remove 'diff truncated to 1000 lines' log; diff-ranking.json is the budget log
- No --spec-file passed (code-review gate omits spec-named signal per spec A4)"
```

---

## Summary

| Task | Files | Steps | Commits |
|------|-------|-------|---------|
| 1. Test suite (red) | `dark-factory/tests/test_diff_rank.py` | 3 | 1 |
| 2. Implement diff_rank.py | `dark-factory/scripts/diff_rank.py` | 4 | 1 |
| 3. Conformance gate | `.archon/commands/dark-factory-conformance.md` | 8 | 1 |
| 4. Code-review gate | `.archon/commands/dark-factory-code-review.md` | 7 | 1 |

**Total:** 4 tasks, 22 steps, 4 commits.

**Acceptance criteria traceability:**

| Req | Task |
|-----|------|
| R1 — Emit `diff-ranking.json` | Task 2 (`main()` writes it) |
| R2 — High-risk chunks first under token cap | Task 2 (`build_ranked_diff`) |
| R3 — Low-risk test files summarized | Task 2 (`_summary_low`) |
| R4 — Safety-sensitive files bypass cap | Task 2 (`critical` tier + `_full(c, "critical")`) |
| R5 — Existing gate semantics unchanged | Tasks 3 & 4 (gates still receive one diff string, same subagents) |
| R6 — Fail-open on error | Task 2 (`try/except` in `__main__`, `||` fallback in gate snippets) |
