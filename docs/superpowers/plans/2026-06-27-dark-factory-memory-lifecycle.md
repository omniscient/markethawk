# Implementation Plan — Dark Factory Memory Lifecycle Maintenance

**Goal:** Add `dark-factory/scripts/memory_maintain.py` — a standalone `argparse` CLI that
implements four lifecycle operations (expire, promote, dedup-invalidate, CLI invalidate) against the
`.archon/memory/*.md` files, with full dry-run support. Add a pytest suite in
`dark-factory/tests/test_memory_maintain.py` with in-memory string fixtures.

**Issue:** #650  
**Spec:** `docs/superpowers/specs/2026-06-27-dark-factory-memory-lifecycle-design.md`  
**Date:** 2026-06-27

---

## Architecture

Standalone Python script — no new Docker containers, no new dependencies beyond the stdlib.
Pure `op_*` functions accept/return dataclasses; `cmd_*` functions handle I/O and dry-run diff.
All operations are reversible before `--dry-run` is removed; dry-run is the default for `run`.

---

## Tech Stack

- **Language/runtime:** Python 3.11, stdlib only (`argparse`, `re`, `difflib`, `dataclasses`, `datetime`)
- **Tests:** `pytest`, in-memory strings (no filesystem writes), `sys.path.insert` import pattern

---

## File Structure

| File | Status | Purpose |
|------|--------|---------|
| `dark-factory/scripts/memory_maintain.py` | New | CLI — parse, ops, render, cmd_run, cmd_invalidate |
| `dark-factory/tests/test_memory_maintain.py` | New | pytest — promote, expire, dedup, invalidate |

---

## Task 1 — Data structures, `parse_entry`, `render_entry` (TDD)

**Files:** `dark-factory/scripts/memory_maintain.py`, `dark-factory/tests/test_memory_maintain.py`

### 1.1 — Write failing tests

Create `dark-factory/tests/test_memory_maintain.py` with the entry-level tests:

```python
"""
Tests for dark-factory/scripts/memory_maintain.py.

All tests operate on in-memory strings; no filesystem writes.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import memory_maintain as mm  # noqa: E402


# ---------------------------------------------------------------------------
# parse_entry
# ---------------------------------------------------------------------------

class TestParseEntry:
    def test_pattern_tag_and_body(self):
        line = "- [PATTERN] Use foo. <!-- issue:#123 date:2026-01-01 expires:2026-07-01 source:implement -->"
        e = mm.parse_entry(line)
        assert e.tag == "PATTERN"
        assert e.body == "Use foo."
        assert e.meta["issue"] == "#123"
        assert e.meta["expires"] == "2026-07-01"

    def test_provisional_tag(self):
        line = "- [PROVISIONAL] Some prov entry. <!-- evidence:x issue:#200 date:2026-01-01 expires:2026-07-01 source:implement -->"
        e = mm.parse_entry(line)
        assert e.tag == "PROVISIONAL"
        assert e.meta["issue"] == "#200"

    def test_invalid_tag_with_reason(self):
        line = "- [INVALID: superseded by identical entry added 2026-06-01] Old entry. <!-- issue:#50 date:2026-01-01 source:implement -->"
        e = mm.parse_entry(line)
        assert e.tag.startswith("INVALID")
        assert "superseded" in e.tag

    def test_no_meta_comment_returns_empty_dict(self):
        line = "- [PATTERN] Entry with no metadata."
        e = mm.parse_entry(line)
        assert e.meta == {}
        assert e.body == "Entry with no metadata."

    def test_non_entry_line_returns_none(self):
        assert mm.parse_entry("## Section Header") is None
        assert mm.parse_entry("") is None
        assert mm.parse_entry("---") is None

    def test_multi_issue_meta(self):
        line = "- [PROVISIONAL] Multi evidence. <!-- evidence:x issue:#10 evidence2:y issue:#20 date:2026-01-01 expires:2026-07-01 source:implement -->"
        e = mm.parse_entry(line)
        assert "#10" in e.issue_numbers
        assert "#20" in e.issue_numbers

    def test_path_tag_extracted(self):
        line = "- [AVOID] Don't do X. <!-- issue:#99 date:2026-01-01 path:backend/app/ expires:2026-07-01 source:implement -->"
        e = mm.parse_entry(line)
        assert e.meta.get("path") == "backend/app/"


# ---------------------------------------------------------------------------
# render_entry
# ---------------------------------------------------------------------------

class TestRenderEntry:
    def test_roundtrip_preserves_line_with_period(self):
        line = "- [PATTERN] Use foo. <!-- issue:#123 date:2026-01-01 expires:2026-07-01 source:implement -->"
        e = mm.parse_entry(line)
        assert mm.render_entry(e) == line

    def test_roundtrip_preserves_line_without_period(self):
        # Body verbatim — no spurious period appended
        line = "- [AVOID] Never use tmpfs for shared volumes <!-- issue:#99 date:2026-01-01 source:implement -->"
        e = mm.parse_entry(line)
        assert mm.render_entry(e) == line

    def test_tag_replacement_changes_rendered_tag(self):
        line = "- [PROVISIONAL] Promo me. <!-- evidence:x issue:#10 evidence2:y issue:#20 date:2026-01-01 expires:2026-07-01 source:implement -->"
        e = mm.parse_entry(line)
        e.tag = "PATTERN"
        rendered = mm.render_entry(e)
        assert rendered.startswith("- [PATTERN]")
```

