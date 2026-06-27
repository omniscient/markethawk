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

    # No NEW record files written during dry run (records dir may already exist from prior runs)
    records_dir = memory_dir / "records"
    records_before = set(records_dir.glob("*.json")) if records_dir.exists() else set()
    result2 = mi.run_import(memory_dir, dry_run=True)
    records_after = set(records_dir.glob("*.json")) if records_dir.exists() else set()
    assert records_before == records_after, (
        f"Record files were written during dry-run! New files: {records_after - records_before}"
    )
