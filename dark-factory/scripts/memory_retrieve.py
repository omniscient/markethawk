#!/usr/bin/env python3
"""
memory_retrieve.py — Role-aware memory retrieval for Dark Factory workflows.

Primary path: .archon/memory/index.jsonl + records/ (when index is present and non-empty)
Fallback path: scan .archon/memory/*.md files directly

Usage:
    python memory_retrieve.py --phase implement [--files "path1\\npath2"] \\
        [--issue 646] [--memory-dir .archon/memory]

Stdout: markdown memory block for insertion into Archon command prompts.
"""
import argparse
import json
import re
import sys
from datetime import date
from pathlib import Path

# ── Constants ──────────────────────────────────────────────────────────────

GLOBAL_FILES = {"codebase-patterns.md", "architecture.md"}

ALL_MEMORY_FILES = [
    "codebase-patterns.md",
    "architecture.md",
    "backend-patterns.md",
    "frontend-patterns.md",
    "dark-factory-ops.md",
]

# Phase → allowed source tags (area-specific file entries only; global files exempt)
PHASE_SOURCE_MAP = {
    "refine": {"refine"},
    "plan": {"refine"},
    "implement": {"implement"},
    "validate": {"conformance"},
    "review": {"code-review"},
}

# File-path prefix → area memory file
AREA_PREFIX_MAP = [
    (("backend/",), "backend-patterns.md"),
    (("frontend/",), "frontend-patterns.md"),
    (("docker-compose", "Dockerfile", "dark-factory/", ".archon/"), "dark-factory-ops.md"),
]

# Only these kind tags are considered authoritative
AUTHORITATIVE_KINDS = {"PATTERN", "AVOID", "FIX"}

# Parse: - [TAG] body <!-- meta -->
_ENTRY_RE = re.compile(
    r"^- \[(?P<tag>[^\]]+)\]\s+(?P<body>.+?)(?:\s*<!--(?P<meta>[^>]*)-->)?\s*$"
)
# Parse key:value pairs in metadata comment
_TAG_RE = re.compile(r"(\w+\d*):([^\s>]+)")


# ── Area selection ─────────────────────────────────────────────────────────

def select_area_files(files):
    """Layer 1: select memory files relevant to the changed file set.

    Returns a sublist of ALL_MEMORY_FILES in declaration order.
    If files is empty, all five files are included.
    """
    if not files:
        return list(ALL_MEMORY_FILES)

    included = set(GLOBAL_FILES)
    for file_path in files:
        for prefixes, mem_file in AREA_PREFIX_MAP:
            if any(file_path.startswith(p) for p in prefixes):
                included.add(mem_file)

    return [f for f in ALL_MEMORY_FILES if f in included]


# ── Entry-level helpers ────────────────────────────────────────────────────

def parse_meta(meta_str):
    """Extract key:value pairs from a metadata comment string."""
    if not meta_str:
        return {}
    return dict(_TAG_RE.findall(meta_str))


def is_expired(expires_str, today=None):
    """Return True if the expiry date is strictly in the past."""
    if not expires_str:
        return False
    ref = today or date.today().isoformat()
    try:
        return expires_str < ref
    except TypeError:
        return False


def path_specificity(path_prefixes, files):
    """Return the length of the longest path prefix that matches any file in files."""
    if not path_prefixes or not files:
        return 0
    best = 0
    for prefix in path_prefixes:
        for f in files:
            if f.startswith(prefix):
                best = max(best, len(prefix))
    return best


def passes_path_filter(path_prefixes, files):
    """True if the entry's path prefixes match at least one file, or has no restriction."""
    if not path_prefixes:
        return True
    if not files:
        return True
    return any(f.startswith(p) for p in path_prefixes for f in files)


def passes_line_filters(tag, meta, source_file, files, allowed_sources):
    """Layer 2 filter for a parsed markdown entry.

    Excludes PROVISIONAL/INVALID/expired entries, applies source filter
    (global files are exempt), and path-tag filter.
    Entries without a source: tag pass the source filter unconditionally
    (backward-compatible with pre-scoping corpus entries).
    """
    tag_upper = tag.upper()
    if tag_upper == "PROVISIONAL" or tag_upper.startswith("INVALID"):
        return False
    if is_expired(meta.get("expires", "")):
        return False
    if source_file not in GLOBAL_FILES:
        src = meta.get("source", "")
        if src and src not in allowed_sources:
            return False
    path_tag = meta.get("path", "")
    if path_tag:
        if files and not any(f.startswith(path_tag) for f in files):
            return False
    return True


