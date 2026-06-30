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
    rationale: Optional[str]
    evidence: List[dict]
    confidence: float
    expires_at: Optional[str]
    retrieval_count: int
    last_used_at: Optional[str]
    supersedes: List[str]
    superseded_by: Optional[str]
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
        try:
            issue_num = int(issue_ref.lstrip("#"))
        except (ValueError, AttributeError):
            issue_num = None
        date_val = dates[i] if i < len(dates) else (dates[0] if dates else None)
        result.append(
            {
                "issue": issue_num,
                "source": source,
                "date": date_val,
                "evidence_tag": evidence_tag_map.get(i),
            }
        )

    # Entries without any issue: tag — emit one evidence object from source/date
    if not issues and (source or dates):
        date_val = dates[0] if dates else None
        result.append(
            {
                "issue": None,
                "source": source,
                "date": date_val,
                "evidence_tag": evidence_tag_map.get(0),
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
            agent_id = record.evidence[0].get("source") if record.evidence else None
            created_at = record.evidence[0].get("date") if record.evidence else None
            compact = {
                "id": record.id,
                "agent_id": agent_id,
                "created_at": created_at,
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

    index_appended = update_index(all_records, index_path, dry_run)

    totals = {
        "total": sum(c["entries"] for c in per_file.values()),
        "created": sum(c["created"] for c in per_file.values()),
        "skipped": sum(c["skipped"] for c in per_file.values()),
        "failed": sum(c["failed"] for c in per_file.values()),
        "index_appended": index_appended,
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
            suffix = f"{created} would-be-created, {skipped} already-exist, {failed} failed"
        else:
            suffix = f"{created} created, {skipped} skipped, {failed} failed"
        print(f"  {source_file:<30} {entries} entries → {suffix}")

    t = result["totals"]
    index_verb = "would-append" if dry_run else "appended"
    print()
    print(
        f"  Total: {t['total']} entries"
        f" | created: {t['created']}"
        f" | skipped: {t['skipped']}"
        f" | failed: {t['failed']}"
        f" | index {index_verb}: {t['index_appended']}"
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
