# Dark Factory Formatter-Only Hunk Filter — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Suppress ruff/isort formatter-only line changes in Python files from the diff fed to the conformance reviewer, and add an explicit reviewer-prompt backstop rule. After this fix no `[OOS]` bullet is emitted for ruff output on an in-scope touched file, no Phase 3.6 excision is attempted, and no spillover ticket is filed for formatting noise.

**Architecture:** Two coordinated layers — (1) a deterministic inline Python hunk filter inserted into Phase 3 Step 3.0 of the conformance command that subtracts formatter-delta hunks from the actual diff before the reviewer sees it, and (2) a one-paragraph carve-out added to `conformance-reviewer-prompt.md` as a backstop for interleaved hunks the filter cannot cleanly separate. Layer 1 is load-bearing; Layer 2 absorbs the residual. The filter is Python-only (ruff is the formatter; no TS autoformatter). The filter is a standalone Python script at `dark-factory/scripts/fmt_hunk_filter.py` (clone-read; no image rebuild needed for Layer 1). Layer 2 prompt change requires an image rebuild.

**Tech Stack:** Bash (conformance command), Python 3 stdlib + `ruff` CLI (filter script), pytest (tests).

**Spec:** `docs/superpowers/specs/2026-06-10-dark-factory-scope-enforcement-formatter-filter-design.md`

**Memory pattern applied:** The `dark-factory-ops.md` `[AVOID]` entry for issue #276 explicitly prohibits file-level exclusion — this plan uses hunk-level stripping only, consistent with that entry.

---

## File Structure

| File | Change |
|---|---|
| `dark-factory/scripts/fmt_hunk_filter.py` | **NEW** Pure stdlib Python 3: read raw diff + py-file list → strip formatter-only hunks → annotated filtered diff. |
| `dark-factory/tests/test_fmt_hunk_filter.py` | **NEW** pytest tests for the filter script. |
| `.archon/commands/dark-factory-conformance.md` | **MODIFY** Step 3.0: add filter invocation after the existing `git diff` block. |
| `.claude/skills/refinement/conformance-reviewer-prompt.md` | **MODIFY** `## Out-of-Scope Changes` section: insert formatter exception rule before the `[OOS]` bullet. |

---

## Task 1: Layer 2 — Formatter exception in the reviewer prompt

**Files:**
- Modify: `.claude/skills/refinement/conformance-reviewer-prompt.md`
- Test: `dark-factory/tests/test_conformance_prompt_formatter_rule.py` (create)

- [ ] **Step 1: Write the failing test**

Create `dark-factory/tests/test_conformance_prompt_formatter_rule.py`:

```python
from pathlib import Path

PROMPT = (
    Path(__file__).resolve().parents[2]
    / ".claude" / "skills" / "refinement" / "conformance-reviewer-prompt.md"
)


def test_formatter_exception_rule_present():
    text = PROMPT.read_text(encoding="utf-8")
    assert "## Out-of-Scope Changes" in text, "section anchor missing"
    assert "Formatter / import-ordering exception" in text, "formatter rule not inserted"
    assert "ruff" in text, "rule must name ruff"
    assert "Do NOT emit an `[OOS]` bullet" in text, "rule must contain the exact prohibition"


def test_formatter_rule_precedes_oos_bullet_format():
    text = PROMPT.read_text(encoding="utf-8")
    fmt_pos = text.find("Formatter / import-ordering exception")
    oos_pos = text.find("- [OOS] <file or area>")
    assert fmt_pos != -1, "formatter rule not found"
    assert oos_pos != -1, "[OOS] example bullet not found"
    assert fmt_pos < oos_pos, "formatter rule must appear before the [OOS] bullet example"
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
cd /workspace/markethawk && python -m pytest dark-factory/tests/test_conformance_prompt_formatter_rule.py -v
```

Expected: FAIL — `formatter rule not inserted`.

- [ ] **Step 3: Insert the rule**

In `.claude/skills/refinement/conformance-reviewer-prompt.md`, find the `## Out-of-Scope Changes` section. The current text ends with:

```
List every change in the diff that is NOT (a) spec-named, (b) supporting housekeeping directly backing an (a) change, or (c) strictly required for the in-scope work to compile/run. Include fixes to pre-existing defects even if they appear beneficial.

- [OOS] <file or area> — <one-sentence description of the unrelated change>
```

