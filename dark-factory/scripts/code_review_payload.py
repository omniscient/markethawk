"""Build a GitHub PR review payload from a code-reviewer subagent's findings.

Pure stdlib. Given the reviewer's markdown output and the unified diff that was
reviewed, this parses severity-tagged findings, anchors each to a changed line on
the RIGHT side of the diff, demotes off-diff findings into the review body, decides
the review event (REQUEST_CHANGES if any finding >= block_threshold else COMMENT),
and caps inline comments at max_findings (highest severity kept).

Used by .archon/commands/dark-factory-code-review.md (clone-read; no image rebuild).

Finding wire format (one bullet per finding):
    - [severity] category | path:line | description
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass
from typing import Optional

SEVERITY_ORDER = {"low": 0, "medium": 1, "high": 2, "critical": 3}

_FINDING_RE = re.compile(r"\s*-\s*\[(critical|high|medium|low)\]\s*(.+)$", re.IGNORECASE)
_LOC_RE = re.compile(r"^(?P<path>.+?):(?P<line>\d+)\s*$")


@dataclass
class Finding:
    severity: str
    category: str
    path: Optional[str]
    line: Optional[int]
    description: str


def _split_loc(loc: str):
    cleaned = (loc or "").strip()
    m = _LOC_RE.match(cleaned)
    if m:
        line = int(m.group("line"))
        if line > 0:
            return m.group("path").strip(), line
        return m.group("path").strip(), None  # line 0/negative is not anchorable
    return (cleaned or None), None


def parse_findings(text: str):
    """Parse `- [sev] category | path:line | desc` bullets anywhere in the text."""
    findings = []
    for raw in (text or "").splitlines():
        m = _FINDING_RE.match(raw)
        if not m:
            continue
        severity = m.group(1).lower()
        fields = [p.strip() for p in m.group(2).split("|")]
        if len(fields) >= 3:
            category, loc, description = fields[0], fields[1], " | ".join(fields[2:])
        elif len(fields) == 2:
            # 2-field is a malformed finding (the prompt mandates 3 fields).
            # Disambiguate: if the first field looks like a path:line location,
            # treat it as the location; otherwise treat it as the category.
            first, description = fields[0], fields[1]
            if _LOC_RE.match(first):
                category, loc = "", first
            else:
                category, loc = first, ""
        else:
            category, loc, description = "", "", fields[0]
        path, line = _split_loc(loc)
        findings.append(Finding(severity, category, path, line, description.strip()))
    return findings


_HUNK_RE = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,\d+)? @@")


def changed_lines(diff_text: str):
    """Map each changed file -> set of RIGHT-side (new) line numbers present in the diff.

    Added ('+') and context (' ') lines advance the new-file counter and are anchorable;
    removed ('-') lines do not. Deleted files (+++ /dev/null) are skipped.
    """
    result = {}
    current = None
    new_ln = 0
    for line in (diff_text or "").splitlines():
        if line.startswith("diff --git"):
            current = None
            continue
        if line.startswith("+++ "):
            path = line[4:].strip()
            if path.startswith("b/"):
                path = path[2:]
            current = None if path == "/dev/null" else path
            if current:
                result.setdefault(current, set())
            continue
        if line.startswith("--- "):
            continue
        m = _HUNK_RE.match(line)
        if m:
            new_ln = int(m.group(1))
            continue
        if current is None:
            continue
        if line.startswith("\\"):  # "\ No newline at end of file" — not a content line
            continue
        if line.startswith("+"):
            result.setdefault(current, set()).add(new_ln)
            new_ln += 1
        elif line.startswith("-"):
            continue  # left side only
        else:  # context line (leading space) or blank
            result.setdefault(current, set()).add(new_ln)
            new_ln += 1
    return result


def _comment_body(f: Finding) -> str:
    cat = f"**{f.category}** · " if f.category else ""
    return f"{cat}**{f.severity}** — {f.description}"


def _review_body(header, blockers, advisory, offdiff, dropped_count):
    lines = [f"## {header}", ""]
    lines.append(
        f"**{len(blockers)}** blocking · **{len(advisory)}** advisory finding(s)."
    )
    if blockers:
        lines += ["", "### ⛔ Blocking"]
        for f in blockers:
            loc = f"`{f.path}:{f.line}`" if f.path and f.line else (f"`{f.path}`" if f.path else "_(no location)_")
            lines.append(f"- **[{f.severity}] {f.category}** {loc} — {f.description}")
    if offdiff:
        lines += ["", "### Findings not anchorable to the diff"]
        for f in offdiff:
            loc = f"`{f.path}:{f.line}`" if f.path and f.line else (f"`{f.path}`" if f.path else "_(no location)_")
            lines.append(f"- [{f.severity}] {f.category} {loc} — {f.description}")
    if dropped_count:
        lines += ["", f"_Note: {dropped_count} additional inline comment(s) dropped (max_findings cap)._"]
    return "\n".join(lines)


def build_review(findings, changed, block_threshold="high", max_findings=50,
                 header="🏭 Dark Factory Code Review"):
    thr = SEVERITY_ORDER[block_threshold.lower()]
    blockers = [f for f in findings if SEVERITY_ORDER[f.severity] >= thr]
    advisory = [f for f in findings if SEVERITY_ORDER[f.severity] < thr]

    def anchorable(f):
        return f.path is not None and f.line is not None and f.line in changed.get(f.path, set())

    anchored = sorted(
        (f for f in findings if anchorable(f)),
        key=lambda f: (-SEVERITY_ORDER[f.severity], f.path, f.line),
    )
    offdiff = [f for f in findings if not anchorable(f)]
    kept = anchored[:max_findings]
    dropped = anchored[max_findings:]
    offdiff_for_body = offdiff + dropped

    comments = [{"path": f.path, "line": f.line, "side": "RIGHT", "body": _comment_body(f)} for f in kept]
    event = "REQUEST_CHANGES" if blockers else "COMMENT"
    body = _review_body(header, blockers, advisory, offdiff_for_body, len(dropped))
    status = "BLOCKED" if blockers else "PASS"
    return {
        "status": status,
        "event": event,
        "payload": {"event": event, "body": body, "comments": comments},
        "blockers": [f.__dict__ for f in blockers],
        "advisory": [f.__dict__ for f in advisory],
        "inline_count": len(comments),
        "offdiff_count": len(offdiff_for_body),
    }


def _read(path: str) -> str:
    with open(path, encoding="utf-8") as fh:
        return fh.read()


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Build a GitHub PR review payload from reviewer findings.")
    ap.add_argument("--review", required=True, help="path to the reviewer subagent's markdown output")
    ap.add_argument("--diff", required=True, help="path to the unified diff that was reviewed")
    ap.add_argument("--block-threshold", default="high", choices=list(SEVERITY_ORDER))
    ap.add_argument("--max-findings", type=int, default=50)
    args = ap.parse_args(argv)
    findings = parse_findings(_read(args.review))
    changed = changed_lines(_read(args.diff))
    result = build_review(findings, changed, args.block_threshold, args.max_findings)
    print(json.dumps(result))
    return 0


if __name__ == "__main__":
    sys.exit(main())
