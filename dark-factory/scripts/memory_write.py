#!/usr/bin/env python3
"""Write-through memory adapter — flat-file only.

Ports write logic from gate_lib.sh::write_memory_entry() to Python,
adding normalized dedup, agent/scope tagging, and index.jsonl stub write.

Usage:
    python3 memory_write.py \\
        --target      <path to .archon/memory/*.md>             \\
        --path-prefix <e.g. dark-factory/scripts/>              \\
        --text        <core lesson text (no tag prefix)>         \\
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
    """Extract lesson text from a [PATTERN]/[AVOID]/[FIX] line (before <!-- comment).

    Splits on the LAST occurrence of ' <!--' so that body text containing '<!--'
    is not prematurely truncated.
    """
    m = re.match(r"^\- \[(?:PATTERN|AVOID|FIX)\] (.+)$", line)
    if not m:
        return ""
    body = m.group(1)
    # Split on the LAST '<!--' to avoid truncating body text that contains '<!--'
    idx = body.rfind("<!--")
    if idx != -1:
        body = body[:idx]
    return body.strip()


def _is_expired(line, today_str):
    m = re.search(r"expires:(\d{4}-\d{2}-\d{2})", line)
    return bool(m) and m.group(1) < today_str


def _parse_args():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--target", required=True, help="Path to .archon/memory/*.md")
    p.add_argument("--path-prefix", required=True, dest="path_prefix")
    p.add_argument("--text", required=True)
    p.add_argument("--source", required=True)
    p.add_argument("--issue", required=True, type=int)
    return p.parse_args()


def _write_index(index_path, args, agent_id, scope, today_str, expires_str):
    record = {
        "project": "markethawk",
        "type": "avoidance",
        "status": "active",
        "source": args.source,
        "agent_id": agent_id,
        "phase": args.source,
        "issue_number": args.issue,
        "files": [args.path_prefix],
        "scope": scope,
        "content": args.text,
        "created_at": today_str,
        "expires_at": expires_str,
    }
    try:
        with index_path.open("a") as fh:
            fh.write(json.dumps(record) + "\n")
    except OSError as exc:
        print(f"memory-write: WARNING: index.jsonl: write failed ({exc})", file=sys.stderr)


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

    # Sanitize: collapse whitespace (removes embedded newlines) and strip HTML
    # comment delimiters (same as the prior bash pipeline: tr -d '\n\r' | sed 's/-->//g').
    # Both '<!--' and '-->' are stripped so prose containing either cannot break
    # the metadata comment appended to each entry.
    args.text = re.sub(r"\s+", " ", args.text).strip()
    args.text = args.text.replace("<!--", "").replace("-->", "")

    # Load existing content (treat missing file as empty)
    if target.is_dir():
        print(f"memory-write: error: --target is a directory, not a file: {target}", file=sys.stderr)
        sys.exit(1)
    try:
        raw = target.read_text(encoding="utf-8") if target.exists() else ""
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
            # Handle legacy/manually added entries that have no date:/expires: tags:
            # append a new metadata comment so reinforcement is always recorded.
            if "date:" not in updated:
                trailing_newline = "\n" if updated.endswith("\n") else ""
                updated = updated.rstrip("\n")
                updated += f" <!-- date:{today_str} expires:{expires_str} -->{trailing_newline}"
            lines[i] = updated
            try:
                target.write_text("".join(lines), encoding="utf-8")
            except OSError as exc:
                print(f"memory-write: error writing {target}: {exc}", file=sys.stderr)
                sys.exit(1)
            print(f"memory-write: reinforced existing entry in {target}")
            skip_index = True
            break
    else:
        # Step 3: Cap check (30 authoritative entries per file).
        # Count all [PATTERN]/[AVOID]/[FIX] entries, matching the bash floor behavior.
        count = sum(1 for l in lines if _ENTRY_RE.match(l))
        if count >= 30:
            print(f"memory-write: cap reached ({count} entries) in {target} — skipping write")
            skip_index = True
        else:
            # Step 4: Build entry with full tag set per #645 contract.
            # Strip --> and newlines from metadata fields to prevent early comment closure.
            safe_source = args.source.replace("-->", "").replace("\n", "").replace("\r", "")
            safe_path = args.path_prefix.replace("-->", "").replace("\n", "").replace("\r", "")
            entry = (
                f"- [AVOID] {args.text} "
                f"<!-- issue:#{args.issue} date:{today_str} expires:{expires_str} "
                f"source:{safe_source} agent:{safe_source} scope:{scope} "
                f"path:{safe_path} -->"
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
                target.write_text("".join(lines), encoding="utf-8")
            except OSError as exc:
                print(f"memory-write: error writing {target}: {exc}", file=sys.stderr)
                sys.exit(1)

    # Step 6: Best-effort index.jsonl write (skip when markdown was a no-op)
    if not skip_index:
        _write_index(target.parent / "index.jsonl", args, agent_id, scope, today_str, expires_str)

    sys.exit(0)


if __name__ == "__main__":
    main()