### 1.2 — Verify tests fail

```bash
cd /workspace/markethawk/dark-factory
python -m pytest tests/test_memory_maintain.py::TestParseEntry -x 2>&1 | head -20
# Expected: ImportError (file doesn't exist yet)
```

### 1.3 — Implement data structures and parse_entry

Create `dark-factory/scripts/memory_maintain.py`:

```python
"""
memory_maintain.py — Dark Factory memory lifecycle maintenance CLI.

Usage:
    python memory_maintain.py run [--dry-run] [--scope <path-prefix>]
    python memory_maintain.py invalidate --file <file.md> --match "<substr>" --reason "<why>"

Subcommand 'run' performs expire + promote + dedup on all .archon/memory/*.md files.
All op_* functions are pure (no filesystem access); cmd_* handle I/O and dry-run diffs.
"""
import argparse
import difflib
import re
import sys
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Optional

MEMORY_DIR = Path(".archon/memory")
MEMORY_FILES = [
    "codebase-patterns.md",
    "architecture.md",
    "backend-patterns.md",
    "frontend-patterns.md",
    "dark-factory-ops.md",
]

ENTRY_RE = re.compile(
    r'^(?P<indent>\s*)-\s+\[(?P<tag>[^\]]+)\]\s+(?P<body>.*?)(?:\s*<!--(?P<meta>[^>]*)-->)?\s*$'
)
ISSUE_RE = re.compile(r'issue:(#\d+)')


@dataclass
class MemoryEntry:
    tag: str
    body: str
    meta: dict = field(default_factory=dict)
    raw_meta: str = ""
    indent: str = ""

    @property
    def issue_numbers(self) -> list:
        return ISSUE_RE.findall(self.raw_meta)

    @property
    def date_val(self) -> Optional[date]:
        d = self.meta.get("date", "")
        try:
            return date.fromisoformat(d)
        except ValueError:
            return None

    @property
    def expires_val(self) -> Optional[date]:
        ex = self.meta.get("expires", "")
        try:
            return date.fromisoformat(ex)
        except ValueError:
            return None

    @property
    def path_tag(self) -> str:
        return self.meta.get("path", "")


@dataclass
class MemoryFile:
    auth_raw_lines: list   # every raw line in the auth section (entry + non-entry), in original order
    auth_entries: list     # MemoryEntry objects parsed from auth_raw_lines, in original order
    prov_lines: list       # raw lines from "---" onward (provisional section raw)
    prov_entries: list     # MemoryEntry objects in provisional section


def parse_entry(line: str) -> Optional[MemoryEntry]:
    """Parse one markdown list line into a MemoryEntry. Returns None for non-entries."""
    m = ENTRY_RE.match(line)
    if not m:
        return None
    # Strip surrounding whitespace from raw_meta so render_entry can reproduce
    # the original "<!-- meta -->" spacing without introducing double-spaces.
    raw_meta = (m.group("meta") or "").strip()
    meta = {}
    for token in raw_meta.split():
        if ":" in token:
            k, _, v = token.partition(":")
            if k not in meta:
                meta[k] = v
    return MemoryEntry(
        tag=m.group("tag"),
        body=m.group("body").strip(),
        meta=meta,
        raw_meta=raw_meta,
        indent=m.group("indent"),
    )


def render_entry(entry: MemoryEntry) -> str:
    """Render a MemoryEntry back to its markdown line. Body is reproduced verbatim — no period normalisation."""
    meta_part = f" <!-- {entry.raw_meta} -->" if entry.raw_meta else ""
    return f"{entry.indent}- [{entry.tag}] {entry.body}{meta_part}"
```

### 1.4 — Verify tests pass

```bash
python -m pytest tests/test_memory_maintain.py::TestParseEntry tests/test_memory_maintain.py::TestRenderEntry -v 2>&1 | tail -20
# Expected: all green
```

### 1.5 — Commit

```bash
git add dark-factory/scripts/memory_maintain.py dark-factory/tests/test_memory_maintain.py
git commit -m "feat: memory_maintain.py — data structures, parse_entry, render_entry (#650)"
```

---

## Task 2 — `parse_file` and `render_file` (TDD)

**Files:** `dark-factory/scripts/memory_maintain.py`, `dark-factory/tests/test_memory_maintain.py`

### 2.1 — Write failing tests

Append to `dark-factory/tests/test_memory_maintain.py`:

```python
# ---------------------------------------------------------------------------
# parse_file / render_file
# ---------------------------------------------------------------------------

SAMPLE_FILE = """\
# Test Memory File

## Section A

- [PATTERN] Auth entry one. <!-- issue:#1 date:2026-01-01 expires:2027-01-01 source:implement -->
- [AVOID] Auth entry two. <!-- issue:#2 date:2026-02-01 expires:2027-02-01 source:implement -->

---
<!-- PROVISIONAL — entries below are from a single observed run; unverified.
     Do not rely on these as authoritative guidance. They are excluded from
     plan/implement prompt injection except as advisory context.
     Each will be promoted to [PATTERN] on second-run confirmation (different issue number) or dropped at TTL. -->

- [PROVISIONAL] Prov entry one. <!-- evidence:x issue:#10 date:2026-03-01 expires:2026-09-01 source:implement -->
"""


class TestParseFile:
    def test_auth_entry_count(self):
        mf = mm.parse_file_content(SAMPLE_FILE)
        assert len(mf.auth_entries) == 2

    def test_prov_entry_count(self):
        mf = mm.parse_file_content(SAMPLE_FILE)
        assert len(mf.prov_entries) == 1

    def test_auth_entry_tags(self):
        mf = mm.parse_file_content(SAMPLE_FILE)
        assert mf.auth_entries[0].tag == "PATTERN"
        assert mf.auth_entries[1].tag == "AVOID"

    def test_prov_entry_tag(self):
        mf = mm.parse_file_content(SAMPLE_FILE)
        assert mf.prov_entries[0].tag == "PROVISIONAL"


class TestRenderFile:
    def test_roundtrip(self):
        mf = mm.parse_file_content(SAMPLE_FILE)
        rendered = mm.render_file(mf)
        assert rendered == SAMPLE_FILE
        # Section header must precede the first entry
        section_pos = rendered.index("## Section A")
        entry_pos = rendered.index("- [PATTERN]")
        assert section_pos < entry_pos

    def test_modify_auth_entry_reflects_in_render(self):
        mf = mm.parse_file_content(SAMPLE_FILE)
        mf.auth_entries[0].tag = "FIX"
        rendered = mm.render_file(mf)
        assert "- [FIX]" in rendered
        assert "- [PATTERN]" not in rendered

    def test_extra_auth_entry_appended_when_no_raw_line(self):
        import copy
        mf = mm.parse_file_content(SAMPLE_FILE)
        promoted = copy.copy(mf.prov_entries[0])
        promoted.tag = "PATTERN"
        mf.auth_entries.append(promoted)
        rendered = mm.render_file(mf)
        assert rendered.count("- [PATTERN]") == 2  # original + promoted

    def test_removed_auth_entry_not_in_render(self):
        mf = mm.parse_file_content(SAMPLE_FILE)
        mf.auth_entries = mf.auth_entries[1:]  # remove first (expire simulation)
        rendered = mm.render_file(mf)
        assert "Auth entry one." not in rendered
        assert "Auth entry two." in rendered
```

### 2.2 — Implement `parse_file_content` and `render_file`

Add to `dark-factory/scripts/memory_maintain.py`:

```python
def parse_file_content(content: str) -> MemoryFile:
    """Parse full file content into a MemoryFile. Splits at the first '---' line."""
    lines = content.split("\n")
    split_idx = None
    for i, line in enumerate(lines):
        if line.strip() == "---":
            split_idx = i
            break

    # auth_raw_lines: every raw line from the auth section, including section headers and blanks.
    # render_file iterates this to reproduce the original structure.
    auth_raw_lines = lines[:split_idx] if split_idx is not None else lines
    prov_raw = lines[split_idx:] if split_idx is not None else []

    # auth_entries: MemoryEntry objects in original order (one per entry-line in auth_raw_lines)
    auth_entries = [e for line in auth_raw_lines for e in [parse_entry(line)] if e is not None]
    prov_entries = [e for line in prov_raw for e in [parse_entry(line)] if e is not None]

    return MemoryFile(
        auth_raw_lines=auth_raw_lines,
        auth_entries=auth_entries,
        prov_lines=prov_raw,
        prov_entries=prov_entries,
    )


def render_file(mf: MemoryFile) -> str:
    """
    Render a MemoryFile back to its full markdown string.

    Auth section: replay auth_raw_lines, replacing each entry-line with the
    next MemoryEntry from auth_entries. Removed entries (fewer auth_entries than
    raw entry-lines) cause the raw line to be skipped. Promoted entries that have
    no raw line counterpart are appended after the last raw auth line.
    Non-entry lines (section headers, blanks) are kept in place.

    Prov section: same positional strategy over prov_lines / prov_entries.
    """
    out_lines = []
    auth_list = list(mf.auth_entries)
    auth_idx = 0

    for line in mf.auth_raw_lines:
        if parse_entry(line) is not None:
            if auth_idx < len(auth_list):
                out_lines.append(render_entry(auth_list[auth_idx]))
                auth_idx += 1
            # else: entry removed (expired/deduped) — skip this raw line
        else:
            out_lines.append(line)

    # Append promoted entries that have no corresponding raw line
    while auth_idx < len(auth_list):
        out_lines.append(render_entry(auth_list[auth_idx]))
        auth_idx += 1

    prov_list = list(mf.prov_entries)
    prov_idx = 0
    for line in mf.prov_lines:
        if parse_entry(line) is not None:
            if prov_idx < len(prov_list):
                out_lines.append(render_entry(prov_list[prov_idx]))
                prov_idx += 1
            # else: entry removed — skip
        else:
            out_lines.append(line)

    return "\n".join(out_lines)
```

### 2.3 — Verify

