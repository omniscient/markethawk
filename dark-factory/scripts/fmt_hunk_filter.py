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
        elif line.startswith("\\"):
            pass  # '\\ No newline at end of file' marker — skip
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

        if actual_applied == fmt_applied:
            return True

    return False


def _run_formatter(content):
    """Apply ruff format + ruff check --fix --select I to content, return result.

    Passes --config backend/pyproject.toml so the formatter uses the project's
    line-length (88) and rule-set — temp files in /tmp/ are outside the project
    tree and ruff won't auto-discover the config from there.
    """
    with tempfile.NamedTemporaryFile(
        suffix=".py", mode="w", delete=False, encoding="utf-8"
    ) as f:
        f.write(content)
        tmp = f.name
    try:
        result = subprocess.run(
            ["ruff", "format", "--config", "backend/pyproject.toml", tmp],
            capture_output=True,
        )
        if result.returncode != 0:
            print(
                f"[fmt_hunk_filter] ruff format warning (rc={result.returncode})"
                " — skipping formatter delta for this file",
                file=sys.stderr,
            )
            return content
        result = subprocess.run(
            ["ruff", "check", "--fix", "--select", "I",
             "--config", "backend/pyproject.toml", tmp],
            capture_output=True,
        )
        if result.returncode > 1:
            print(
                f"[fmt_hunk_filter] ruff check warning (rc={result.returncode})"
                " — using partial result",
                file=sys.stderr,
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
        if (
            line.startswith("diff --git")
            or line.startswith("index ")
            or line.startswith("--- a/")
            or line.startswith("--- /dev/null")
        ):
            skip = False
            output.append(line)
        elif line.startswith("+++ b/"):
            cur_file = line[6:].rstrip("\n")
            skip = False
            output.append(line)
        elif cur_file and cur_file in headers_to_strip:
            m = re.match(r"^@@ ", line)
            if m:
                skip = line in headers_to_strip[cur_file]
            if not skip:
                output.append(line)
        else:
            output.append(line)

    stripped_files = list(headers_to_strip.keys())
    annotation = (
        f"[Pre-triage] Formatter-only hunks stripped from "
        f"{len(stripped_files)} .py file(s): {', '.join(stripped_files)}\n"
    )
    return annotation + "".join(output), stripped_files


def main():
    if len(sys.argv) != 3:
        print("Usage: fmt_hunk_filter.py <diff_file> <py_files_list_file>", file=sys.stderr)
        sys.exit(1)

    diff_file = sys.argv[1]
    files_file = sys.argv[2]

    with open(diff_file, encoding="utf-8") as f:
        raw_diff = f.read()

    with open(files_file, encoding="utf-8") as f:
        py_files = [line.strip() for line in f if line.strip()]

    filtered, _ = filter_diff(raw_diff, py_files)
    sys.stdout.write(filtered)


if __name__ == "__main__":
    main()