Insert the following block between the paragraph ending "even if they appear beneficial." and the `- [OOS] <file or area>` line:

```markdown
**Formatter / import-ordering exception:** Reformatting and import re-ordering produced by
`ruff`, `ruff format`, or equivalent linters acting on a Python file that also contains
in-scope changes is **not** an out-of-scope change. Do NOT emit an `[OOS]` bullet for
whitespace rewraps, line-length splits, or isort import reorders in touched `.py` files.
These changes are non-actionable housekeeping — the formatter re-applies them on every
commit. Only flag as `[OOS]` if the reformatting appears in a file with no spec-required
changes.

```

- [ ] **Step 4: Run the test to verify it passes**

```bash
python -m pytest dark-factory/tests/test_conformance_prompt_formatter_rule.py -v
```

Expected: PASS (2 tests).

- [ ] **Step 5: Commit**

```bash
git add .claude/skills/refinement/conformance-reviewer-prompt.md \
        dark-factory/tests/test_conformance_prompt_formatter_rule.py
git commit -m "fix(dark-factory): add formatter exception rule to conformance reviewer prompt [#276]"
```

---

## Task 2: Formatter hunk filter script (`fmt_hunk_filter.py`)

**Files:**
- Create: `dark-factory/scripts/fmt_hunk_filter.py`
- Create: `dark-factory/tests/test_fmt_hunk_filter.py`

- [ ] **Step 1: Write the failing tests**

Create `dark-factory/tests/test_fmt_hunk_filter.py`:

```python
"""
Tests for dark-factory/scripts/fmt_hunk_filter.py.

parse_file_hunks, overlaps, _apply_hunk, and is_formatter_only are tested
directly with synthetic inputs. filter_diff is tested via mocked subprocess.run
so neither git nor ruff needs to be installed. difflib runs for real so the
integration tests cover the actual hunk-comparison path end-to-end.
"""
import sys
import textwrap
from pathlib import Path
from unittest.mock import patch, MagicMock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import fmt_hunk_filter as fhf  # noqa: E402


# ---------------------------------------------------------------------------
# parse_file_hunks
# ---------------------------------------------------------------------------

SAMPLE_DIFF = textwrap.dedent("""\
    diff --git a/backend/app/core/tracing.py b/backend/app/core/tracing.py
    index aaa..bbb 100644
    --- a/backend/app/core/tracing.py
    +++ b/backend/app/core/tracing.py
    @@ -1,4 +1,4 @@
    -import os
    -import sys
    +import sys
    +import os
     x = 1
     y = 2
    @@ -10,3 +10,4 @@
     ctx = {}
    +span = ctx.get("span")
     end = True
""")


def test_parse_file_hunks_returns_two_hunks():
    hunks = fhf.parse_file_hunks(SAMPLE_DIFF, "backend/app/core/tracing.py")
    assert len(hunks) == 2


def test_parse_file_hunks_captures_hunk_lines():
    hunks = fhf.parse_file_hunks(SAMPLE_DIFF, "backend/app/core/tracing.py")
    h0_text = "".join(hunks[0]["lines"])
    assert "-import os\n" in h0_text
    assert "+import sys\n" in h0_text


def test_parse_file_hunks_unknown_file_returns_empty():
    assert fhf.parse_file_hunks(SAMPLE_DIFF, "other/file.py") == []


# ---------------------------------------------------------------------------
# overlaps
# ---------------------------------------------------------------------------

def test_overlaps_true_when_adjacent():
    assert fhf.overlaps(
        {"old_start": 1, "old_count": 3},
        {"old_start": 3, "old_count": 2},
    )


def test_overlaps_false_when_disjoint():
    assert not fhf.overlaps(
        {"old_start": 1, "old_count": 2},
        {"old_start": 5, "old_count": 2},
    )


# ---------------------------------------------------------------------------
# _apply_hunk
# ---------------------------------------------------------------------------

def _make_hunk(old_start, old_count, body_lines):
    """Build a hunk dict with the given body (list of diff lines, no @@ header)."""
    header = f"@@ -{old_start},{old_count} +1,{old_count} @@\n"
    return {
        "old_start": old_start,
        "old_count": old_count,
        "header": header,
        "lines": [header] + body_lines,
    }


def test_apply_hunk_produces_added_and_context_lines():
    hunk = _make_hunk(1, 4, [
        "-import os\n", "-import sys\n",
        "+import sys\n", "+import os\n",
        " x = 1\n", " y = 2\n",
    ])
    result = fhf._apply_hunk(hunk)
    assert result == ["import sys\n", "import os\n", "x = 1\n", "y = 2\n"]


def test_apply_hunk_skips_removed_lines():
    hunk = _make_hunk(1, 1, ["-old_line\n"])
    assert fhf._apply_hunk(hunk) == []


# ---------------------------------------------------------------------------
# is_formatter_only — result-based comparison (representation-independent)
# ---------------------------------------------------------------------------

BASE_LINES = ["import os\n", "import sys\n", "x = 1\n", "y = 2\n"]


def test_is_formatter_only_true_for_reorder_despite_different_diff_grouping():
    # git-style: removes both imports, adds them sorted
    actual = _make_hunk(1, 4, [
        "-import os\n", "-import sys\n",
        "+import sys\n", "+import os\n",
        " x = 1\n", " y = 2\n",
    ])
    # difflib-style minimal edit: keeps import sys in place, moves import os
    fmt = _make_hunk(1, 4, [
        "-import os\n", " import sys\n",
        "+import os\n", " x = 1\n", " y = 2\n",
    ])
    # Both produce ["import sys\n", "import os\n", "x = 1\n", "y = 2\n"]
    assert fhf.is_formatter_only(actual, [fmt], BASE_LINES)


def test_is_formatter_only_false_when_actual_adds_feature_line():
    actual = _make_hunk(1, 4, [
        "-import os\n", "-import sys\n",
        "+import sys\n", "+import os\n",
        "+NEW_FEATURE = True\n",
        " x = 1\n", " y = 2\n",
    ])
    fmt = _make_hunk(1, 4, [
        "-import os\n", " import sys\n",
        "+import os\n", " x = 1\n", " y = 2\n",
    ])
    assert not fhf.is_formatter_only(actual, [fmt], BASE_LINES)


def test_is_formatter_only_false_when_no_overlap():
    actual = _make_hunk(50, 3, ["-old_line\n", "+new_line\n"])
    fmt = _make_hunk(1, 4, ["-import os\n", "+import sys\n"])
    assert not fhf.is_formatter_only(actual, [fmt], BASE_LINES)


# ---------------------------------------------------------------------------
# filter_diff integration — mocks git/ruff; difflib runs for real
# ---------------------------------------------------------------------------

FMT_DIFF = textwrap.dedent("""\
    diff --git a/backend/app/core/tracing.py b/backend/app/core/tracing.py
    index aaa..bbb 100644
    --- a/backend/app/core/tracing.py
    +++ b/backend/app/core/tracing.py
    @@ -1,4 +1,4 @@
    -import os
    -import sys
    +import sys
    +import os
     x = 1
     y = 2
    @@ -10,3 +10,4 @@
     ctx = {}
    +span = ctx.get("span")
     end = True
""")

# Hunk 1 (@@ -1,4): purely isort noise (os/sys → sys/os).
# Hunk 2 (@@ -10,3): real feature line (+span). Both are in the same file.

BASE_CONTENT = "import os\nimport sys\nx = 1\ny = 2\n"
FORMATTED_CONTENT = "import sys\nimport os\nx = 1\ny = 2\n"


def _make_mock_run(base_content, formatted_content):
    def _run(args, **kwargs):
        mock = MagicMock()
        mock.returncode = 0
        mock.stdout = base_content.encode() if "show" in args else b""
        if "format" in args or "check" in args:
            import os as _os
            tmpfile = args[-1]
            with open(tmpfile, "w", encoding="utf-8") as f:
                f.write(formatted_content)
        return mock
    return _run


def test_filter_diff_strips_formatter_only_hunk():
    with patch("fmt_hunk_filter.subprocess.run", side_effect=_make_mock_run(BASE_CONTENT, FORMATTED_CONTENT)):
        with patch("fmt_hunk_filter.shutil.which", return_value="/usr/bin/ruff"):
            filtered, stripped = fhf.filter_diff(FMT_DIFF, ["backend/app/core/tracing.py"])
    assert "backend/app/core/tracing.py" in stripped
    assert "@@ -1,4" not in filtered
    assert "@@ -10,3" in filtered
    assert "+span = ctx.get" in filtered


def test_filter_diff_leaves_interleaved_hunk_intact():
    mixed_diff = textwrap.dedent("""\
        diff --git a/backend/app/core/tracing.py b/backend/app/core/tracing.py
        --- a/backend/app/core/tracing.py
        +++ b/backend/app/core/tracing.py
        @@ -1,4 +1,5 @@
        -import os
        -import sys
        +import sys
        +import os
        +NEW_FEATURE = True
         x = 1
    """)
    with patch("fmt_hunk_filter.subprocess.run", side_effect=_make_mock_run(BASE_CONTENT, FORMATTED_CONTENT)):
        with patch("fmt_hunk_filter.shutil.which", return_value="/usr/bin/ruff"):
            filtered, stripped = fhf.filter_diff(mixed_diff, ["backend/app/core/tracing.py"])
    assert "backend/app/core/tracing.py" not in stripped
    assert "@@ -1,4" in filtered


def test_filter_diff_new_file_skipped():
    new_file_diff = textwrap.dedent("""\
        diff --git a/backend/app/new.py b/backend/app/new.py
        new file mode 100644
        --- /dev/null
        +++ b/backend/app/new.py
        @@ -0,0 +1,3 @@
        +import os
        +x = 1
    """)
    def _run_no_base(args, **kwargs):
        mock = MagicMock()
        mock.returncode = 1
        mock.stdout = b""
        return mock
    with patch("fmt_hunk_filter.subprocess.run", side_effect=_run_no_base):
        with patch("fmt_hunk_filter.shutil.which", return_value="/usr/bin/ruff"):
            filtered, stripped = fhf.filter_diff(new_file_diff, ["backend/app/new.py"])
    assert stripped == []
    assert filtered == new_file_diff


def test_filter_diff_no_ruff_returns_raw():
    with patch("fmt_hunk_filter.shutil.which", return_value=None):
        filtered, stripped = fhf.filter_diff(FMT_DIFF, ["backend/app/core/tracing.py"])
    assert filtered == FMT_DIFF
    assert stripped == []
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
python -m pytest dark-factory/tests/test_fmt_hunk_filter.py -v
```