```bash
python -m pytest tests/test_memory_maintain.py::TestParseFile tests/test_memory_maintain.py::TestRenderFile -v 2>&1 | tail -20
# Expected: all green
```

### 2.4 — Commit

```bash
git add dark-factory/scripts/memory_maintain.py dark-factory/tests/test_memory_maintain.py
git commit -m "feat: memory_maintain.py — parse_file_content and render_file (#650)"
```

---

## Task 3 — `op_expire` (TDD)

**Files:** `dark-factory/scripts/memory_maintain.py`, `dark-factory/tests/test_memory_maintain.py`

### 3.1 — Write failing tests

Append to `dark-factory/tests/test_memory_maintain.py`:

```python
# ---------------------------------------------------------------------------
# op_expire
# ---------------------------------------------------------------------------

from datetime import date as _date


def _entry(tag, body, expires=None, issue="#1", date_str="2026-01-01"):
    meta = {"issue": issue, "date": date_str, "source": "implement"}
    raw = f"issue:{issue} date:{date_str} source:implement"
    if expires:
        meta["expires"] = expires
        raw += f" expires:{expires}"
    return mm.MemoryEntry(tag=tag, body=body, meta=meta, raw_meta=raw)


class TestOpExpire:
    TODAY = _date(2026, 6, 27)

    def test_removes_expired_auth_entry(self):
        entries = [_entry("PATTERN", "Old entry", expires="2026-01-01")]
        result = mm.op_expire(entries, [], self.TODAY)
        assert len(result.kept_auth) == 0
        assert len(result.removed_auth) == 1

    def test_keeps_future_auth_entry(self):
        entries = [_entry("PATTERN", "Current entry", expires="2027-01-01")]
        result = mm.op_expire(entries, [], self.TODAY)
        assert len(result.kept_auth) == 1
        assert len(result.removed_auth) == 0

    def test_no_expires_key_is_kept(self):
        entries = [_entry("PATTERN", "No expiry")]
        result = mm.op_expire(entries, [], self.TODAY)
        assert len(result.kept_auth) == 1

    def test_removes_expired_provisional(self):
        prov = [_entry("PROVISIONAL", "Expired prov", expires="2026-01-01")]
        result = mm.op_expire([], prov, self.TODAY)
        assert len(result.kept_prov) == 0
        assert len(result.removed_prov) == 1

    def test_keeps_non_expired_provisional(self):
        prov = [_entry("PROVISIONAL", "Active prov", expires="2027-01-01")]
        result = mm.op_expire([], prov, self.TODAY)
        assert len(result.kept_prov) == 1

    def test_removes_provisional_with_only_one_issue_and_past_expires(self):
        prov = [_entry("PROVISIONAL", "Single issue expired", expires="2026-01-01", issue="#5")]
        result = mm.op_expire([], prov, self.TODAY)
        assert len(result.removed_prov) == 1
```

### 3.2 — Implement `op_expire`

Add to `dark-factory/scripts/memory_maintain.py`:

```python
from dataclasses import dataclass as _dc

@_dc
class ExpireResult:
    kept_auth: list
    removed_auth: list
    kept_prov: list
    removed_prov: list


def op_expire(auth_entries: list, prov_entries: list, today: date) -> ExpireResult:
    """
    Pure function. Remove entries whose expires: date is in the past.
    Provisional entries that have expired (regardless of issue count) are also removed.
    """
    kept_auth, removed_auth = [], []
    for e in auth_entries:
        ex = e.expires_val
        if ex is not None and ex < today:
            removed_auth.append(e)
        else:
            kept_auth.append(e)

    kept_prov, removed_prov = [], []
    for e in prov_entries:
        ex = e.expires_val
        if ex is not None and ex < today:
            removed_prov.append(e)
        else:
            kept_prov.append(e)

    return ExpireResult(
        kept_auth=kept_auth,
        removed_auth=removed_auth,
        kept_prov=kept_prov,
        removed_prov=removed_prov,
    )
```

### 3.3 — Verify

```bash
python -m pytest tests/test_memory_maintain.py::TestOpExpire -v 2>&1 | tail -15
```

### 3.4 — Commit

```bash
git add dark-factory/scripts/memory_maintain.py dark-factory/tests/test_memory_maintain.py
git commit -m "feat: memory_maintain.py — op_expire (#650)"
```

---

## Task 4 — `op_promote` (TDD)

**Files:** `dark-factory/scripts/memory_maintain.py`, `dark-factory/tests/test_memory_maintain.py`

### 4.1 — Write failing tests

Append to `dark-factory/tests/test_memory_maintain.py`:

