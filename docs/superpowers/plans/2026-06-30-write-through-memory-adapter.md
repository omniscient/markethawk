# Plan: Write-Through Memory Adapter — Flat-File Only (#648)

**Date:** 2026-06-30
**Issue:** [#648 — Build write-through memory adapter for agentmemory and .archon markdown](https://github.com/omniscient/markethawk/issues/648)
**Epic:** #643 (Improve Dark Factory memory system using agent-native memory architecture)
**Related:** #645 (schema), #646 (read adapter), #649 (index substrate / import)

---

## Goal

Replace the bash-only `write_memory_entry()` in `gate_lib.sh` with a Python adapter
(`memory_write.py`) that is fully unit-tested, tags every entry with `agent:`/`scope:`/`path:`
metadata per the #645 contract, and writes a best-effort stub record to `.archon/memory/index.jsonl`.
Markdown files remain the source of truth. No network I/O; no REST sidecar; no external
dependencies beyond Python 3 stdlib.

## Architecture

| Concern | Decision |
|---|---|
| Write ownership | `memory_write.py` owns all write logic (routing already in bash via `route_memory_file()`) |
| Dedup | Normalized substring match (lowercase + whitespace collapse + punctuation strip); on match: in-place `date:`/`expires:` update |
| index.jsonl | Best-effort append; symmetric skip when markdown write is no-op |
| bash integration | `write_memory_entry()` body becomes a 5-line `python3 "$(dirname "${BASH_SOURCE[0]}")/memory_write.py"` call |
| Testing | pytest unit tests for all write-pipeline steps; shell integration test for the gate_lib.sh delegation |

## Tech Stack

- **Python 3 stdlib** — `argparse`, `json`, `re`, `pathlib`, `datetime`, `calendar`, `sys`
- **pytest** — unit tests, no fixtures beyond `tmp_path`
- **bash** — 5-line delegation wrapper in `gate_lib.sh`

---

## File Structure

```
dark-factory/
  scripts/
    memory_write.py            ← new — full write adapter
    gate_lib.sh                ← modified — write_memory_entry() body replaced
  tests/
    test_memory_write.py       ← new — pytest unit tests
    test_memory_write_gate.sh  ← new — bash integration test for gate_lib.sh delegation
.archon/memory/
  index.jsonl                  ← new (created on first write by memory_write.py)
  *.md                         ← existing — source of truth, extended with agent:/scope: tags
```

---

## Task 1 — Write failing pytest tests + implement `memory_write.py` core markdown pipeline

**Files:** `dark-factory/tests/test_memory_write.py`, `dark-factory/scripts/memory_write.py`

### TDD steps

**Step 1.1 — Write the failing test file**

Create `dark-factory/tests/test_memory_write.py`:

```python
"""
Unit tests for memory_write.py — markdown write pipeline.
Tests are pure filesystem: no mocking, no network.
Run from repo root: pytest dark-factory/tests/test_memory_write.py -v
"""
import json
import re
import subprocess
import sys
from datetime import date, timedelta
from pathlib import Path

import pytest

SCRIPT = Path(__file__).parent.parent / "scripts" / "memory_write.py"


def run(*args):
    """Run memory_write.py and return CompletedProcess."""
    return subprocess.run(
        [sys.executable, str(SCRIPT)] + list(args),
        capture_output=True,
        text=True,
    )


# ── fixtures ────────────────────────────────────────────────────────────────

@pytest.fixture
def md_empty(tmp_path):
    """Markdown file with PROVISIONAL delimiter, no entries."""
    f = tmp_path / "backend-patterns.md"
    f.write_text("# Backend Patterns\n\n---\n<!-- PROVISIONAL -->\n")
    return f


@pytest.fixture
def md_at_cap(tmp_path):
    """Markdown file with exactly 29 existing [AVOID] entries."""
    f = tmp_path / "dark-factory-ops.md"
    lines = ["# Dark Factory Ops\n\n"]
    for i in range(29):
        lines.append(
            f"- [AVOID] Entry {i} "
            f"<!-- issue:#1 date:2026-01-01 expires:2027-01-01 source:refine -->\n"
        )
    lines.append("---\n<!-- PROVISIONAL -->\n")
    f.write_text("".join(lines))
    return f


@pytest.fixture
def md_with_expired(tmp_path):
    """Markdown file with one expired entry and one valid entry."""
    f = tmp_path / "codebase-patterns.md"
    yesterday = (date.today() - timedelta(days=1)).strftime("%Y-%m-%d")
    f.write_text(
        f"# Codebase Patterns\n\n"
        f"- [AVOID] stale lesson "
        f"<!-- issue:#1 date:2025-01-01 expires:{yesterday} source:refine -->\n"
        f"- [AVOID] valid lesson "
        f"<!-- issue:#2 date:2026-01-01 expires:2027-01-01 source:refine -->\n"
        f"---\n<!-- PROVISIONAL -->\n"
    )
    return f


# ── scope derivation ────────────────────────────────────────────────────────

class TestScopeDerivation:
    def test_backend_patterns(self, tmp_path):
        md = tmp_path / "backend-patterns.md"
        md.write_text("# Backend Patterns\n\n---\n")
        run("--target", str(md), "--path-prefix", "backend/app/",
            "--text", "avoid this", "--source", "conformance", "--issue", "648")
        assert "scope:backend" in md.read_text()

    def test_dark_factory_ops(self, tmp_path):
        md = tmp_path / "dark-factory-ops.md"
        md.write_text("# Dark Factory Ops\n\n---\n")
        run("--target", str(md), "--path-prefix", "dark-factory/scripts/",
            "--text", "avoid this", "--source", "code-review", "--issue", "648")
        assert "scope:dark-factory" in md.read_text()

    def test_frontend_patterns(self, tmp_path):
        md = tmp_path / "frontend-patterns.md"
        md.write_text("# Frontend Patterns\n\n---\n")
        run("--target", str(md), "--path-prefix", "frontend/src/",
            "--text", "avoid this", "--source", "refine", "--issue", "648")
        assert "scope:frontend" in md.read_text()

    def test_architecture(self, tmp_path):
        md = tmp_path / "architecture.md"
        md.write_text("# Architecture\n\n---\n")
        run("--target", str(md), "--path-prefix", "ARCHITECTURE.md",
            "--text", "avoid this", "--source", "implement", "--issue", "648")
        assert "scope:architecture" in md.read_text()

    def test_codebase_patterns(self, tmp_path):
        md = tmp_path / "codebase-patterns.md"
        md.write_text("# Codebase Patterns\n\n---\n")
        run("--target", str(md), "--path-prefix", "docs/",
            "--text", "avoid this", "--source", "implement", "--issue", "648")
        assert "scope:codebase" in md.read_text()


# ── markdown write ──────────────────────────────────────────────────────────

class TestMarkdownWrite:
    def test_exits_0_on_success(self, md_empty):
        result = run("--target", str(md_empty), "--path-prefix", "backend/app/",
                     "--text", "avoid mocks in tests", "--source", "conformance", "--issue", "648")
        assert result.returncode == 0

    def test_entry_inserted_before_provisional_delimiter(self, md_empty):
        run("--target", str(md_empty), "--path-prefix", "backend/app/",
            "--text", "avoid mocks in tests", "--source", "conformance", "--issue", "648")
        lines = md_empty.read_text().splitlines()
        avoid_idx = next(i for i, l in enumerate(lines) if "[AVOID]" in l)
        delim_idx = next(i for i, l in enumerate(lines) if l == "---")
        assert avoid_idx < delim_idx

    def test_entry_has_all_required_tags(self, md_empty):
        run("--target", str(md_empty), "--path-prefix", "backend/app/",
            "--text", "avoid mocks in tests", "--source", "conformance", "--issue", "648")
        content = md_empty.read_text()
        today = date.today().strftime("%Y-%m-%d")
        assert "agent:conformance" in content
        assert "scope:backend" in content
        assert "path:backend/app/" in content
        assert "source:conformance" in content
        assert "issue:#648" in content
        assert f"date:{today}" in content

    def test_expires_is_approximately_6_months_out(self, md_empty):
        run("--target", str(md_empty), "--path-prefix", "backend/app/",
            "--text", "avoid mocks", "--source", "conformance", "--issue", "648")
        content = md_empty.read_text()
        m = re.search(r"expires:(\d{4}-\d{2}-\d{2})", content)
        assert m, "expires: tag missing"
        expires = date.fromisoformat(m.group(1))
        delta = (expires - date.today()).days
        assert 179 <= delta <= 185, f"expires should be ~6 months out, got {delta} days"

    def test_append_when_no_delimiter(self, tmp_path):
        md = tmp_path / "codebase-patterns.md"
        md.write_text("# Codebase Patterns\n\n")
        run("--target", str(md), "--path-prefix", "docs/",
            "--text", "some lesson", "--source", "implement", "--issue", "10")
        assert "[AVOID]" in md.read_text()

    def test_exit_1_on_empty_text(self, md_empty):
        result = run("--target", str(md_empty), "--path-prefix", "backend/app/",
                     "--text", "", "--source", "conformance", "--issue", "648")
        assert result.returncode == 1


# ── normalized dedup ────────────────────────────────────────────────────────

class TestNormalizedDedup:
    def test_exact_duplicate_skipped(self, md_empty):
        text = "avoid using mocks in tests"
        run("--target", str(md_empty), "--path-prefix", "backend/app/",
            "--text", text, "--source", "conformance", "--issue", "648")
        run("--target", str(md_empty), "--path-prefix", "backend/app/",
            "--text", text, "--source", "conformance", "--issue", "648")
        assert md_empty.read_text().count("[AVOID]") == 1

    def test_case_and_whitespace_normalized(self, md_empty):
        run("--target", str(md_empty), "--path-prefix", "backend/app/",
            "--text", "avoid using mocks in tests", "--source", "conformance", "--issue", "648")
        run("--target", str(md_empty), "--path-prefix", "backend/app/",
            "--text", "Avoid  Using  Mocks  In  Tests.", "--source", "conformance", "--issue", "648")
        assert md_empty.read_text().count("[AVOID]") == 1

    def test_distinct_text_is_not_deduped(self, md_empty):
        run("--target", str(md_empty), "--path-prefix", "backend/app/",
            "--text", "avoid using mocks in tests", "--source", "conformance", "--issue", "648")
        run("--target", str(md_empty), "--path-prefix", "backend/app/",
            "--text", "avoid global state in celery tasks", "--source", "conformance", "--issue", "648")
        assert md_empty.read_text().count("[AVOID]") == 2

    def test_dedup_exits_0(self, md_empty):
        text = "avoid using mocks"
        run("--target", str(md_empty), "--path-prefix", "backend/app/",
            "--text", text, "--source", "conformance", "--issue", "648")
        result = run("--target", str(md_empty), "--path-prefix", "backend/app/",
                     "--text", text, "--source", "conformance", "--issue", "648")
        assert result.returncode == 0


# ── reinforcement ───────────────────────────────────────────────────────────

class TestReinforcement:
    def test_reinforce_updates_date_and_expires_in_place(self, md_empty):
        text = "avoid mocks in integration tests"
        # Write initial entry with a past date by hacking the file after first write
        run("--target", str(md_empty), "--path-prefix", "backend/app/",
            "--text", text, "--source", "conformance", "--issue", "648")
        # Backdate the written entry
        content = md_empty.read_text()
        content = re.sub(r"date:\d{4}-\d{2}-\d{2}", "date:2025-01-01", content)
        content = re.sub(r"expires:\d{4}-\d{2}-\d{2}", "expires:2025-07-01", content)
        md_empty.write_text(content)

        # Normalized duplicate — should reinforce
        run("--target", str(md_empty), "--path-prefix", "backend/app/",
            "--text", "Avoid  Mocks  In  Integration  Tests.", "--source", "conformance", "--issue", "700")

        result_content = md_empty.read_text()
        # Still exactly one entry
        assert result_content.count("[AVOID]") == 1
        # date updated to today
        today = date.today().strftime("%Y-%m-%d")
        assert f"date:{today}" in result_content

    def test_reinforce_exits_0(self, md_empty):
        text = "avoid this pattern"
        run("--target", str(md_empty), "--path-prefix", "backend/app/",
            "--text", text, "--source", "conformance", "--issue", "648")
        result = run("--target", str(md_empty), "--path-prefix", "backend/app/",
                     "--text", "Avoid  This  Pattern.", "--source", "conformance", "--issue", "700")
        assert result.returncode == 0


# ── cap enforcement ─────────────────────────────────────────────────────────

class TestCapEnforcement:
    def test_30th_entry_succeeds(self, md_at_cap):
        result = run("--target", str(md_at_cap), "--path-prefix", "dark-factory/",
                     "--text", "entry 30", "--source", "conformance", "--issue", "648")
        assert result.returncode == 0
        assert md_at_cap.read_text().count("[AVOID]") == 30

    def test_31st_entry_skipped(self, md_at_cap):
        run("--target", str(md_at_cap), "--path-prefix", "dark-factory/",
            "--text", "entry 30", "--source", "conformance", "--issue", "648")
        result = run("--target", str(md_at_cap), "--path-prefix", "dark-factory/",
                     "--text", "entry 31 — completely unique text here", "--source", "conformance",
                     "--issue", "648")
        assert result.returncode == 0
        assert md_at_cap.read_text().count("[AVOID]") == 30


# ── expiry cleanup ──────────────────────────────────────────────────────────

class TestExpiryCleanup:
    def test_expired_entries_removed_before_new_write(self, md_with_expired):
        run("--target", str(md_with_expired), "--path-prefix", "docs/",
            "--text", "new lesson", "--source", "implement", "--issue", "648")
        content = md_with_expired.read_text()
        assert "stale lesson" not in content
        assert "valid lesson" in content
        assert "new lesson" in content

    def test_only_expired_entries_removed(self, md_with_expired):
        run("--target", str(md_with_expired), "--path-prefix", "docs/",
            "--text", "new lesson", "--source", "implement", "--issue", "648")
        content = md_with_expired.read_text()
        assert content.count("[AVOID]") == 2  # valid + new
```

**Step 1.2 — Verify tests fail (module not found)**

```bash
cd /workspace/markethawk
docker compose exec dark-factory bash -c "
  cd /workspace/markethawk &&
  python -m pytest dark-factory/tests/test_memory_write.py -v --tb=short 2>&1 | head -30
"
```

Expected output includes:
```
ModuleNotFoundError  or  FileNotFoundError: [Errno 2] No such file or directory: '.../memory_write.py'
```
(All tests error/fail — confirming TDD red phase.)

**Step 1.3 — Implement `memory_write.py`**

Create `dark-factory/scripts/memory_write.py`:

```python
#!/usr/bin/env python3
"""Write-through memory adapter — flat-file only.

Ports write logic from gate_lib.sh::write_memory_entry() to Python,
adding normalized dedup, agent/scope tagging, and index.jsonl stub write.

Usage:
    python3 memory_write.py \\
        --target      <path to .archon/memory/*.md>        \\
        --path-prefix <e.g. dark-factory/scripts/>         \\
        --text        <core lesson text (no tag prefix)>    \\
        --source      <conformance|code-review|refine|implement> \\
        --issue       <issue number>

Exit 0: write succeeded or intentionally skipped (dedup/cap).
Exit 1: markdown I/O error. index.jsonl failures do NOT set exit 1.
"""
import argparse
import calendar
import json
import re
import sys
from datetime import date
from pathlib import Path

_ENTRY_RE = re.compile(r"^\- \[(PATTERN|AVOID|FIX)\] ")


def _normalize(text):
    """Lowercase, collapse whitespace, strip trailing punctuation."""
    text = text.lower()
    text = re.sub(r"\s+", " ", text).strip()
    text = text.rstrip(".,;:!?")
    return text


def _scope_from_stem(stem):
    """Derive scope from markdown filename stem.

    backend-patterns  → backend
    dark-factory-ops  → dark-factory
    frontend-patterns → frontend
    architecture      → architecture
    codebase-patterns → codebase
    """
    for suffix in ("-patterns", "-ops"):
        if stem.endswith(suffix):
            return stem[: -len(suffix)]
    return stem


def _add_months(d, months):
    """Add months to a date, clamping to the last day of the resulting month."""
    month = d.month + months
    year = d.year + (month - 1) // 12
    month = (month - 1) % 12 + 1
    last_day = calendar.monthrange(year, month)[1]
    return date(year, month, min(d.day, last_day))


def _extract_body(line):
    """Extract lesson text from a [PATTERN]/[AVOID]/[FIX] line (before <!-- comment)."""
    m = re.match(r"^\- \[(?:PATTERN|AVOID|FIX)\] (.*?)(?:\s*<!--.*)?$", line)
    return m.group(1).strip() if m else ""


def _is_expired(line, today_str):
    m = re.search(r"expires:(\d{4}-\d{2}-\d{2})", line)
    return bool(m) and m.group(1) < today_str


def _parse_args():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--target",      required=True,  help="Path to .archon/memory/*.md")
    p.add_argument("--path-prefix", required=True,  dest="path_prefix")
    p.add_argument("--text",        required=True)
    p.add_argument("--source",      required=True)
    p.add_argument("--issue",       required=True,  type=int)
    return p.parse_args()


def main():
    args = _parse_args()
    target = Path(args.target)
    today = date.today()
    today_str = today.strftime("%Y-%m-%d")
    expires_str = _add_months(today, 6).strftime("%Y-%m-%d")
    scope = _scope_from_stem(target.stem)
    agent_id = args.source

    if not args.text.strip():
        print("memory-write: error: --text is empty", file=sys.stderr)
        sys.exit(1)

    # Load existing content (create file as empty if it doesn't exist)
    try:
        raw = target.read_text() if target.exists() else ""
    except OSError as exc:
        print(f"memory-write: error reading {target}: {exc}", file=sys.stderr)
        sys.exit(1)

    lines = raw.splitlines(keepends=True)

    # Step 1: Expiry cleanup — strip expired authoritative entries
    lines = [
        l for l in lines
        if not (_ENTRY_RE.match(l) and _is_expired(l, today_str))
    ]

    # Step 2: Normalized dedup check + reinforcement
    candidate_norm = _normalize(args.text)
    skip_index = False

    for i, line in enumerate(lines):
        if not _ENTRY_RE.match(line):
            continue
        if _normalize(_extract_body(line)) == candidate_norm:
            # REINFORCE: update date: and expires: in-place; one-line diff
            updated = re.sub(r"date:\d{4}-\d{2}-\d{2}", f"date:{today_str}", line)
            updated = re.sub(r"expires:\d{4}-\d{2}-\d{2}", f"expires:{expires_str}", updated)
            lines[i] = updated
            try:
                target.write_text("".join(lines))
            except OSError as exc:
                print(f"memory-write: error writing {target}: {exc}", file=sys.stderr)
                sys.exit(1)
            print(f"memory-write: reinforced existing entry in {target}")
            skip_index = True
            break
    else:
        # Step 3: Cap check (30 authoritative entries per file)
        count = sum(1 for l in lines if _ENTRY_RE.match(l))
        if count >= 30:
            print(f"memory-write: cap reached ({count} entries) in {target} — skipping write")
            skip_index = True
        else:
            # Step 4: Build entry with full tag set
            entry = (
                f"- [AVOID] {args.text} "
                f"<!-- issue:#{args.issue} date:{today_str} expires:{expires_str} "
                f"source:{args.source} agent:{agent_id} scope:{scope} "
                f"path:{args.path_prefix} -->"
            )

            # Step 5: Insert before --- delimiter, or append if absent
            delim_idx = next(
                (i for i, l in enumerate(lines) if l.rstrip("\n") == "---"),
                None,
            )
            if delim_idx is not None:
                lines.insert(delim_idx, entry + "\n")
            else:
                if lines and not lines[-1].endswith("\n"):
                    lines.append("\n")
                lines.append(entry + "\n")

            # Write markdown (source of truth)
            try:
                target.write_text("".join(lines))
            except OSError as exc:
                print(f"memory-write: error writing {target}: {exc}", file=sys.stderr)
                sys.exit(1)

    # Step 6: Best-effort index.jsonl write (skip when markdown was a no-op)
    if not skip_index:
        _write_index(target.parent / "index.jsonl", args, agent_id, scope, today_str, expires_str)

    sys.exit(0)


def _write_index(index_path, args, agent_id, scope, today_str, expires_str):
    record = {
        "project":      "markethawk",
        "type":         "avoidance",
        "status":       "active",
        "source":       args.source,
        "agent_id":     agent_id,
        "phase":        args.source,
        "issue_number": args.issue,
        "files":        [args.path_prefix],
        "scope":        scope,
        "content":      args.text,
        "created_at":   today_str,
        "expires_at":   expires_str,
    }
    try:
        with index_path.open("a") as fh:
            fh.write(json.dumps(record) + "\n")
    except OSError as exc:
        print(f"memory-write: WARNING: index.jsonl: write failed ({exc})", file=sys.stderr)


if __name__ == "__main__":
    main()
```

**Step 1.4 — Verify all tests pass**

```bash
docker compose exec dark-factory bash -c "
  cd /workspace/markethawk &&
  python -m pytest dark-factory/tests/test_memory_write.py -v 2>&1
"
```

Expected output (all green):
```
test_memory_write.py::TestScopeDerivation::test_backend_patterns PASSED
test_memory_write.py::TestScopeDerivation::test_dark_factory_ops PASSED
test_memory_write.py::TestScopeDerivation::test_frontend_patterns PASSED
test_memory_write.py::TestScopeDerivation::test_architecture PASSED
test_memory_write.py::TestScopeDerivation::test_codebase_patterns PASSED
test_memory_write.py::TestMarkdownWrite::test_exits_0_on_success PASSED
test_memory_write.py::TestMarkdownWrite::test_entry_inserted_before_provisional_delimiter PASSED
test_memory_write.py::TestMarkdownWrite::test_entry_has_all_required_tags PASSED
test_memory_write.py::TestMarkdownWrite::test_expires_is_approximately_6_months_out PASSED
test_memory_write.py::TestMarkdownWrite::test_append_when_no_delimiter PASSED
test_memory_write.py::TestMarkdownWrite::test_exit_1_on_empty_text PASSED
test_memory_write.py::TestNormalizedDedup::test_exact_duplicate_skipped PASSED
test_memory_write.py::TestNormalizedDedup::test_case_and_whitespace_normalized PASSED
test_memory_write.py::TestNormalizedDedup::test_distinct_text_is_not_deduped PASSED
test_memory_write.py::TestNormalizedDedup::test_dedup_exits_0 PASSED
test_memory_write.py::TestReinforcement::test_reinforce_updates_date_and_expires_in_place PASSED
test_memory_write.py::TestReinforcement::test_reinforce_exits_0 PASSED
test_memory_write.py::TestCapEnforcement::test_30th_entry_succeeds PASSED
test_memory_write.py::TestCapEnforcement::test_31st_entry_skipped PASSED
test_memory_write.py::TestExpiryCleanup::test_expired_entries_removed_before_new_write PASSED
test_memory_write.py::TestExpiryCleanup::test_only_expired_entries_removed PASSED
============================== 21 passed in X.XXs ===============================
```

**Step 1.5 — Commit**

```bash
git add dark-factory/scripts/memory_write.py dark-factory/tests/test_memory_write.py
git commit -m "feat: add memory_write.py with markdown write pipeline (#648)"
```

---

## Task 2 — Add `index.jsonl` tests + verify implementation

**Files:** `dark-factory/tests/test_memory_write.py` (extend), `dark-factory/scripts/memory_write.py` (already implements `_write_index`)

The `_write_index` function is already in memory_write.py from Task 1. This task adds the missing pytest coverage for index.jsonl behaviour, which ensures the implementation is fully tested before the gate_lib.sh delegation wires it into the live pipeline.

### TDD steps

**Step 2.1 — Append index.jsonl tests to the test file**

Add a new `TestIndexJsonl` class at the bottom of
`dark-factory/tests/test_memory_write.py`:

```python
# ── index.jsonl ─────────────────────────────────────────────────────────────

class TestIndexJsonl:
    def test_successful_write_creates_index_next_to_target(self, md_empty):
        run("--target", str(md_empty), "--path-prefix", "backend/app/",
            "--text", "avoid mocks", "--source", "conformance", "--issue", "648")
        index = md_empty.parent / "index.jsonl"
        assert index.exists(), "index.jsonl should be created on first write"

    def test_index_record_has_required_fields(self, md_empty):
        run("--target", str(md_empty), "--path-prefix", "backend/app/",
            "--text", "avoid mocks", "--source", "conformance", "--issue", "648")
        record = json.loads((md_empty.parent / "index.jsonl").read_text().strip())
        assert record["agent_id"] == "conformance"
        assert record["scope"] == "backend"
        assert record["content"] == "avoid mocks"
        assert record["issue_number"] == 648
        assert record["files"] == ["backend/app/"]
        assert record["project"] == "markethawk"
        assert record["type"] == "avoidance"
        assert record["status"] == "active"

    def test_second_write_appends_second_record(self, md_empty):
        run("--target", str(md_empty), "--path-prefix", "backend/app/",
            "--text", "avoid mocks", "--source", "conformance", "--issue", "648")
        run("--target", str(md_empty), "--path-prefix", "backend/app/",
            "--text", "avoid global state", "--source", "conformance", "--issue", "648")
        lines = (md_empty.parent / "index.jsonl").read_text().strip().splitlines()
        assert len(lines) == 2
        assert json.loads(lines[0])["content"] == "avoid mocks"
        assert json.loads(lines[1])["content"] == "avoid global state"

    def test_dedup_skip_does_not_append_to_index(self, md_empty):
        run("--target", str(md_empty), "--path-prefix", "backend/app/",
            "--text", "avoid mocks", "--source", "conformance", "--issue", "648")
        first = (md_empty.parent / "index.jsonl").read_text()
        # normalized duplicate
        run("--target", str(md_empty), "--path-prefix", "backend/app/",
            "--text", "AVOID MOCKS.", "--source", "conformance", "--issue", "648")
        assert (md_empty.parent / "index.jsonl").read_text() == first

    def test_cap_skip_does_not_append_to_index(self, md_at_cap):
        # md_at_cap has 29 entries; write 30th (should succeed and append to index)
        run("--target", str(md_at_cap), "--path-prefix", "dark-factory/",
            "--text", "entry 30", "--source", "conformance", "--issue", "648")
        first = (md_at_cap.parent / "index.jsonl").read_text()
        # 31st write — cap hit, no index append
        run("--target", str(md_at_cap), "--path-prefix", "dark-factory/",
            "--text", "entry 31 unique text that does not exist yet", "--source", "conformance",
            "--issue", "648")
        assert (md_at_cap.parent / "index.jsonl").read_text() == first

    def test_index_io_error_is_nonfatal(self, md_empty):
        """index.jsonl I/O failure must not set exit 1."""
        index = md_empty.parent / "index.jsonl"
        index.write_text("")
        index.chmod(0o000)
        try:
            result = run("--target", str(md_empty), "--path-prefix", "backend/app/",
                         "--text", "avoid mocks", "--source", "conformance", "--issue", "648")
            assert result.returncode == 0
            # Markdown was still written
            assert "[AVOID]" in md_empty.read_text()
            # Warning emitted to stderr
            assert "index.jsonl" in result.stderr
        finally:
            index.chmod(0o644)
```

**Step 2.2 — Verify new tests pass (implementation already complete)**

```bash
docker compose exec dark-factory bash -c "
  cd /workspace/markethawk &&
  python -m pytest dark-factory/tests/test_memory_write.py -v 2>&1
"
```

Expected:
```
============================== 27 passed in X.XXs ===============================
```

**Step 2.3 — Commit**

```bash
git add dark-factory/tests/test_memory_write.py
git commit -m "test: add index.jsonl coverage to test_memory_write.py (#648)"
```

---

## Task 3 — Update `gate_lib.sh::write_memory_entry()` to delegate to `memory_write.py`

**Files:** `dark-factory/scripts/gate_lib.sh` (modify), `dark-factory/tests/test_memory_write_gate.sh` (new)

Per the memory pattern from `dark-factory-ops.md`: use
`$(dirname "${BASH_SOURCE[0]}")/memory_write.py` (not `$0`) because `gate_lib.sh` is
**sourced** by callers — `$0` resolves to the sourcing shell's argv[0], not to `gate_lib.sh`.

### TDD steps

**Step 3.1 — Write the failing shell integration test**

Create `dark-factory/tests/test_memory_write_gate.sh`:

```bash
#!/usr/bin/env bash
# Integration test: write_memory_entry() in gate_lib.sh delegates to memory_write.py.
# Tests that the delegation produces entries with agent:/scope: tags (new behaviour).
set -euo pipefail

REPO_ROOT=$(git rev-parse --show-toplevel)
source "${REPO_ROOT}/dark-factory/scripts/gate_lib.sh"

PASS=0; FAIL=0

assert() {
  local desc="$1" result="$2"
  if [ "$result" = "0" ]; then
    echo "PASS: $desc"; PASS=$((PASS+1))
  else
    echo "FAIL: $desc"; FAIL=$((FAIL+1))
  fi
}

TMP=$(mktemp -d)
trap "rm -rf $TMP" EXIT

# ── Test 1: entry written with agent: tag ────────────────────────────────────
MD="$TMP/dark-factory-ops.md"
printf "# Dark Factory Ops\n\n---\n<!-- PROVISIONAL -->\n" > "$MD"

write_memory_entry "$MD" "dark-factory/scripts/" "avoid bad pattern" "conformance" "648"

assert "[AVOID] entry written" \
  "$(grep -q '\[AVOID\]' "$MD" && echo 0 || echo 1)"
assert "agent: tag present" \
  "$(grep -q 'agent:conformance' "$MD" && echo 0 || echo 1)"
assert "scope: tag present" \
  "$(grep -q 'scope:dark-factory' "$MD" && echo 0 || echo 1)"
assert "path: tag present" \
  "$(grep -q 'path:dark-factory/scripts/' "$MD" && echo 0 || echo 1)"
assert "entry is before --- delimiter" \
  "$(awk '/\[AVOID\]/{a=NR} /^---$/{b=NR} END{exit !(a<b)}' "$MD" && echo 0 || echo 1)"

# ── Test 2: normalized dedup skips second write ──────────────────────────────
write_memory_entry "$MD" "dark-factory/scripts/" "avoid bad pattern" "conformance" "648"
ENTRY_COUNT=$(grep -c '\[AVOID\]' "$MD" || true)
assert "dedup skips second identical write (count=1)" \
  "$([ "$ENTRY_COUNT" -eq 1 ] && echo 0 || echo 1)"

# ── Test 3: index.jsonl created next to the markdown ────────────────────────
assert "index.jsonl created" \
  "$([ -f "$TMP/index.jsonl" ] && echo 0 || echo 1)"

# ── Test 4: index.jsonl record is valid JSON with agent_id field ─────────────
assert "index.jsonl record is valid JSON" \
  "$(python3 -c "import json; json.loads(open('$TMP/index.jsonl').readline())" && echo 0 || echo 1)"
assert "index.jsonl agent_id is conformance" \
  "$(python3 -c \"import json; r=json.loads(open('$TMP/index.jsonl').readline()); exit(0 if r['agent_id']=='conformance' else 1)\" && echo 0 || echo 1)"

# ── Test 5: route_memory_file() still works (bash function unchanged) ─────────
assert "route_memory_file dark-factory/ → dark-factory-ops.md" \
  "$([ \"$(route_memory_file 'dark-factory/scripts/foo.sh')\" = '.archon/memory/dark-factory-ops.md' ] && echo 0 || echo 1)"

echo ""
echo "Results: $PASS passed, $FAIL failed"
[ "$FAIL" -eq 0 ]
```

**Step 3.2 — Run the shell test against the old gate_lib.sh to confirm it fails**

The old `write_memory_entry()` produces no `agent:` tag, so Test 1's "agent: tag present"
assertion will fail:

```bash
docker compose exec dark-factory bash -c "
  cd /workspace/markethawk &&
  bash dark-factory/tests/test_memory_write_gate.sh 2>&1
"
```

Expected (old bash implementation, no agent: tags):
```
PASS: [AVOID] entry written
FAIL: agent: tag present
FAIL: scope: tag present
...
Results: X passed, Y failed
```

**Step 3.3 — Replace `write_memory_entry()` body in `gate_lib.sh`**

In `dark-factory/scripts/gate_lib.sh`, replace the entire `write_memory_entry()` function
body (lines from `local TARGET=...` through `fi`) with the 5-line Python delegation:

Old body to remove:
```bash
write_memory_entry() {
  # Usage: write_memory_entry TARGET PATH_PREFIX VIOLATION_TEXT SOURCE ISSUE_NUM
  local TARGET="$1" PATH_PREFIX="$2" TEXT="$3" SOURCE="$4" ISSUE="$5"

  # Dedup: skip if core sentence already present
  if grep -qF "$TEXT" "$TARGET" 2>/dev/null; then
    echo "memory-write: duplicate entry skipped — already in $TARGET"
    return 0
  fi

  # Expiry cleanup (mawk-compatible two-argument match form)
  TODAY=$(date +%Y-%m-%d)
  awk -v today="$TODAY" '
    /expires:[0-9]{4}-[0-9]{2}-[0-9]{2}/ {
      found=match($0, /expires:[0-9]{4}-[0-9]{2}-[0-9]{2}/)
      if (found) { expiry_date=substr($0, RSTART+8, 10); if (expiry_date < today) next }
    }
    { print }
  ' "$TARGET" > "$TARGET.tmp" && mv "$TARGET.tmp" "$TARGET"

  # Cap check (30 authoritative entries per file)
  COUNT=$(grep -c '^\- \[PATTERN\]\|^\- \[AVOID\]\|^\- \[FIX\]' "$TARGET" 2>/dev/null || echo 0)
  if [ "$COUNT" -ge 30 ]; then
    echo "memory-write: cap reached ($COUNT entries) in $TARGET — skipping write"
    return 0
  fi

  EXPIRES=$(date -d '+6 months' +%Y-%m-%d 2>/dev/null || date -v+6m +%Y-%m-%d)
  ENTRY="- [AVOID] $TEXT <!-- issue:#$ISSUE date:$(date +%Y-%m-%d) expires:$EXPIRES source:$SOURCE path:$PATH_PREFIX -->"

  # Insert before the PROVISIONAL section delimiter (or append if no delimiter)
  if grep -q '^---$' "$TARGET" 2>/dev/null; then
    sed -i "/^---$/i $ENTRY" "$TARGET"
  else
    echo "$ENTRY" >> "$TARGET"
  fi
}
```

New body (5-line delegation):
```bash
write_memory_entry() {
  # Usage: write_memory_entry TARGET PATH_PREFIX VIOLATION_TEXT SOURCE ISSUE_NUM
  local TARGET="$1" PATH_PREFIX="$2" TEXT="$3" SOURCE="$4" ISSUE="$5"
  python3 "$(dirname "${BASH_SOURCE[0]}")/memory_write.py" \
    --target "$TARGET" --path-prefix "$PATH_PREFIX" --text "$TEXT" \
    --source "$SOURCE" --issue "$ISSUE"
}
```

`${BASH_SOURCE[0]}` (not `$0`) is required because `gate_lib.sh` is **sourced** — `$0`
resolves to the caller's shell, not `gate_lib.sh` itself.

**Step 3.4 — Run integration test to confirm it passes**

```bash
docker compose exec dark-factory bash -c "
  cd /workspace/markethawk &&
  bash dark-factory/tests/test_memory_write_gate.sh 2>&1
"
```

Expected:
```
PASS: [AVOID] entry written
PASS: agent: tag present
PASS: scope: tag present
PASS: path: tag present
PASS: entry is before --- delimiter
PASS: dedup skips second identical write (count=1)
PASS: index.jsonl created
PASS: index.jsonl record is valid JSON
PASS: index.jsonl agent_id is conformance
PASS: route_memory_file dark-factory/ → dark-factory-ops.md

Results: 10 passed, 0 failed
```

**Step 3.5 — Run the existing memory write shell test to confirm no regression**

```bash
docker compose exec dark-factory bash -c "
  cd /workspace/markethawk &&
  bash dark-factory/tests/test_conformance_memory_write.sh 2>&1
"
```

Expected:
```
Results: X passed, 0 failed
```

**Step 3.6 — Run full pytest suite to confirm no regression**

```bash
docker compose exec dark-factory bash -c "
  cd /workspace/markethawk &&
  python -m pytest dark-factory/tests/test_memory_write.py -v 2>&1
"
```

Expected:
```
============================== 27 passed in X.XXs ===============================
```

**Step 3.7 — Commit**

```bash
git add dark-factory/scripts/gate_lib.sh dark-factory/tests/test_memory_write_gate.sh
git commit -m "refactor: gate_lib.sh write_memory_entry() delegates to memory_write.py (#648)"
```
