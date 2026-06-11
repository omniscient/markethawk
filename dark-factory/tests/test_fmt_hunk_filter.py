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


# ---------------------------------------------------------------------------
# Fix 1: is_formatter_only — loop-and-accumulate (don't return early)
# ---------------------------------------------------------------------------

def test_is_formatter_only_true_when_second_formatter_hunk_matches():
    """First overlapping fmt hunk doesn't match; second does — should still return True."""
    actual = _make_hunk(1, 4, [
        "-import os\n", "-import sys\n",
        "+import sys\n", "+import os\n",
        " x = 1\n", " y = 2\n",
    ])
    # First formatter hunk: overlaps but produces different result (wrong reorder)
    fmt_wrong = _make_hunk(1, 4, [
        "-import os\n", "-import sys\n",
        "+import os\n", "+import sys\n",  # same order = no change = different from actual
        " x = 1\n", " y = 2\n",
    ])
    # Second formatter hunk: overlaps and produces the same result as actual
    fmt_correct = _make_hunk(1, 4, [
        "-import os\n", " import sys\n",
        "+import os\n", " x = 1\n", " y = 2\n",
    ])
    # Pre-fix: returns False (exits on first hunk). Post-fix: returns True.
    assert fhf.is_formatter_only(actual, [fmt_wrong, fmt_correct], BASE_LINES)


# ---------------------------------------------------------------------------
# Fix 2: _apply_hunk — ignore "\ No newline at end of file" marker
# ---------------------------------------------------------------------------

def test_apply_hunk_ignores_no_newline_marker():
    """Lines starting with \\ (the diff no-newline marker) should be silently skipped."""
    hunk = _make_hunk(1, 1, ["+last line", "\\ No newline at end of file\n"])
    result = fhf._apply_hunk(hunk)
    assert result == ["last line"]


# ---------------------------------------------------------------------------
# Fix 3: _run_formatter — check returncode; fallback on ruff format error
# ---------------------------------------------------------------------------

def test_run_formatter_returns_content_unchanged_on_ruff_format_error(capsys):
    """If ruff format exits non-zero, _run_formatter returns the original content."""
    content = "import os\nprint('hello')\n"

    def _mock_run_format_error(args, **kwargs):
        m = MagicMock()
        m.returncode = 2  # ruff format error (e.g. bad config)
        m.stdout = b""
        return m

    with patch("fmt_hunk_filter.subprocess.run", side_effect=_mock_run_format_error):
        result = fhf._run_formatter(content)

    assert result == content
    captured = capsys.readouterr()
    assert "warning" in captured.err.lower() or "fmt_hunk_filter" in captured.err


# ---------------------------------------------------------------------------
# Fix 4: reconstruction loop — removed body lines starting with "--- " are not headers
# ---------------------------------------------------------------------------

def test_filter_diff_body_line_starting_with_triple_dash_not_treated_as_file_header():
    """
    A removed body line whose content starts with '-- ' (diff line '--- ...') must not
    reset skip=False. The stripped hunk tail must still be suppressed after the fix.

    Scenario: file has [import os, import sys, -- deprecated]. The formatter reorders
    imports and removes the '-- deprecated' line (mocked), producing the same result as
    the actual diff. The single hunk is formatter-only, gets stripped. The '--- deprecated'
    body line in the stripped hunk must not trigger the file-header branch and re-enable
    emission of subsequent hunk lines.
    """
    diff_with_dash_body = textwrap.dedent("""\
        diff --git a/backend/app/core/tracing.py b/backend/app/core/tracing.py
        index aaa..bbb 100644
        --- a/backend/app/core/tracing.py
        +++ b/backend/app/core/tracing.py
        @@ -1,3 +1,2 @@
        -import os
        -import sys
        +import sys
        +import os
        --- deprecated
    """)

    # base has the '-- deprecated' line; formatter removes it and reorders imports
    base_content = "import os\nimport sys\n-- deprecated\n"
    formatted_content = "import sys\nimport os\n"

    with patch("fmt_hunk_filter.subprocess.run", side_effect=_make_mock_run(base_content, formatted_content)):
        with patch("fmt_hunk_filter.shutil.which", return_value="/usr/bin/ruff"):
            filtered, stripped = fhf.filter_diff(
                diff_with_dash_body, ["backend/app/core/tracing.py"]
            )

    # The formatter-only hunk should be stripped.
    assert "backend/app/core/tracing.py" in stripped
    assert "@@ -1,3" not in filtered
    # The '--- deprecated' removed body line must NOT appear in the filtered output.
    # Pre-fix: it would appear because the reconstruction loop misidentified it as a
    # file header and reset skip=False.
    assert "--- deprecated" not in filtered