```python
# ---------------------------------------------------------------------------
# op_promote
# ---------------------------------------------------------------------------

def _prov_entry(body, issues, extra_meta=""):
    raw = " ".join(f"issue:{i}" for i in issues)
    raw += f" date:2026-01-01 expires:2027-01-01 source:implement{extra_meta}"
    meta = {"date": "2026-01-01", "expires": "2027-01-01", "source": "implement"}
    for iss in issues:
        if "issue" not in meta:
            meta["issue"] = iss
    return mm.MemoryEntry(tag="PROVISIONAL", body=body, meta=meta, raw_meta=raw)


class TestOpPromote:
    def test_two_distinct_issues_promotes_to_pattern(self):
        prov = [_prov_entry("Promote me", ["#10", "#20"])]
        result = mm.op_promote(prov)
        assert len(result.promoted) == 1
        assert result.promoted[0].tag == "PATTERN"
        assert result.promoted[0] not in result.remaining_prov

    def test_one_issue_stays_provisional(self):
        prov = [_prov_entry("Stay provisional", ["#10"])]
        result = mm.op_promote(prov)
        assert len(result.promoted) == 0
        assert len(result.remaining_prov) == 1

    def test_two_identical_issues_not_promoted(self):
        # Same issue number repeated — counts as 1 distinct
        prov = [_prov_entry("Not promoted", ["#10", "#10"])]
        result = mm.op_promote(prov)
        assert len(result.promoted) == 0

    def test_promoted_entry_moves_from_prov_to_auth(self):
        prov = [
            _prov_entry("Promote", ["#10", "#20"]),
            _prov_entry("Stay", ["#30"]),
        ]
        result = mm.op_promote(prov)
        assert len(result.promoted) == 1
        assert len(result.remaining_prov) == 1
        assert result.remaining_prov[0].body == "Stay"

    def test_inline_metadata_tag_overrides_pattern(self):
        raw = "evidence:x issue:#10 evidence2:y issue:#20 date:2026-01-01 expires:2027-01-01 source:implement promote_as:AVOID"
        e = mm.MemoryEntry(tag="PROVISIONAL", body="Avoid entry", meta={"date": "2026-01-01", "promote_as": "AVOID"}, raw_meta=raw)
        result = mm.op_promote([e])
        assert result.promoted[0].tag == "AVOID"
```

### 4.2 — Implement `op_promote`

Add to `dark-factory/scripts/memory_maintain.py`:

```python
@_dc
class PromoteResult:
    promoted: list       # MemoryEntry objects (now tagged PATTERN/AVOID/FIX)
    remaining_prov: list # MemoryEntry objects that stay PROVISIONAL


def op_promote(prov_entries: list) -> PromoteResult:
    """
    Pure function. Promote PROVISIONAL entries with 2+ distinct issue:#N values.
    Promoted entries get tag PATTERN (or promote_as: value if present in meta).
    """
    promoted, remaining = [], []
    for e in prov_entries:
        distinct = set(e.issue_numbers)
        if len(distinct) >= 2:
            new_tag = e.meta.get("promote_as", "PATTERN")
            import copy
            promoted_e = copy.copy(e)
            promoted_e.tag = new_tag
            promoted.append(promoted_e)
        else:
            remaining.append(e)
    return PromoteResult(promoted=promoted, remaining_prov=remaining)
```

### 4.3 — Verify

```bash
python -m pytest tests/test_memory_maintain.py::TestOpPromote -v 2>&1 | tail -15
```

### 4.4 — Commit

```bash
git add dark-factory/scripts/memory_maintain.py dark-factory/tests/test_memory_maintain.py
git commit -m "feat: memory_maintain.py — op_promote (#650)"
```

---

## Task 5 — `op_dedup` (TDD)

**Files:** `dark-factory/scripts/memory_maintain.py`, `dark-factory/tests/test_memory_maintain.py`

### 5.1 — Write failing tests

Append to `dark-factory/tests/test_memory_maintain.py`:

```python
# ---------------------------------------------------------------------------
# op_dedup
# ---------------------------------------------------------------------------

import re as _re


class TestOpDedup:
    def test_identical_bodies_marks_older_invalid(self):
        older = _entry("PATTERN", "Use the transaction rollback fixture", date_str="2026-01-01")
        newer = _entry("PATTERN", "Use the transaction rollback fixture", date_str="2026-06-01")
        result = mm.op_dedup([older, newer])
        # older gets INVALID tag; newer stays
        tags = {e.body: e.tag for e in result.entries}
        assert tags["Use the transaction rollback fixture"].startswith("INVALID")
        # The newer entry must survive unchanged
        surviving = [e for e in result.entries if not e.tag.startswith("INVALID")]
        assert len(surviving) == 1
        assert surviving[0].meta.get("date") == "2026-06-01"

    def test_below_threshold_not_deduped(self):
        e1 = _entry("PATTERN", "Use foo for bar operations to get results.")
        e2 = _entry("PATTERN", "Use completely different approach with no similarities at all.")
        result = mm.op_dedup([e1, e2])
        assert all(not e.tag.startswith("INVALID") for e in result.entries)

    def test_already_invalid_entries_skipped(self):
        inv = _entry("INVALID: already bad", "Some body text for dedup test.")
        normal = _entry("PATTERN", "Some body text for dedup test.")
        result = mm.op_dedup([inv, normal])
        # Should not double-invalidate
        invalid_count = sum(1 for e in result.entries if e.tag.startswith("INVALID"))
        assert invalid_count == 1

    def test_dedup_count_reported(self):
        older = _entry("PATTERN", "Duplicate pattern entry here for dedup check.", date_str="2026-01-01")
        newer = _entry("PATTERN", "Duplicate pattern entry here for dedup check.", date_str="2026-06-01")
        result = mm.op_dedup([older, newer])
        assert result.deduped_count == 1
```

