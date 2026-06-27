# Plan: Import Existing Archon Memory into Structured Backend (#649)

**Date:** 2026-06-27
**Issue:** [#649 — Import existing .archon memory into the structured memory backend](https://github.com/omniscient/markethawk/issues/649)
**Epic:** #643 (Improve Dark Factory memory system using agent-native memory architecture)
**Phase:** Epic Phase 1 — non-invasive index (read only, no prompt changes)

---

## Goal

Create `dark-factory/scripts/memory_import.py` — a stdlib-only Python script that reads the five existing `.archon/memory/*.md` files, parses every `- [KIND] text <!-- metadata -->` entry, writes each as `.archon/memory/records/<id>.json`, and maintains `.archon/memory/index.jsonl`. The import is idempotent: re-running skips existing records. The script never touches the source `.md` files.

## Architecture

Two new files:

| File | Action | Description |
|------|--------|-------------|
| `dark-factory/scripts/memory_import.py` | **CREATE** | Standalone stdlib-only import script |
| `dark-factory/tests/test_memory_import.py` | **CREATE** | 13 unit tests + 1 integration test |

The script runs outside the factory container — any Python 3 with read/write access to the repo root is sufficient. No pip packages needed beyond stdlib (`hashlib`, `json`, `re`, `pathlib`, `argparse`, `dataclasses`).

## Tech Stack

- **Python 3 stdlib only** — no dependencies
- **pytest** — CI runs via `python -m pytest dark-factory/tests/ -v`
- **sys.path.insert** — test file imports the script module directly (established pattern in this test suite)

---

## File Structure

```
dark-factory/
  scripts/
    memory_import.py             ← new
  tests/
    test_memory_import.py        ← new
.archon/
  memory/
    architecture.md              ← read-only (never modified)
    backend-patterns.md          ← read-only (never modified)
    codebase-patterns.md         ← read-only (never modified)
    dark-factory-ops.md          ← read-only (never modified)
    frontend-patterns.md         ← read-only (never modified)
    records/                     ← created by script
      <id>.json                  ← one per entry
    index.jsonl                  ← created/appended by script
```

---

## Task 1 — Write failing unit tests

**Files:** `dark-factory/tests/test_memory_import.py`

### TDD steps

**Step 1.1 — Create the test file**

Create `dark-factory/tests/test_memory_import.py`:

```python
"""Tests for dark-factory/scripts/memory_import.py."""
import json
import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import memory_import as mi  # noqa: E402


# ---------------------------------------------------------------------------
# ID stability
# ---------------------------------------------------------------------------

def test_id_stability():
    """Same entry text yields the same id on repeated calls."""
    r1 = mi.parse_entry(
        "- [PATTERN] Foo bar baz <!-- issue:#100 date:2026-01-01 source:implement -->",
        "backend-patterns.md",
    )
    r2 = mi.parse_entry(
        "- [PATTERN] Foo bar baz <!-- issue:#100 date:2026-01-01 source:implement -->",
        "backend-patterns.md",
    )
    assert r1.id == r2.id


def test_id_kind_transition_stability():
    """Changing [KIND] tag on fixed text yields the same id (kind excluded from hash input)."""
    r_pattern = mi.parse_entry(
        "- [PATTERN] Foo bar baz <!-- issue:#100 date:2026-01-01 source:implement -->",
        "backend-patterns.md",
    )
    r_avoid = mi.parse_entry(
        "- [AVOID] Foo bar baz <!-- issue:#100 date:2026-01-01 source:implement -->",
        "backend-patterns.md",
    )
    assert r_pattern.id == r_avoid.id


# ---------------------------------------------------------------------------
# [INVALID: reason] parsing
# ---------------------------------------------------------------------------

def test_invalid_with_embedded_reason():
    """[INVALID: reason] bracket: kind=INVALID, confidence=0.0, reason NOT in summary."""
    record = mi.parse_entry(
        "- [INVALID: deprecated since #379] The proxy blocks exec operations"
        " <!-- evidence:curl-response issue:#287 date:2026-06-11 source:implement -->",
        "dark-factory-ops.md",
    )
    assert record is not None
    assert record.kind == "INVALID"
    assert record.confidence == 0.0
    # The bracket (including embedded reason) must not appear in the summary
    assert "[INVALID" not in record.summary
    assert "proxy blocks exec" in record.summary


# ---------------------------------------------------------------------------
# PROVISIONAL section inheritance
# ---------------------------------------------------------------------------

def test_provisional_section_inherits_kind():
    """Entries below --- without explicit [PROVISIONAL] tag inherit kind=PROVISIONAL."""
    with tempfile.TemporaryDirectory() as tmpdir:
        md = Path(tmpdir) / "codebase-patterns.md"
        md.write_text(
            "- [PATTERN] Normal entry <!-- issue:#1 date:2026-01-01 source:implement -->\n"
            "---\n"
            "- [PATTERN] Below separator <!-- issue:#2 date:2026-01-01 source:implement -->\n",
            encoding="utf-8",
        )
        records = list(mi.iter_entries(Path(tmpdir), "codebase-patterns.md"))

    assert len(records) == 2
    assert records[0].kind == "PATTERN"
    assert records[0].confidence == 1.0
    assert records[1].kind == "PROVISIONAL"
    assert records[1].confidence == 0.4


def test_provisional_section_invalid_keeps_kind():
    """[INVALID] entries below --- keep kind=INVALID (not overridden to PROVISIONAL)."""
    with tempfile.TemporaryDirectory() as tmpdir:
        md = Path(tmpdir) / "codebase-patterns.md"
        md.write_text(
            "---\n"
            "- [INVALID: old] Was true once <!-- issue:#1 date:2026-01-01 source:implement -->\n",
            encoding="utf-8",
        )
        records = list(mi.iter_entries(Path(tmpdir), "codebase-patterns.md"))

    assert len(records) == 1
    assert records[0].kind == "INVALID"
    assert records[0].confidence == 0.0


# ---------------------------------------------------------------------------
# Scope derivation
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("filename,expected_scope", [
    ("architecture.md", "architecture"),
    ("backend-patterns.md", "backend"),
    ("frontend-patterns.md", "frontend"),
    ("dark-factory-ops.md", "dark-factory"),
    ("codebase-patterns.md", "codebase"),
])
def test_scope_derivation(filename, expected_scope):
    record = mi.parse_entry(
        "- [PATTERN] Foo bar <!-- issue:#1 date:2026-01-01 source:implement -->",
        filename,
    )
    assert record.scope == expected_scope


# ---------------------------------------------------------------------------
# Confidence tiering
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("kind_bracket,source,expected", [
    ("INVALID: x", "implement", 0.0),
    ("PROVISIONAL", "implement", 0.4),
    ("PATTERN", "implement", 1.0),
    ("PATTERN", "conformance", 1.0),
    ("PATTERN", "refine", 0.7),
    ("PATTERN", "code-review", 0.7),
    ("PATTERN", "bootstrap", 0.7),
    ("PATTERN", "unknown-source", 0.7),
])
def test_confidence_tiering(kind_bracket, source, expected):
    record = mi.parse_entry(
        f"- [{kind_bracket}] Foo bar <!-- issue:#1 date:2026-01-01 source:{source} -->",
        "backend-patterns.md",
    )
    assert record is not None
    assert record.confidence == expected


# ---------------------------------------------------------------------------
# Evidence array
# ---------------------------------------------------------------------------

def test_evidence_single():
    """Single issue tag → one-element evidence array."""
    record = mi.parse_entry(
        "- [PATTERN] Foo bar <!-- issue:#123 date:2026-01-01 source:implement -->",
        "backend-patterns.md",
    )
    assert len(record.evidence) == 1
    assert record.evidence[0]["issue"] == 123
    assert record.evidence[0]["source"] == "implement"
    assert record.evidence[0]["date"] == "2026-01-01"
    assert record.evidence[0]["evidence_tag"] is None


def test_evidence_multi_evidence2():
    """evidence2: tag produces two-element array with per-issue evidence_tags."""
    record = mi.parse_entry(
        "- [INVALID: old] Foo bar"
        " <!-- evidence:curl-response issue:#287 date:2026-06-11"
        " evidence2:docker-exec issue:#259 date:2026-06-13"
        " expires:2026-12-13 source:implement -->",
        "dark-factory-ops.md",
    )
    assert len(record.evidence) == 2
    assert record.evidence[0]["issue"] == 287
    assert record.evidence[0]["evidence_tag"] == "curl-response"
    assert record.evidence[1]["issue"] == 259
    assert record.evidence[1]["evidence_tag"] == "docker-exec"


# ---------------------------------------------------------------------------
# path_prefixes
# ---------------------------------------------------------------------------

def test_path_prefixes_present():
    record = mi.parse_entry(
        "- [AVOID] Foo bar <!-- issue:#100 date:2026-01-01 source:conformance path:frontend/ -->",
        "codebase-patterns.md",
    )
    assert record.path_prefixes == ["frontend/"]


def test_path_prefixes_absent():
    record = mi.parse_entry(
        "- [PATTERN] Foo bar <!-- issue:#100 date:2026-01-01 source:implement -->",
        "backend-patterns.md",
    )
    assert record.path_prefixes == []


# ---------------------------------------------------------------------------
# expires_at
# ---------------------------------------------------------------------------

def test_expires_at_present():
    record = mi.parse_entry(
        "- [PATTERN] Foo bar <!-- issue:#100 date:2026-01-01 expires:2026-12-01 source:implement -->",
        "backend-patterns.md",
    )
    assert record.expires_at == "2026-12-01"


def test_expires_at_absent():
    record = mi.parse_entry(
        "- [PATTERN] Foo bar <!-- bootstrap date:2026-06-02 source:refine -->",
        "architecture.md",
    )
    assert record.expires_at is None


# ---------------------------------------------------------------------------
# Idempotency
# ---------------------------------------------------------------------------

def test_write_record_idempotency():
    """First write returns 'created'; second write on same record returns 'skipped'."""
    with tempfile.TemporaryDirectory() as tmpdir:
        records_dir = Path(tmpdir)
        record = mi.parse_entry(
            "- [PATTERN] Unique lesson text here <!-- issue:#100 date:2026-01-01 source:implement -->",
            "backend-patterns.md",
        )
        assert mi.write_record(record, records_dir, dry_run=False) == "created"
        assert mi.write_record(record, records_dir, dry_run=False) == "skipped"
        # File is valid JSON with required fields
        saved = json.loads((records_dir / f"{record.id}.json").read_text())
        assert saved["id"] == record.id
        assert saved["project"] == "markethawk"
        assert saved["retrieval_count"] == 0
        assert saved["last_used_at"] is None


def test_dry_run_writes_nothing():
    """Dry run returns 'created' without writing any files."""
    with tempfile.TemporaryDirectory() as tmpdir:
        records_dir = Path(tmpdir)
        record = mi.parse_entry(
            "- [PATTERN] Dry run test <!-- issue:#100 date:2026-01-01 source:implement -->",
            "backend-patterns.md",
        )
        result = mi.write_record(record, records_dir, dry_run=True)
        assert result == "created"
        assert not any(records_dir.iterdir())


# ---------------------------------------------------------------------------
# Integration test (runs against real .archon/memory/)
# ---------------------------------------------------------------------------

def test_integration_dry_run_real_memory():
    """Dry-run import against the live .archon/memory/ — no files written, invariants hold."""
    repo_root = Path(__file__).resolve().parents[2]
    memory_dir = repo_root / ".archon" / "memory"
    if not memory_dir.exists():
        pytest.skip(".archon/memory not found — skipping integration test")

    # Capture .md mtimes before import
    md_mtimes = {p.name: p.stat().st_mtime for p in memory_dir.glob("*.md")}

    result = mi.run_import(memory_dir, dry_run=True)
    records = result["records"]

    # Total entry count must be at least 100 across all five files
    assert result["totals"]["total"] >= 100, (
        f"Expected >=100 entries, got {result['totals']['total']}"
    )

    # No duplicate IDs
    ids = [r.id for r in records]
    assert len(ids) == len(set(ids)), "Duplicate record IDs found"

    # All records have required schema keys
    required_keys = {
        "id", "project", "kind", "scope", "path_prefixes", "summary",
        "rationale", "evidence", "confidence", "expires_at", "retrieval_count",
        "last_used_at", "supersedes", "superseded_by", "source_file",
    }
    for r in records:
        missing = required_keys - r.as_dict().keys()
        assert not missing, f"Record {r.id} missing keys: {missing}"

    # No .md files were modified
    for name, mtime_before in md_mtimes.items():
        assert (memory_dir / name).stat().st_mtime == mtime_before, (
            f"{name} was modified during dry-run — should never happen"
        )

    # No records directory created (dry run)
    records_dir = memory_dir / "records"
    assert not records_dir.exists() or not any(records_dir.iterdir()), (
        "Record files were written during dry-run!"
    )
```

**Step 1.2 — Verify tests fail (module not found)**

```bash
cd /workspace/markethawk
python -m pytest dark-factory/tests/test_memory_import.py -x 2>&1 | head -20
```

Expected output:
```
E   ModuleNotFoundError: No module named 'memory_import'
FAILED dark-factory/tests/test_memory_import.py - ModuleNotFoundError: ...
```

**Step 1.3 — Commit the test file**

```bash
git add dark-factory/tests/test_memory_import.py
git commit -m "test: add failing tests for memory_import (#649)"
```

Expected output: `[refine/issue-649-... <sha>] test: add failing tests for memory_import (#649)`

---

## Task 2 — Implement `memory_import.py`

**Files:** `dark-factory/scripts/memory_import.py`

### TDD steps

**Step 2.1 — Create the implementation**

Create `dark-factory/scripts/memory_import.py`:

```python
#!/usr/bin/env python3
"""
Seed the structured memory backend from existing .archon/memory/*.md files.

Produces:
  .archon/memory/records/<id>.json  — one JSON file per entry
  .archon/memory/index.jsonl        — append-only compact summary index

Usage:
  python dark-factory/scripts/memory_import.py              # write mode
  python dark-factory/scripts/memory_import.py --dry-run    # preview only
  python dark-factory/scripts/memory_import.py --memory-dir .archon/memory
"""
import argparse
import hashlib
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional


SCOPE_MAP = {
    "architecture.md": "architecture",
    "backend-patterns.md": "backend",
    "frontend-patterns.md": "frontend",
    "dark-factory-ops.md": "dark-factory",
    "codebase-patterns.md": "codebase",
}

SOURCE_CONFIDENCE = {
    "implement": 1.0,
    "conformance": 1.0,
    "refine": 0.7,
    "code-review": 0.7,
    "bootstrap": 0.7,
}

MEMORY_FILES = list(SCOPE_MAP.keys())

# Matches: - [KIND...] text <!-- metadata -->
ENTRY_RE = re.compile(r"^- \[([^\]]+)\] (.+?) <!-- (.+?) -->$")

# Matches key:value pairs in metadata; supports keys like evidence2, evidence3
TAG_RE = re.compile(r"(\w+\d*):([^\s>]+)")


@dataclass
class MemoryRecord:
    id: str
    project: str
    kind: str
    scope: str
    path_prefixes: List[str]
    summary: str
    rationale: None
    evidence: List[dict]
    confidence: float
    expires_at: Optional[str]
    retrieval_count: int
    last_used_at: None
    supersedes: List[str]
    superseded_by: None
    source_file: str

    def as_dict(self) -> dict:
        return {
            "id": self.id,
            "project": self.project,
            "kind": self.kind,
            "scope": self.scope,
            "path_prefixes": self.path_prefixes,
            "summary": self.summary,
            "rationale": self.rationale,
            "evidence": self.evidence,
            "confidence": self.confidence,
            "expires_at": self.expires_at,
            "retrieval_count": self.retrieval_count,
            "last_used_at": self.last_used_at,
            "supersedes": self.supersedes,
            "superseded_by": self.superseded_by,
            "source_file": self.source_file,
        }


def _compute_id(source_filename: str, text: str) -> str:
    """Stable ID: sha256(source_filename + newline + normalized_text)[:16].

    normalized_text collapses whitespace in the entry text so minor reformats
    don't break existing record IDs. Kind tag is excluded so kind transitions
    (PROVISIONAL→PATTERN, PATTERN→INVALID) don't change the ID.
    """
    normalized = re.sub(r"\s+", " ", text).strip()
    raw = source_filename + "\n" + normalized
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def _parse_kind(bracket_content: str) -> str:
    """Extract the kind word from bracket content.

    'PATTERN'              → 'PATTERN'
    'AVOID'                → 'AVOID'
    'INVALID: reason text' → 'INVALID'
    """
    return bracket_content.split(":")[0].split()[0].upper()


def _parse_metadata(meta_str: str) -> dict:
    """Parse space-separated key:value pairs from the metadata comment string.

    Repeated keys (e.g. two issue: tags) are accumulated into a list.
    Single-occurrence keys remain scalars.
    """
    result: dict = {}
    for m in TAG_RE.finditer(meta_str):
        key, val = m.group(1), m.group(2)
        if key in result:
            existing = result[key]
            if isinstance(existing, list):
                existing.append(val)
            else:
                result[key] = [existing, val]
        else:
            result[key] = val
    return result


def _build_evidence(tags: dict) -> List[dict]:
    """Construct the evidence array from parsed metadata tags.

    One evidence object per issue: occurrence. The evidence: tag value
    (if present) becomes evidence_tag for the first issue; evidence2: for
    the second, etc.
    """
    issues = tags.get("issue", [])
    if isinstance(issues, str):
        issues = [issues]

    dates = tags.get("date", [])
    if isinstance(dates, str):
        dates = [dates]

    source = tags.get("source", None)
    if isinstance(source, list):
        source = source[0]

    # Collect evidence tags: evidence: → index 0, evidence2: → index 1, etc.
    evidence_tag_map: dict = {}
    base_ev = tags.get("evidence", None)
    if base_ev and isinstance(base_ev, str):
        evidence_tag_map[0] = base_ev

    for key, val in tags.items():
        m = re.match(r"^evidence(\d+)$", key)
        if m:
            idx = int(m.group(1)) - 1  # evidence2 → index 1
            evidence_tag_map[idx] = val if isinstance(val, str) else val[0]

    result = []
    for i, issue_ref in enumerate(issues):
        issue_num = int(issue_ref.lstrip("#"))
        date_val = dates[i] if i < len(dates) else (dates[0] if dates else None)
        result.append(
            {
                "issue": issue_num,
                "source": source,
                "date": date_val,
                "evidence_tag": evidence_tag_map.get(i),
            }
        )
    return result


def _derive_confidence(kind: str, tags: dict) -> float:
    if kind == "INVALID":
        return 0.0
    if kind == "PROVISIONAL":
        return 0.4
    source = tags.get("source", None)
    if isinstance(source, list):
        source = source[0]
    return SOURCE_CONFIDENCE.get(source, 0.7)


def parse_entry(line: str, source_file: str) -> Optional["MemoryRecord"]:
    """Parse one memory entry line. Returns None if the line doesn't match."""
    m = ENTRY_RE.match(line.rstrip())
    if not m:
        return None

    bracket_content = m.group(1)
    text = m.group(2)
    meta_str = m.group(3)

    kind = _parse_kind(bracket_content)
    tags = _parse_metadata(meta_str)

    record_id = _compute_id(source_file, text)
    scope = SCOPE_MAP.get(source_file, "codebase")
    confidence = _derive_confidence(kind, tags)

    path_val = tags.get("path", None)
    if isinstance(path_val, list):
        path_prefixes = path_val
    elif path_val:
        path_prefixes = [path_val]
    else:
        path_prefixes = []

    expires_at = tags.get("expires", None)
    if isinstance(expires_at, list):
        expires_at = expires_at[0]

    summary = re.sub(r"\s+", " ", text).strip()
    evidence = _build_evidence(tags)

    return MemoryRecord(
        id=record_id,
        project="markethawk",
        kind=kind,
        scope=scope,
        path_prefixes=path_prefixes,
        summary=summary,
        rationale=None,
        evidence=evidence,
        confidence=confidence,
        expires_at=expires_at,
        retrieval_count=0,
        last_used_at=None,
        supersedes=[],
        superseded_by=None,
        source_file=source_file,
    )


def iter_entries(memory_dir: Path, source_file: str):
    """Yield MemoryRecord objects from one memory markdown file.

    Entries below the '---' separator that lack an explicit [PROVISIONAL] or
    [INVALID] tag have their kind overridden to PROVISIONAL with confidence 0.4.
    """
    path = memory_dir / source_file
    if not path.exists():
        return

    in_provisional_section = False
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip() == "---":
            in_provisional_section = True
            continue

        record = parse_entry(line.strip(), source_file)
        if record is None:
            continue

        if in_provisional_section and record.kind not in ("PROVISIONAL", "INVALID"):
            record.kind = "PROVISIONAL"
            record.confidence = 0.4

        yield record


def write_record(record: MemoryRecord, records_dir: Path, dry_run: bool) -> str:
    """Write record JSON file. Returns 'created' or 'skipped'.

    Idempotent: if <records_dir>/<id>.json already exists, returns 'skipped'
    without reading or touching the file.
    """
    path = records_dir / f"{record.id}.json"
    if path.exists():
        return "skipped"
    if not dry_run:
        records_dir.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(record.as_dict(), indent=2, sort_keys=True),
            encoding="utf-8",
        )
    return "created"


def update_index(
    records: List[MemoryRecord], index_path: Path, dry_run: bool
) -> int:
    """Append compact JSONL lines for records not already in index.jsonl.

    Returns count of lines appended (or would-be-appended in dry-run).
    Never removes or rewrites existing lines.
    """
    existing_ids: set = set()
    if index_path.exists():
        for line in index_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line:
                try:
                    obj = json.loads(line)
                    existing_ids.add(obj.get("id"))
                except json.JSONDecodeError:
                    pass

    new_lines = []
    for record in records:
        if record.id not in existing_ids:
            compact = {
                "id": record.id,
                "kind": record.kind,
                "scope": record.scope,
                "path_prefixes": record.path_prefixes,
                "confidence": record.confidence,
                "expires_at": record.expires_at,
                "source_file": record.source_file,
                "summary_snippet": record.summary[:120],
            }
            new_lines.append(json.dumps(compact, sort_keys=True))

    if not dry_run and new_lines:
        with index_path.open("a", encoding="utf-8") as f:
            for line in new_lines:
                f.write(line + "\n")

    return len(new_lines)


def run_import(memory_dir: Path, dry_run: bool = False) -> dict:
    """Run the full import across all five memory files.

    Returns a dict with 'per_file' counts, 'totals', and 'records' list.
    """
    records_dir = memory_dir / "records"
    index_path = memory_dir / "index.jsonl"

    per_file: dict = {}
    all_records: List[MemoryRecord] = []

    for source_file in MEMORY_FILES:
        file_records = list(iter_entries(memory_dir, source_file))
        counts = {"entries": len(file_records), "created": 0, "skipped": 0, "failed": 0}

        for record in file_records:
            try:
                outcome = write_record(record, records_dir, dry_run)
                counts[outcome] += 1
            except Exception as exc:
                counts["failed"] += 1
                print(
                    f"  ERROR: {source_file} id={record.id}: {exc}",
                    file=sys.stderr,
                )

        per_file[source_file] = counts
        all_records.extend(file_records)

    update_index(all_records, index_path, dry_run)

    totals = {
        "total": sum(c["entries"] for c in per_file.values()),
        "created": sum(c["created"] for c in per_file.values()),
        "skipped": sum(c["skipped"] for c in per_file.values()),
        "failed": sum(c["failed"] for c in per_file.values()),
    }

    return {"per_file": per_file, "totals": totals, "records": all_records}


def _print_report(result: dict, memory_dir: Path, dry_run: bool) -> None:
    records_dir = memory_dir / "records"
    index_path = memory_dir / "index.jsonl"
    mode = "dry-run" if dry_run else "write"

    print("Memory import — markethawk")
    print(f"  Source:  {memory_dir}/")
    print(f"  Records: {records_dir}/")
    print(f"  Index:   {index_path}")
    print(f"  Mode:    {mode}")
    print()

    for source_file, counts in result["per_file"].items():
        entries = counts["entries"]
        created = counts["created"]
        skipped = counts["skipped"]
        failed = counts["failed"]
        if dry_run:
            suffix = f"{entries} would-be-created"
        else:
            suffix = f"{created} created, {skipped} skipped, {failed} failed"
        print(f"  {source_file:<30} {entries} entries → {suffix}")

    t = result["totals"]
    print()
    print(
        f"  Total: {t['total']} entries"
        f" | created: {t['created']}"
        f" | skipped: {t['skipped']}"
        f" | failed: {t['failed']}"
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Import .archon/memory/*.md into structured backend"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Compute and print the report without writing any files",
    )
    parser.add_argument(
        "--memory-dir",
        type=Path,
        default=None,
        help="Path to .archon/memory directory (default: repo_root/.archon/memory)",
    )
    args = parser.parse_args()

    if args.memory_dir:
        memory_dir = args.memory_dir.resolve()
    else:
        # dark-factory/scripts/ → repo root (two levels up)
        script_dir = Path(__file__).resolve().parent
        repo_root = script_dir.parent.parent
        memory_dir = repo_root / ".archon" / "memory"

    if not memory_dir.exists():
        print(f"ERROR: memory directory not found: {memory_dir}", file=sys.stderr)
        sys.exit(1)

    result = run_import(memory_dir, dry_run=args.dry_run)
    _print_report(result, memory_dir, dry_run=args.dry_run)

    if result["totals"]["failed"] > 0:
        sys.exit(1)


if __name__ == "__main__":
    main()
```

**Step 2.2 — Verify all unit tests pass**

```bash
cd /workspace/markethawk
python -m pytest dark-factory/tests/test_memory_import.py -v 2>&1
```

Expected output:
```
PASSED dark-factory/tests/test_memory_import.py::test_id_stability
PASSED dark-factory/tests/test_memory_import.py::test_id_kind_transition_stability
PASSED dark-factory/tests/test_memory_import.py::test_invalid_with_embedded_reason
PASSED dark-factory/tests/test_memory_import.py::test_provisional_section_inherits_kind
PASSED dark-factory/tests/test_memory_import.py::test_provisional_section_invalid_keeps_kind
PASSED dark-factory/tests/test_memory_import.py::test_scope_derivation[architecture.md-architecture]
PASSED dark-factory/tests/test_memory_import.py::test_scope_derivation[backend-patterns.md-backend]
PASSED dark-factory/tests/test_memory_import.py::test_scope_derivation[frontend-patterns.md-frontend]
PASSED dark-factory/tests/test_memory_import.py::test_scope_derivation[dark-factory-ops.md-dark-factory]
PASSED dark-factory/tests/test_memory_import.py::test_scope_derivation[codebase-patterns.md-codebase]
PASSED dark-factory/tests/test_memory_import.py::test_confidence_tiering[INVALID: x-implement-0.0]
PASSED dark-factory/tests/test_memory_import.py::test_confidence_tiering[PROVISIONAL-implement-0.4]
PASSED dark-factory/tests/test_memory_import.py::test_confidence_tiering[PATTERN-implement-1.0]
PASSED dark-factory/tests/test_memory_import.py::test_confidence_tiering[PATTERN-conformance-1.0]
PASSED dark-factory/tests/test_memory_import.py::test_confidence_tiering[PATTERN-refine-0.7]
PASSED dark-factory/tests/test_memory_import.py::test_confidence_tiering[PATTERN-code-review-0.7]
PASSED dark-factory/tests/test_memory_import.py::test_confidence_tiering[PATTERN-bootstrap-0.7]
PASSED dark-factory/tests/test_memory_import.py::test_confidence_tiering[PATTERN-unknown-source-0.7]
PASSED dark-factory/tests/test_memory_import.py::test_evidence_single
PASSED dark-factory/tests/test_memory_import.py::test_evidence_multi_evidence2
PASSED dark-factory/tests/test_memory_import.py::test_path_prefixes_present
PASSED dark-factory/tests/test_memory_import.py::test_path_prefixes_absent
PASSED dark-factory/tests/test_memory_import.py::test_expires_at_present
PASSED dark-factory/tests/test_memory_import.py::test_expires_at_absent
PASSED dark-factory/tests/test_memory_import.py::test_write_record_idempotency
PASSED dark-factory/tests/test_memory_import.py::test_dry_run_writes_nothing
PASSED dark-factory/tests/test_memory_import.py::test_integration_dry_run_real_memory

27 passed in X.XXs
```

**Step 2.3 — Commit the implementation**

```bash
git add dark-factory/scripts/memory_import.py
git commit -m "feat: implement memory_import.py — seed structured backend from markdown (#649)"
```

---

## Task 3 — Integration verification and write-mode smoke test

**Files:** None (verification only)

### Steps

**Step 3.1 — Run dry-run against real `.archon/memory/`**

```bash
cd /workspace/markethawk
python dark-factory/scripts/memory_import.py --dry-run
```

Expected output (counts will vary by actual entry count):
```
Memory import — markethawk
  Source:  /workspace/markethawk/.archon/memory/
  Records: /workspace/markethawk/.archon/memory/records/
  Index:   /workspace/markethawk/.archon/memory/index.jsonl
  Mode:    dry-run

  architecture.md                6 entries → 6 would-be-created
  backend-patterns.md            32 entries → 32 would-be-created
  codebase-patterns.md           14 entries → 14 would-be-created
  dark-factory-ops.md            39 entries → 39 would-be-created
  frontend-patterns.md           38 entries → 38 would-be-created

  Total: 129 entries | created: 129 | skipped: 0 | failed: 0
```

Verify no files were created:
```bash
ls .archon/memory/records/ 2>/dev/null && echo "ERROR: records dir exists" || echo "OK: no records written"
ls .archon/memory/index.jsonl 2>/dev/null && echo "ERROR: index written" || echo "OK: no index written"
```

Expected: both `OK:` lines.

**Step 3.2 — Run in write mode**

```bash
python dark-factory/scripts/memory_import.py
```

Expected: same counts with `created: 129 | skipped: 0 | failed: 0` (or real numbers).

Spot-check that files exist and are valid JSON:
```bash
ls .archon/memory/records/ | wc -l
python3 -c "
import json, pathlib
records = list(pathlib.Path('.archon/memory/records').glob('*.json'))
for p in records[:3]:
    d = json.loads(p.read_text())
    print(d['id'], d['kind'], d['scope'], d['source_file'])
"
```

Expected: 3 sample records printed with valid fields.

Spot-check index:
```bash
head -3 .archon/memory/index.jsonl | python3 -c "import json,sys; [print(json.loads(l)) for l in sys.stdin]"
```

Expected: 3 JSON objects each containing `id`, `kind`, `scope`, `summary_snippet`.

**Step 3.3 — Verify idempotency on re-run**

```bash
python dark-factory/scripts/memory_import.py
```

Expected:
```
  Total: 129 entries | created: 0 | skipped: 129 | failed: 0
```

All entries skipped because `records/<id>.json` already exist.

**Step 3.4 — Verify `.md` files untouched**

```bash
git diff -- .archon/memory/*.md
```

Expected: no output (all `.md` files are unchanged).

**Step 3.5 — Commit generated artifacts**

```bash
git add .archon/memory/records/ .archon/memory/index.jsonl
git commit -m "feat: seed structured memory backend from existing markdown entries (#649)"
```

---

## Acceptance Criteria Coverage

| Criterion | Task | How |
|---|---|---|
| Parse all 5 `.md` files idempotently | Task 2 + 3 | `iter_entries()` per file; `write_record()` skips existing |
| `[INVALID]` entries remain invalid | Task 1+2 | `test_invalid_with_embedded_reason`, `test_provisional_section_invalid_keeps_kind` |
| `[PROVISIONAL]` entries remain provisional | Task 1+2 | `test_provisional_section_inherits_kind`, confidence tiering |
| Expiry/path tags preserved | Task 1+2 | `test_expires_at_*`, `test_path_prefixes_*` |
| Import report shows created/skipped/failed | Task 2+3 | `_print_report()`, Step 3.2–3.3 |
| No destructive rewrite of `.md` files | Task 1+2 | `test_integration_dry_run_real_memory` mtime check, Step 3.4 |
| `--dry-run` flag | Task 1+2 | `test_dry_run_writes_nothing`, Step 3.1 |
