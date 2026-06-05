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
        if line.startswith("+"):
            result.setdefault(current, set()).add(new_ln)
            new_ln += 1
        elif line.startswith("-"):
            continue  # left side only
        else:  # context line (leading space) or blank
            result.setdefault(current, set()).add(new_ln)
            new_ln += 1
    return result