### 5.2 — Implement `op_dedup`

Add to `dark-factory/scripts/memory_maintain.py`:

```python
from difflib import SequenceMatcher

META_RE = re.compile(r'<!--.*?-->', re.DOTALL)
DEDUP_THRESHOLD = 0.90


def _strip_meta(body: str) -> str:
    """Strip inline <!-- --> comments and normalise whitespace for comparison."""
    stripped = META_RE.sub("", body)
    return re.sub(r'\s+', ' ', stripped).strip()


@_dc
class DedupResult:
    entries: list
    deduped_count: int


def op_dedup(entries: list) -> DedupResult:
    """
    Pure function. Compare each pair of non-INVALID entries by body similarity.
    If ratio >= 0.90, tag the older entry (by date:) as INVALID: superseded.
    Returns all entries with INVALID tags applied.
    """
    import copy
    working = [copy.copy(e) for e in entries]
    deduped = 0

    for i in range(len(working)):
        if working[i].tag.startswith("INVALID"):
            continue
        for j in range(i + 1, len(working)):
            if working[j].tag.startswith("INVALID"):
                continue
            a_body = _strip_meta(working[i].body)
            b_body = _strip_meta(working[j].body)
            ratio = SequenceMatcher(None, a_body, b_body).ratio()
            if ratio >= DEDUP_THRESHOLD:
                # Older by date gets tagged INVALID
                a_date = working[i].date_val or date.min
                b_date = working[j].date_val or date.min
                if a_date <= b_date:
                    newer_date = working[j].meta.get("date", "unknown")
                    working[i].tag = f"INVALID: superseded by identical entry added {newer_date}"
                    deduped += 1
                    break  # working[i] is now INVALID; inner loop guard catches it next outer iter
                else:
                    newer_date = working[i].meta.get("date", "unknown")
                    working[j].tag = f"INVALID: superseded by identical entry added {newer_date}"
                    deduped += 1

    return DedupResult(entries=working, deduped_count=deduped)
```

### 5.3 — Verify

```bash
python -m pytest tests/test_memory_maintain.py::TestOpDedup -v 2>&1 | tail -15
```

### 5.4 — Commit

```bash
git add dark-factory/scripts/memory_maintain.py dark-factory/tests/test_memory_maintain.py
git commit -m "feat: memory_maintain.py — op_dedup (#650)"
```

---

## Task 6 — `cmd_invalidate` (TDD)

**Files:** `dark-factory/scripts/memory_maintain.py`, `dark-factory/tests/test_memory_maintain.py`

### 6.1 — Write failing tests

Append to `dark-factory/tests/test_memory_maintain.py`:

```python
# ---------------------------------------------------------------------------
# cmd_invalidate (in-memory variant)
# ---------------------------------------------------------------------------

class TestCmdInvalidateLogic:
    def test_matching_entry_retagged(self):
        content = (
            "# Header\n"
            "\n"
            "- [PATTERN] Use the foo approach for bar. <!-- issue:#1 date:2026-01-01 source:implement -->\n"
            "- [PATTERN] Use baz for everything. <!-- issue:#2 date:2026-01-01 source:implement -->\n"
            "\n"
            "---\n"
            "<!-- PROVISIONAL -->\n"
        )
        result = mm.invalidate_content(content, match="foo approach", reason="deprecated by bar-v2")
        assert "[INVALID: deprecated by bar-v2]" in result
        assert "[PATTERN] Use the foo approach" not in result

    def test_non_matching_entries_unchanged(self):
        content = (
            "# Header\n"
            "- [PATTERN] Use baz for everything. <!-- issue:#2 date:2026-01-01 source:implement -->\n"
            "---\n"
            "<!-- PROVISIONAL -->\n"
        )
        result = mm.invalidate_content(content, match="not present", reason="whatever")
        assert result == content

    def test_meta_comment_preserved_after_retag(self):
        content = (
            "# H\n"
            "- [PATTERN] Keep the metadata comment intact. <!-- issue:#7 date:2026-05-01 source:implement -->\n"
            "---\n"
            "<!-- PROVISIONAL -->\n"
        )
        result = mm.invalidate_content(content, match="metadata comment", reason="test")
        assert "<!-- issue:#7 date:2026-05-01 source:implement -->" in result
```

### 6.2 — Implement `invalidate_content` and `cmd_invalidate`

Add to `dark-factory/scripts/memory_maintain.py`:

```python
def invalidate_content(content: str, match: str, reason: str) -> str:
    """
    Pure function. Find the first entry whose body contains `match` and retag it
    INVALID: <reason>, preserving the inline metadata comment.
    Returns the full file content string with the replacement applied.
    """
    lines = content.split("\n")
    for i, line in enumerate(lines):
        e = parse_entry(line)
        if e is not None and match in e.body and not e.tag.startswith("INVALID"):
            e.tag = f"INVALID: {reason}"
            lines[i] = render_entry(e)
            break
    return "\n".join(lines)


def cmd_invalidate(args) -> int:
    """Invalidate a specific entry by body substring. Returns exit code."""
    file_path = MEMORY_DIR / args.file
    if not file_path.exists():
        print(f"error: file not found: {file_path}", file=sys.stderr)
        return 1
    content = file_path.read_text()
    new_content = invalidate_content(content, args.match, args.reason)
    if new_content == content:
        print(f"No entry matching '{args.match}' found in {args.file}")
        return 0
    file_path.write_text(new_content)
    print(f"Retagged matching entry in {args.file} as INVALID: {args.reason}")
    return 0
```