# ── Markdown fallback path ─────────────────────────────────────────────────

def scan_markdown_files(memory_dir, area_files, files, allowed_sources):
    """Scan .md files and return {source_file: [raw_line, ...]} for passing entries."""
    results = {}
    for fname in area_files:
        fpath = Path(memory_dir) / fname
        if not fpath.exists():
            continue
        try:
            text = fpath.read_text(encoding="utf-8")
        except OSError:
            continue

        entries = []
        for line in text.splitlines():
            if line.strip() == "---":
                break
            m = _ENTRY_RE.match(line)
            if not m:
                continue
            tag = m.group("tag")
            meta = parse_meta(m.group("meta") or "")
            if passes_line_filters(tag, meta, fname, files, allowed_sources):
                entries.append(line)

        if entries:
            results[fname] = entries

    return results


def format_markdown_output(results):
    """Format scan_markdown_files output as a ### Memory: block string."""
    parts = []
    for fname in ALL_MEMORY_FILES:
        if fname not in results:
            continue
        parts.append(f"### Memory: {fname}")
        parts.extend(results[fname])
        parts.append("")
    return "\n".join(parts).rstrip()


# ── Index primary path ─────────────────────────────────────────────────────

def scan_index(memory_dir, area_files, files, allowed_sources):
    """Scan index.jsonl and records/ to build ranked entry list.

    Returns list of dicts: {source_file, text, specificity, created_at}.
    Source filter uses agent_id from the index entry per spec §6.
    Record files are read for full summary text (implementation-time decision, spec Open Q #3).
    """
    memory_dir = Path(memory_dir)
    index_path = memory_dir / "index.jsonl"
    records_dir = memory_dir / "records"
    area_set = set(area_files)
    today = date.today().isoformat()

    candidates = []
    for raw in index_path.read_text(encoding="utf-8").splitlines():
        raw = raw.strip()
        if not raw:
            continue
        try:
            entry = json.loads(raw)
        except json.JSONDecodeError:
            continue

        if entry.get("status") in ("provisional", "invalid"):
            continue
        if is_expired(entry.get("expires_at", ""), today):
            continue

        source_file = entry.get("source_file", "")
        if source_file not in area_set:
            continue

        path_prefixes = entry.get("path_prefixes") or []
        if not passes_path_filter(path_prefixes, files):
            continue

        # Source filter: use agent_id from index entry (global files exempt).
        # Entries without agent_id pass unconditionally (backward compat with pre-import corpus).
        if source_file not in GLOBAL_FILES:
            agent_id = entry.get("agent_id") or ""
            if agent_id and agent_id not in allowed_sources:
                continue

        # Read record for full summary (fail-open: fallback to summary_snippet)
        entry_id = entry.get("id")
        if not entry_id:
            continue
        record_path = records_dir / f"{entry_id}.json"
        if record_path.exists():
            try:
                record = json.loads(record_path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                summary = entry.get("summary_snippet", "")
            else:
                summary = record.get("summary", entry.get("summary_snippet", ""))
        else:
            summary = entry.get("summary_snippet", "")

        text = f"- [{entry.get('kind', 'PATTERN')}] {summary}"
        spec = path_specificity(path_prefixes, files)
        candidates.append({
            "source_file": source_file,
            "text": text,
            "specificity": spec,
            "created_at": entry.get("created_at", ""),
        })

    return candidates


def format_index_output(candidates):
    """Format scan_index output, grouped by source_file in ALL_MEMORY_FILES order.

    Within each group: ranked by path specificity (desc) then created_at (desc).
    """
    grouped = {}
    for c in candidates:
        grouped.setdefault(c["source_file"], []).append(c)

    parts = []
    for fname in ALL_MEMORY_FILES:
        if fname not in grouped:
            continue
        entries = sorted(
            grouped[fname],
            key=lambda x: (x["specificity"], x.get("created_at") or ""),
            reverse=True,
        )
        parts.append(f"### Memory: {fname}")
        for e in entries:
            parts.append(e["text"])
        parts.append("")

    return "\n".join(parts).rstrip()


# ── Dispatch ───────────────────────────────────────────────────────────────

def retrieve_memory(memory_dir, phase, files):
    """Return a markdown memory block for the given phase and changed files."""
    allowed_sources = PHASE_SOURCE_MAP.get(phase, set())
    area_files = select_area_files(files)
    memory_dir = Path(memory_dir)

    index_path = memory_dir / "index.jsonl"
    if index_path.exists():
        try:
            candidates = scan_index(memory_dir, area_files, files, allowed_sources)
        except (OSError, ValueError):
            candidates = []
        if candidates:
            return format_index_output(candidates)

    results = scan_markdown_files(memory_dir, area_files, files, allowed_sources)
    return format_markdown_output(results)


# ── Trace emission ────────────────────────────────────────────────────────

def _count_entries(fpath, files, allowed_sources, source_file_name):
    """Count total and included entries in a memory .md file."""
    try:
        text = fpath.read_text(encoding="utf-8")
    except OSError:
        return None

    total = 0
    included = 0
    for line in text.splitlines():
        if line.strip() == "---":
            break
        m = _ENTRY_RE.match(line)
        if not m:
            continue
        total += 1
        tag = m.group("tag")
        meta = parse_meta(m.group("meta") or "")
        if passes_line_filters(tag, meta, source_file_name, files, allowed_sources):
            included += 1

    return {"total": total, "included": included}


def emit_memory_trace(trace_path, phase, files, memory_dir, area_files, allowed_sources):
    """Write memory-trace.json to trace_path. Best-effort: never raises."""
    try:
        memory_dir = Path(memory_dir)
        files_loaded = []
        fallback_used = False

        for fname in area_files:
            fpath = memory_dir / fname
            counts = _count_entries(fpath, files, allowed_sources, fname) if fpath.exists() else None
            if counts is None:
                fallback_used = True
                continue
            files_loaded.append({
                "path": str(fpath),
                "entries_total": counts["total"],
                "entries_included": counts["included"],
                "entries_filtered_out": counts["total"] - counts["included"],
            })

        trace = {
            "schema_version": 1,
            "retrieval_mechanism": "flatfile-pathtag",
            "phase": phase,
            "affected_files": list(files),
            "files_loaded": files_loaded,
            "fallback_used": fallback_used,
        }

        trace_path = Path(trace_path)
        trace_path.parent.mkdir(parents=True, exist_ok=True)
        trace_path.write_text(json.dumps(trace, indent=2), encoding="utf-8")
    except Exception:
        pass


# ── CLI ────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Retrieve Dark Factory memory entries for a workflow phase."
    )
    parser.add_argument(
        "--phase",
        required=True,
        choices=list(PHASE_SOURCE_MAP),
        help="Workflow phase (drives source filter and area selection)",
    )
    parser.add_argument(
        "--files",
        default="",
        help="Newline-separated list of changed or anticipated file paths",
    )
    parser.add_argument("--issue", type=int, default=None, help="Issue number (informational)")
    parser.add_argument("--labels", default="", help="Issue labels (reserved, unused)")
    parser.add_argument(
        "--memory-dir",
        default=".archon/memory",
        help="Path to the memory directory (default: .archon/memory)",
    )
    parser.add_argument(
        "--emit-trace-to",
        default=None,
        metavar="PATH",
        help="Write memory-trace.json to this path (best-effort, non-blocking)",
    )
    args = parser.parse_args()

    memory_dir = Path(args.memory_dir)
    if not memory_dir.exists():
        sys.stderr.write(f"error: memory directory not found: {memory_dir}\n")
        sys.exit(1)

    files = [f.strip() for f in args.files.splitlines() if f.strip()]
    allowed_sources = PHASE_SOURCE_MAP.get(args.phase, set())
    area_files = select_area_files(files)

    output = retrieve_memory(memory_dir, args.phase, files)
    if output:
        print(output)

    if args.emit_trace_to:
        emit_memory_trace(args.emit_trace_to, args.phase, files, memory_dir, area_files, allowed_sources)


if __name__ == "__main__":
    main()