Expected: FAIL — `ModuleNotFoundError: No module named 'fmt_hunk_filter'`.

- [ ] **Step 3: Create the filter script**

Create `dark-factory/scripts/fmt_hunk_filter.py`:

```python
"""
Formatter-only hunk filter for dark-factory conformance pre-triage.

Usage:
    python3 fmt_hunk_filter.py <diff_file> <py_files_list_file>

Reads the raw unified diff from <diff_file> and the list of .py files from
<py_files_list_file> (one path per line). For each .py file, fetches the base
version from main, runs ruff format + ruff check --fix --select I on a throwaway
copy, computes the formatter delta, then strips hunks from the actual diff that
produce the same file content as the formatter-only transformation. Interleaved
hunks (formatter noise + feature lines that produce a different result) are left
intact — Layer 2 reviewer prompt handles the residual.

Comparison is result-based (representation-independent): for each overlapping
hunk pair, reconstruct the file region each hunk produces and compare. This
correctly handles the case where git diff and difflib.unified_diff group the same
transformation differently (the key failure mode of token-based subset comparison).

Outputs the filtered diff to stdout, with a [Pre-triage] annotation prepended if
any hunks were stripped. On missing ruff, outputs the raw diff unchanged.
"""
import difflib
import os
import re
import shutil
import subprocess
import sys
import tempfile


def parse_file_hunks(diff_text, filepath):
    """Return list of hunk dicts for one file from a unified diff."""
    hunks = []
    cur_hunk = None
    in_file = False

    for line in diff_text.splitlines(keepends=True):
        if line.startswith("+++ b/"):
            in_file = (line[6:].rstrip("\n") == filepath)
            cur_hunk = None
        elif in_file:
            m = re.match(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@", line)
            if m:
                if cur_hunk:
                    hunks.append(cur_hunk)
                cur_hunk = {
                    "old_start": int(m.group(1)),
                    "old_count": int(m.group(2) or 1),
                    "header": line,
                    "lines": [line],
                }
            elif cur_hunk:
                cur_hunk["lines"].append(line)

    if cur_hunk:
        hunks.append(cur_hunk)
    return hunks


def overlaps(h1, h2):
    """True if the old-file line ranges of two hunks overlap."""
    return (
        h1["old_start"] < h2["old_start"] + h2["old_count"]
        and h2["old_start"] < h1["old_start"] + h1["old_count"]
    )


def _apply_hunk(hunk):
    """Return lines produced by hunk: added lines and context lines (no removed)."""
    result = []
    for line in hunk["lines"][1:]:  # Skip @@ header
        if line.startswith("+"):
            result.append(line[1:])
        elif line.startswith(" "):
            result.append(line[1:])
        # '-' lines (removed from base) are skipped
    return result


def is_formatter_only(actual, fmt_hunks, base_lines):
    """
    Check if applying actual hunk to base_lines produces the same file content
    as any overlapping formatter hunk. Uses result-based comparison so it is
    representation-independent: git diff and difflib can group the same
    transformation differently (e.g. import reorder) but produce the same result.

    If the results match → formatter-only → safe to strip.
    If the results differ → interleaved feature+formatter → leave intact.
    If no formatter hunk overlaps → not formatter noise → leave intact.
    """
    actual_new = _apply_hunk(actual)

    for fh in fmt_hunks:
        if not overlaps(actual, fh):
            continue

        fmt_new = _apply_hunk(fh)

        # Build result for the union of both hunks' old-file regions (0-indexed)
        union_start = min(actual["old_start"], fh["old_start"]) - 1
        union_end = max(
            actual["old_start"] + actual["old_count"],
            fh["old_start"] + fh["old_count"],
        )

        actual_applied = (
            base_lines[union_start : actual["old_start"] - 1]
            + actual_new
            + base_lines[actual["old_start"] - 1 + actual["old_count"] : union_end]
        )
        fmt_applied = (
            base_lines[union_start : fh["old_start"] - 1]
            + fmt_new
            + base_lines[fh["old_start"] - 1 + fh["old_count"] : union_end]
        )

        return actual_applied == fmt_applied

    return False


def _run_formatter(content):
    """Apply ruff format + ruff check --fix --select I to content, return result."""
    with tempfile.NamedTemporaryFile(
        suffix=".py", mode="w", delete=False, encoding="utf-8"
    ) as f:
        f.write(content)
        tmp = f.name
    try:
        subprocess.run(["ruff", "format", tmp], capture_output=True)
        subprocess.run(
            ["ruff", "check", "--fix", "--select", "I", tmp], capture_output=True
        )
        with open(tmp, encoding="utf-8") as f:
            return f.read()
    finally:
        os.unlink(tmp)


def filter_diff(raw_diff, py_files):
    """
    Strip formatter-only hunks from raw_diff for each file in py_files.
    Returns (filtered_diff: str, stripped_files: list[str]).
    On missing ruff, returns (raw_diff, []) unchanged.
    """
    if not shutil.which("ruff"):
        return raw_diff, []

    headers_to_strip = {}  # filepath → set of hunk header strings to remove

    for filepath in py_files:
        actual_hunks = parse_file_hunks(raw_diff, filepath)
        if not actual_hunks:
            continue

        proc = subprocess.run(["git", "show", f"main:{filepath}"], capture_output=True)
        if proc.returncode != 0:
            continue  # new file — no base version to compare against

        base = proc.stdout.decode("utf-8", errors="replace")
        fmtd = _run_formatter(base)
        if fmtd == base:
            continue  # formatter makes no changes to this file

        base_lines = base.splitlines(keepends=True)
        diff_lines = list(
            difflib.unified_diff(
                base_lines,
                fmtd.splitlines(keepends=True),
                fromfile=f"a/{filepath}",
                tofile=f"b/{filepath}",
                n=3,
            )
        )
        if not diff_lines:
            continue
        fmt_hunks = parse_file_hunks("".join(diff_lines), filepath)
        if not fmt_hunks:
            continue

        to_strip = {
            ah["header"]
            for ah in actual_hunks
            if is_formatter_only(ah, fmt_hunks, base_lines)
        }
        if to_strip:
            headers_to_strip[filepath] = to_strip

    if not headers_to_strip:
        return raw_diff, []

    # Reconstruct diff, skipping stripped hunk blocks
    output = []
    cur_file = None
    skip = False

    for line in raw_diff.splitlines(keepends=True):
        if line.startswith("diff --git") or line.startswith("--- ") or line.startswith("index "):
            skip = False
            output.append(line)
        elif line.startswith("+++ b/"):
            cur_file = line[6:].rstrip("\n")
            skip = False
            output.append(line)
        elif line.startswith("@@"):
            strip_set = headers_to_strip.get(cur_file, set())
            if line in strip_set:
                skip = True
            else:
                skip = False
                output.append(line)
        elif not skip:
            output.append(line)

    stripped_files = list(headers_to_strip.keys())
    return "".join(output), stripped_files


def main():
    if len(sys.argv) != 3:
        sys.stderr.write("usage: fmt_hunk_filter.py <diff_file> <py_files_list>\n")
        sys.exit(1)

    raw_diff = open(sys.argv[1], encoding="utf-8").read()
    py_files = [l.strip() for l in open(sys.argv[2], encoding="utf-8") if l.strip()]

    if not py_files:
        sys.stdout.write(raw_diff)
        sys.exit(0)

    filtered, stripped_files = filter_diff(raw_diff, py_files)

    annotation = ""
    if stripped_files:
        annotation = (
            f"[Pre-triage] Formatter-only hunks stripped from "
            f"{len(stripped_files)} .py file(s): {', '.join(stripped_files)}\n\n"
        )

    sys.stdout.write(annotation + filtered)


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run the tests to verify they pass**

```bash
python -m pytest dark-factory/tests/test_fmt_hunk_filter.py -v
```

Expected: PASS (all 13 tests).

- [ ] **Step 5: Commit**

```bash
git add dark-factory/scripts/fmt_hunk_filter.py \
        dark-factory/tests/test_fmt_hunk_filter.py