### 6.3 — Verify

```bash
python -m pytest tests/test_memory_maintain.py::TestCmdInvalidateLogic -v 2>&1 | tail -15
```

### 6.4 — Commit

```bash
git add dark-factory/scripts/memory_maintain.py dark-factory/tests/test_memory_maintain.py
git commit -m "feat: memory_maintain.py — invalidate_content, cmd_invalidate (#650)"
```

---

## Task 7 — `cmd_run` with dry-run, scope filter, summary, and `__main__` (TDD)

**Files:** `dark-factory/scripts/memory_maintain.py`, `dark-factory/tests/test_memory_maintain.py`

### 7.1 — Write failing tests

Append to `dark-factory/tests/test_memory_maintain.py`:

```python
# ---------------------------------------------------------------------------
# cmd_run logic (scope filter + apply_ops_to_content)
# ---------------------------------------------------------------------------

FULL_FILE = """\
# Test File

- [PATTERN] Keep this one. <!-- issue:#1 date:2026-01-01 expires:2027-01-01 source:implement -->
- [PATTERN] This one expired. <!-- issue:#2 date:2026-01-01 expires:2025-01-01 source:implement -->

---
<!-- PROVISIONAL — entries below are from a single observed run; unverified.
     Do not rely on these as authoritative guidance. They are excluded from
     plan/implement prompt injection except as advisory context.
     Each will be promoted to [PATTERN] on second-run confirmation (different issue number) or dropped at TTL. -->

- [PROVISIONAL] Ready to promote. <!-- evidence:x issue:#10 evidence2:y issue:#20 date:2026-01-01 expires:2027-01-01 source:implement -->
- [PROVISIONAL] Single issue only. <!-- issue:#30 date:2026-01-01 expires:2027-01-01 source:implement -->
"""


class TestApplyOpsToContent:
    TODAY = _date(2026, 6, 27)

    def test_expired_entry_removed(self):
        new_content, summary = mm.apply_ops_to_content(FULL_FILE, self.TODAY, scope=None)
        assert "This one expired." not in new_content
        assert summary["expired_auth"] == 1

    def test_keep_non_expired(self):
        new_content, summary = mm.apply_ops_to_content(FULL_FILE, self.TODAY, scope=None)
        assert "Keep this one." in new_content

    def test_promoted_entry_moves_to_auth(self):
        new_content, summary = mm.apply_ops_to_content(FULL_FILE, self.TODAY, scope=None)
        assert summary["promoted"] == 1
        assert "[PATTERN] Ready to promote." in new_content

    def test_single_issue_stays_provisional(self):
        new_content, summary = mm.apply_ops_to_content(FULL_FILE, self.TODAY, scope=None)
        assert "Single issue only." in new_content

    def test_scope_filter_skips_unmatched_entries(self):
        scoped_file = (
            "# H\n"
            "- [PATTERN] Backend only. <!-- issue:#1 date:2026-01-01 expires:2025-01-01 source:implement path:backend/ -->\n"
            "- [PATTERN] Frontend only. <!-- issue:#2 date:2026-01-01 expires:2025-01-01 source:implement path:frontend/ -->\n"
            "---\n<!-- PROVISIONAL -->\n"
        )
        new_content, summary = mm.apply_ops_to_content(scoped_file, self.TODAY, scope="backend/")
        # backend entry expired and scoped: removed. frontend: unscoped match skipped — kept.
        assert "Backend only." not in new_content
        assert "Frontend only." in new_content


class TestDryRunDiff:
    def test_dry_run_returns_unified_diff_string(self):
        original = FULL_FILE
        today = _date(2026, 6, 27)
        diff = mm.compute_dry_run_diff(original, "test.md", today, scope=None)
        assert "---" in diff or diff == ""  # empty diff if no changes
```

### 7.2 — Implement `apply_ops_to_content`, `compute_dry_run_diff`, `cmd_run`, and `__main__`

Add to `dark-factory/scripts/memory_maintain.py`:

```python
import copy as _copy


def apply_ops_to_content(content: str, today: date, scope: Optional[str]) -> tuple:
    """
    Apply expire + promote + dedup to file content string.
    scope: if set, only process entries whose path: tag starts with scope.
    Returns (new_content, summary_dict).
    """
    mf = parse_file_content(content)
    summary = {"expired_auth": 0, "expired_prov": 0, "promoted": 0, "deduped": 0}

    def _in_scope(e: MemoryEntry) -> bool:
        if scope is None:
            return True
        pt = e.path_tag
        return pt == "" or pt.startswith(scope)

    # Expire auth entries in-place, preserving original relative order.
    # Out-of-scope entries are kept unconditionally (scope only gates expiry).
    # Preserving order is critical: render_file uses positional replay against
    # _auth_raw_lines, so any reordering (e.g. in-scope first, out-of-scope second)
    # would map entries to the wrong section headers in the rendered output.
    new_auth_entries = []
    for e in mf.auth_entries:
        if _in_scope(e):
            ex = e.expires_val
            if ex is not None and ex < today:
                summary["expired_auth"] += 1
                continue  # drop — render_file will skip the corresponding raw line
        new_auth_entries.append(e)

    # Expire all provisionals (both in-scope and out-of-scope) before promotion
    # to prevent promoting an expired-but-out-of-scope provisional.
    new_prov_entries = []
    for e in mf.prov_entries:
        ex = e.expires_val
        if ex is not None and ex < today:
            summary["expired_prov"] += 1
            continue
        new_prov_entries.append(e)

    # Promote surviving provisionals
    promote_result = op_promote(new_prov_entries)
    summary["promoted"] = len(promote_result.promoted)

    # Dedup on surviving auth + promoted (appended — no raw line, handled by render_file's tail loop)
    combined_auth = new_auth_entries + promote_result.promoted
    dedup_result = op_dedup(combined_auth)
    summary["deduped"] = dedup_result.deduped_count

    mf.auth_entries = dedup_result.entries
    mf.prov_entries = promote_result.remaining_prov

    return render_file(mf), summary


def compute_dry_run_diff(content: str, filename: str, today: date, scope: Optional[str]) -> str:
    """Return a unified diff string showing what cmd_run would change."""
    new_content, _ = apply_ops_to_content(content, today, scope)
    diff_lines = list(difflib.unified_diff(
        content.splitlines(keepends=True),
        new_content.splitlines(keepends=True),
        fromfile=f".archon/memory/{filename}",
        tofile=f".archon/memory/{filename} (dry-run)",
    ))
    return "".join(diff_lines)


def cmd_run(args) -> int:
    """Run expire + promote + dedup on memory files. Default is --dry-run."""
    today = date.today()
    scope = getattr(args, "scope", None)
    dry_run = getattr(args, "dry_run", True)
    any_changes = False

    for fname in MEMORY_FILES:
        fpath = MEMORY_DIR / fname
        if not fpath.exists():
            continue
        content = fpath.read_text()
        if dry_run:
            diff = compute_dry_run_diff(content, fname, today, scope)
            if diff:
                print(diff)
                any_changes = True
        else:
            new_content, summary = apply_ops_to_content(content, today, scope)
            if new_content != content:
                fpath.write_text(new_content)
                any_changes = True
                print(
                    f"{fname}: expired={summary['expired_auth']+summary['expired_prov']} "
                    f"promoted={summary['promoted']} deduped={summary['deduped']}"
                )

    if not any_changes:
        print("No changes.")
    return 0


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Dark Factory memory lifecycle maintenance CLI"
    )
    sub = parser.add_subparsers(dest="command")

    run_p = sub.add_parser("run", help="Expire, promote, dedup all memory files")
    run_p.add_argument("--dry-run", action="store_true", default=True,
                       help="Print diff only; do not write (default: True)")
    run_p.add_argument("--no-dry-run", dest="dry_run", action="store_false",
                       help="Actually write changes")
    run_p.add_argument("--scope", default=None,
                       help="Restrict to entries whose path: tag starts with this prefix")

    inv_p = sub.add_parser("invalidate", help="Retag a specific entry as INVALID")
    inv_p.add_argument("--file", required=True, help="Memory file name (e.g. dark-factory-ops.md)")
    inv_p.add_argument("--match", required=True, help="Substring to find in entry body")
    inv_p.add_argument("--reason", required=True, help="Reason for invalidation")

    return parser


if __name__ == "__main__":
    parser = _build_parser()
    args = parser.parse_args()
    if args.command == "run":
        sys.exit(cmd_run(args))
    elif args.command == "invalidate":
        sys.exit(cmd_invalidate(args))
    else:
        parser.print_help()
        sys.exit(1)
```

### 7.3 — Verify all tests pass

```bash
python -m pytest tests/test_memory_maintain.py -v 2>&1 | tail -40
# Expected: all tests green
```

Also smoke-test the CLI:

```bash
cd /workspace/markethawk
python dark-factory/scripts/memory_maintain.py run --dry-run 2>&1 | head -30
# Expected: unified diff output or "No changes."
```

### 7.4 — Commit

```bash
git add dark-factory/scripts/memory_maintain.py dark-factory/tests/test_memory_maintain.py
git commit -m "feat: memory_maintain.py — cmd_run, dry-run, scope filter, argparse CLI (#650)"
```

---

## Summary

| Task | Files | Steps |
|------|-------|-------|
| 1 — Data structures, parse_entry, render_entry | 2 | 5 |
| 2 — parse_file_content, render_file | 2 | 4 |
| 3 — op_expire | 2 | 4 |
| 4 — op_promote | 2 | 4 |
| 5 — op_dedup | 2 | 4 |
| 6 — cmd_invalidate | 2 | 4 |
| 7 — cmd_run + CLI + __main__ | 2 | 4 |

**Total:** 7 tasks, 29 steps across 2 files.
