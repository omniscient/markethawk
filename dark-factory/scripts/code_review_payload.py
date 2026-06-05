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
    m = _LOC_RE.match((loc or "").strip())
    if m:
        return m.group("path").strip(), int(m.group("line"))
    cleaned = (loc or "").strip()
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
            category, loc, description = "", fields[0], fields[1]
        else:
            category, loc, description = "", "", fields[0]
        path, line = _split_loc(loc)
        findings.append(Finding(severity, category, path, line, description.strip()))
    return findings