git commit -m "feat(dark-factory): formatter-only hunk filter script [#276]"
```

---

## Task 3: Layer 1 — Wire the filter into conformance Step 3.0

**Files:**
- Modify: `.archon/commands/dark-factory-conformance.md`
- Test: `dark-factory/tests/test_conformance_formatter_step.py` (create)

- [ ] **Step 1: Write the failing test**

Create `dark-factory/tests/test_conformance_formatter_step.py`:

```python
from pathlib import Path

CMD = (
    Path(__file__).resolve().parents[2]
    / ".archon" / "commands" / "dark-factory-conformance.md"
)


def test_step_30_invokes_filter_script():
    text = CMD.read_text(encoding="utf-8")
    assert "fmt_hunk_filter.py" in text, "Step 3.0 must invoke fmt_hunk_filter.py"


def test_step_30_guards_on_ruff_absence_via_script():
    text = CMD.read_text(encoding="utf-8")
    # Script handles missing ruff internally (returns raw diff unchanged)
    assert "fmt_hunk_filter.py" in text


def test_step_30_writes_py_files_list():
    text = CMD.read_text(encoding="utf-8")
    assert "'*.py'" in text or '"*.py"' in text, \
        "Step 3.0 must extract .py file list from git diff --name-only"


def test_step_30_pre_triage_annotation_variable():
    text = CMD.read_text(encoding="utf-8")
    assert "TRIAGED_DIFF" in text, \
        "filtered diff must be stored as TRIAGED_DIFF for Step 3.1"


