"""
memory_maintain.py — Dark Factory memory lifecycle maintenance CLI.

Usage:
    python memory_maintain.py run [--dry-run] [--no-dry-run] [--scope <path-prefix>]
    python memory_maintain.py invalidate --file <file.md> --match "<substr>" --reason "<why>"

Subcommand 'run' performs expire + promote + dedup on all .archon/memory/*.md files.
All op_* functions are pure (no filesystem access); cmd_* handle I/O and dry-run diffs.
"""
import argparse
import copy
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
META_RE = re.compile(r'<!--.*?-->', re.DOTALL)
DEDUP_THRESHOLD = 0.90


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


@dataclass
class ExpireResult:
    kept_auth: list
    removed_auth: list
    kept_prov: list
    removed_prov: list


@dataclass
class PromoteResult:
    promoted: list        # MemoryEntry objects (now tagged PATTERN/AVOID/FIX)
    remaining_prov: list  # MemoryEntry objects that stay PROVISIONAL


@dataclass
class DedupResult:
    entries: list
    deduped_count: int


def parse_entry(line: str) -> Optional[MemoryEntry]:
    """Parse one markdown list line into a MemoryEntry. Returns None for non-entries."""
    m = ENTRY_RE.match(line)
    if not m:
        return None
    # Strip surrounding whitespace from raw_meta so render_entry reproduces the original
    # "<!-- meta -->" spacing without introducing double-spaces.
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
    """Render a MemoryEntry back to its markdown line. Body is reproduced verbatim."""
    meta_part = f" <!-- {entry.raw_meta} -->" if entry.raw_meta else ""
    return f"{entry.indent}- [{entry.tag}] {entry.body}{meta_part}"


def parse_file_content(content: str) -> MemoryFile:
    """Parse full file content into a MemoryFile. Splits at the first '---' line."""
    lines = content.split("\n")
    split_idx = None
    for i, line in enumerate(lines):
        if line.strip() == "---":
            split_idx = i
            break

    # auth_raw_lines: every raw line in the auth section, including section headers and blanks.
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
            # else: entry removed (expired/promoted) — skip
        else:
            out_lines.append(line)

    return "\n".join(out_lines)


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
            promoted_e = copy.copy(e)
            promoted_e.tag = new_tag
            promoted.append(promoted_e)
        else:
            remaining.append(e)
    return PromoteResult(promoted=promoted, remaining_prov=remaining)


def _strip_meta(body: str) -> str:
    """Strip inline <!-- --> comments and normalise whitespace for comparison."""
    stripped = META_RE.sub("", body)
    return re.sub(r'\s+', ' ', stripped).strip()


def op_dedup(entries: list) -> DedupResult:
    """
    Pure function. Compare each pair of non-INVALID entries by body similarity.
    If ratio >= 0.90, tag the older entry (by date:) as INVALID: superseded.
    Returns all entries with INVALID tags applied.
    """
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
            ratio = difflib.SequenceMatcher(None, a_body, b_body).ratio()
            if ratio >= DEDUP_THRESHOLD:
                a_date = working[i].date_val or date.min
                b_date = working[j].date_val or date.min
                if a_date <= b_date:
                    newer_date = working[j].meta.get("date", "unknown")
                    working[i].tag = f"INVALID: superseded by identical entry added {newer_date}"
                    deduped += 1
                    break  # working[i] is now INVALID; outer loop guard catches it
                else:
                    newer_date = working[i].meta.get("date", "unknown")
                    working[j].tag = f"INVALID: superseded by identical entry added {newer_date}"
                    deduped += 1

    return DedupResult(entries=working, deduped_count=deduped)


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


def apply_ops_to_content(content: str, today: date, scope: Optional[str]) -> tuple:
    """
    Apply expire + promote + dedup to file content string.
    scope: if set, only process entries whose path: tag starts with scope (untagged always processed).
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
    # Out-of-scope entries are kept unconditionally; scope only gates expiry.
    # Preserving order is critical: render_file uses positional replay against
    # auth_raw_lines, so reordering would map entries to wrong section headers.
    new_auth_entries = []
    for e in mf.auth_entries:
        if _in_scope(e):
            ex = e.expires_val
            if ex is not None and ex < today:
                summary["expired_auth"] += 1
                continue
        new_auth_entries.append(e)

    # Expire all provisionals before promotion to prevent promoting an
    # expired-but-out-of-scope provisional.
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

    # Dedup on surviving auth + promoted (promoted entries are appended;
    # render_file's tail-append loop handles entries with no raw line counterpart)
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
                    f"{fname}: expired={summary['expired_auth'] + summary['expired_prov']} "
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
    run_p.add_argument(
        "--dry-run", action="store_true", default=True,
        help="Print diff only; do not write (default: True)"
    )
    run_p.add_argument(
        "--no-dry-run", dest="dry_run", action="store_false",
        help="Actually write changes"
    )
    run_p.add_argument(
        "--scope", default=None,
        help="Restrict to entries whose path: tag starts with this prefix"
    )

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
