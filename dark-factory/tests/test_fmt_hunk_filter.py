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