def test_step_31_uses_triaged_diff():
    text = CMD.read_text(encoding="utf-8")
    # TRIAGED_DIFF must be referenced in Step 3.1's ARTIFACT_CONTENT build
    assert "TRIAGED_DIFF" in text
    triaged_pos = text.find("TRIAGED_DIFF")
    artifact_content_pos = text.find("ARTIFACT_CONTENT")
    assert triaged_pos < artifact_content_pos or text.count("TRIAGED_DIFF") >= 2, \
        "TRIAGED_DIFF must be used when building ARTIFACT_CONTENT"
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
python -m pytest dark-factory/tests/test_conformance_formatter_step.py -v
```

Expected: FAIL — `fmt_hunk_filter.py` not referenced in the command.

- [ ] **Step 3: Replace Step 3.0 in the conformance command**

In `.archon/commands/dark-factory-conformance.md`, replace the entire Step 3.0 section. The **exact on-disk text** to replace includes the git-diff block, the prose sentence, AND the trailing `OOS_LOG` bash block (lines 64–89 of the file). Include all of it in both the "Replace" and "With" targets so neither part is silently dropped.

Replace (full Step 3.0 section, ending just before `### Step 3.1`):

```markdown
### Step 3.0 — Pre-triage: strip housekeeping

Before feeding the diff to the reviewer, strip noise that would pollute the out-of-scope analysis:

```bash
# Get raw diff excluding lock files, auto-generated artifacts, and agent memory
git diff main...HEAD \
  -- ':!*.lock' ':!*.md' \
  ':!.archon/memory/**' \
  ':!codeindex.json' ':!symbolindex.json' \
  ':!docs/codeindex-hotspots.md' \
  ':!docs/database-schema.md' \
  2>/dev/null | head -1000
```

These files are housekeeping that does not belong to the feature's spec surface; excluding them prevents the reviewer from mis-classifying them as out-of-scope.

Also check for an `out-of-scope.md` recorded by the implement agent:
```bash
OOS_LOG=""
if [ -f "$ARTIFACTS_DIR/out-of-scope.md" ]; then
  OOS_LOG=$(cat "$ARTIFACTS_DIR/out-of-scope.md")
fi
```
```

With (expanded Step 3.0, preserving the OOS_LOG block):

````markdown
### Step 3.0 — Pre-triage: strip housekeeping and formatter-only Python hunks

Before feeding the diff to the reviewer, strip noise that would pollute the out-of-scope analysis.

**3.0.1 — Get the raw diff (lock files, generated artifacts, and agent memory excluded):**

```bash
RAW_DIFF=$(git diff main...HEAD \
  -- ':!*.lock' ':!*.md' \
  ':!.archon/memory/**' \
  ':!codeindex.json' ':!symbolindex.json' \
  ':!docs/codeindex-hotspots.md' \
  ':!docs/database-schema.md' \
  2>/dev/null | head -1000)
```

**3.0.2 — Strip formatter-only hunks from .py files (hunk-level, not file-level):**

For each `.py` file in the diff, the filter script fetches the base version from `main`,
applies `ruff format` + `ruff check --fix --select I` to a throwaway copy, computes the
formatter delta, and removes from the diff any hunk whose changed lines are a strict subset
of the formatter delta. Interleaved hunks (formatter noise and feature code share the same
hunk) are left intact — Layer 2 (reviewer prompt) handles the residual.

```bash
# Extract .py files touched by the branch (one per line)
PY_FILES=$(git diff main...HEAD --name-only -- '*.py' 2>/dev/null)

TRIAGED_DIFF="$RAW_DIFF"
FILTER_ANNOTATION=""

if [ -n "$PY_FILES" ]; then
  # Write inputs to temp files
  DIFF_TMP=$(mktemp /tmp/fmt_diff_XXXXXX.txt)
  FILES_TMP=$(mktemp /tmp/fmt_files_XXXXXX.txt)
  printf '%s' "$RAW_DIFF" > "$DIFF_TMP"
  printf '%s\n' $PY_FILES > "$FILES_TMP"

  # Run the hunk filter; on script error fall back to raw diff (fail-open)
  FILTER_OUT=$(python3 dark-factory/scripts/fmt_hunk_filter.py \
    "$DIFF_TMP" "$FILES_TMP" 2>/tmp/fmt_filter_err.txt) \
    && TRIAGED_DIFF="$FILTER_OUT" \
    || echo "pre-triage: fmt_hunk_filter.py failed — using raw diff ($(cat /tmp/fmt_filter_err.txt))"

  rm -f "$DIFF_TMP" "$FILES_TMP"

  # Extract the [Pre-triage] annotation line if present (first line of output)
  FILTER_ANNOTATION=$(printf '%s' "$TRIAGED_DIFF" | head -1 | grep '^\[Pre-triage\]' || true)
  if [ -n "$FILTER_ANNOTATION" ]; then
    echo "pre-triage: $FILTER_ANNOTATION"
  fi
fi
```

`$TRIAGED_DIFF` is the formatter-stripped diff (or the raw diff if no .py files or ruff is
absent). `$FILTER_ANNOTATION` is the one-line informational note (empty if no stripping).

Also check for an `out-of-scope.md` recorded by the implement agent (preserved from original Step 3.0):
```bash
OOS_LOG=""
if [ -f "$ARTIFACTS_DIR/out-of-scope.md" ]; then
  OOS_LOG=$(cat "$ARTIFACTS_DIR/out-of-scope.md")
fi
```
````

Then in **Step 3.1**, replace the reference to the raw git diff with `$TRIAGED_DIFF`. Find the line:

```
2. Build `$ARTIFACT_CONTENT`:
   ```
   ### Implementation Summary
   <contents of $ARTIFACTS_DIR/implementation.md, or "No implementation summary found.">

   ### Out-of-Scope Log (from implement agent)
   <contents of $ARTIFACTS_DIR/out-of-scope.md, or "None recorded.">

   ### Diff (pre-triaged, truncated to 1000 lines)
   <git diff output from Step 3.0>
   ```
```

Replace `<git diff output from Step 3.0>` with:

```
$FILTER_ANNOTATION
$TRIAGED_DIFF
```

So the full artifact content block becomes:

```
2. Build `$ARTIFACT_CONTENT`:
   ```
   ### Implementation Summary
   <contents of $ARTIFACTS_DIR/implementation.md, or "No implementation summary found.">

   ### Out-of-Scope Log (from implement agent)
   <contents of $ARTIFACTS_DIR/out-of-scope.md, or "None recorded.">

   ### Diff (pre-triaged, truncated to 1000 lines)
   $FILTER_ANNOTATION
   $TRIAGED_DIFF
   ```
```

- [ ] **Step 4: Run the tests to verify they pass**

```bash
python -m pytest dark-factory/tests/test_conformance_formatter_step.py -v
```

Expected: PASS (5 tests).

Also confirm the full test suite is green:

```bash
python -m pytest dark-factory/tests/test_fmt_hunk_filter.py \
                  dark-factory/tests/test_conformance_formatter_step.py \
                  dark-factory/tests/test_conformance_prompt_formatter_rule.py -v
```

Expected: PASS (20 tests total).

- [ ] **Step 5: Commit**

```bash
git add .archon/commands/dark-factory-conformance.md \
        dark-factory/tests/test_conformance_formatter_step.py
git commit -m "fix(dark-factory): wire formatter hunk filter into conformance Step 3.0 [#276]"
```

---

## Task 4: Rebuild the container image (Layer 2 propagation)

`conformance-reviewer-prompt.md` is COPYed into the image at `/opt/refinement-skills/` at build
time (per `dark-factory-ops.md` PATTERN: `.claude/skills/refinement/` files require an image
rebuild to propagate). The filter script (`dark-factory/scripts/`) is clone-read and needs no
rebuild.

**Files:**
- (no file changes — image build only)

- [ ] **Step 1: Verify the dark-factory service is defined in the compose file**

```bash
docker compose --profile factory config --services 2>/dev/null | grep dark-factory
```

Expected: `dark-factory` appears in the list.

- [ ] **Step 2: Rebuild the image**

```bash
docker compose --profile factory build dark-factory
```

Expected output ends with `Successfully built ...` (or `=> exporting to image` for BuildKit).

- [ ] **Step 3: Verify the prompt was baked in**

```bash
docker compose --profile factory run --rm dark-factory \
  bash -c "grep -c 'Formatter / import-ordering exception' /opt/refinement-skills/conformance-reviewer-prompt.md"
```

Expected: `1`

- [ ] **Step 4: Commit the build confirmation (no file changes)**

No git commit needed — the image rebuild is not a source change. Log the rebuild in the
implementation summary artifact if one is being written.

---

## Done criteria

- `python -m pytest dark-factory/tests/test_fmt_hunk_filter.py dark-factory/tests/test_conformance_formatter_step.py dark-factory/tests/test_conformance_prompt_formatter_rule.py -v` is green (20 tests).
- `conformance-reviewer-prompt.md` contains the formatter exception rule before the `[OOS]` bullet.
- `dark-factory-conformance.md` Step 3.0 writes `$TRIAGED_DIFF` (via `fmt_hunk_filter.py`) and Step 3.1 uses `$TRIAGED_DIFF` in `$ARTIFACT_CONTENT`.
- `dark-factory/scripts/fmt_hunk_filter.py` exists; `python3 fmt_hunk_filter.py --help` exits without error (or usage: error on wrong args is acceptable).
- Container image rebuilt; `grep` on `/opt/refinement-skills/conformance-reviewer-prompt.md` inside the container finds the new rule.
- No file-level exclusion used anywhere (per `dark-factory-ops.md` [AVOID] for issue #276).
