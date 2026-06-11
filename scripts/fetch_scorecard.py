#!/usr/bin/env python3
"""Factory Scorecard (issue #331) → scorecard.json

Computes the merge-rate triad (Cognition), rework rate (DORA 2025), 2-week
churn (GitClear), and success-by-size (METR) for factory PRs over an arbitrary
date window. Consumed by ``render_report.py`` (merged into the dashboard data
blob under a ``scorecard`` key).

A *factory PR* is any PR with ≥1 commit authored by ``factory@markethawk`` —
all PRs share one GitHub login, so commit authorship is the only reliable
fingerprint. Co-authors (``noreply@anthropic.com``) appear on both factory and
human commits and must be ignored.
"""
import json
import re
import subprocess
import sys
from datetime import datetime, timedelta, timezone

REPO = "omniscient/markethawk"
FACTORY_EMAIL = "factory@markethawk"
REGRESSION_LABEL = "factory-regression"
EDITS_LABEL = "merged-with-edits"
CHURN_WINDOW_DAYS = 14

_ISSUE_RE = re.compile(r"issue-(\d+)")
_SIZE_RE = re.compile(r"size:\s*([SMLX]+)")


# ── factory fingerprint & triad classification ───────────────────────────────
def is_factory_commit(commit: dict) -> bool:
    return any(a.get("email") == FACTORY_EMAIL for a in commit.get("authors", []))


def is_factory_pr(pr: dict) -> bool:
    return any(is_factory_commit(c) for c in pr.get("commits", []))


def classify_pr(pr: dict) -> str:
    """Triad bucket for a factory PR: open | closed | merged_with_edits | merged_clean.

    ``merged_with_edits`` is derived from commit authorship (≥1 non-factory
    commit) with the ``merged-with-edits`` label as a manual override for
    edits git can't see (e.g. a human fix-up pushed to main after merge).
    """
    if pr["state"] == "OPEN":
        return "open"
    if pr["state"] == "CLOSED":
        return "closed"
    label_names = {lbl["name"] for lbl in pr.get("labels", [])}
    # Callers only classify factory PRs (is_factory_pr ⇒ ≥1 commit), so an
    # empty commits list can't occur on the merged path; if it ever did,
    # falling through to merged_clean (no human commit seen) is the intent.
    has_human_commit = any(
        not is_factory_commit(c) for c in pr.get("commits", [])
    )
    if has_human_commit or EDITS_LABEL in label_names:
        return "merged_with_edits"
    return "merged_clean"


def linked_issue_number(head_ref: str | None) -> int | None:
    m = _ISSUE_RE.search(head_ref or "")
    return int(m.group(1)) if m else None


# ── window helpers ────────────────────────────────────────────────────────────
def _dt(iso: str | None) -> datetime | None:
    if not iso:
        return None
    return datetime.fromisoformat(iso.replace("Z", "+00:00"))


def in_window(iso: str | None, since: datetime, until: datetime) -> bool:
    d = _dt(iso)
    return d is not None and since <= d <= until


# ── 2-week churn (GitClear slop signal) ───────────────────────────────────────
def parse_numstat(output: str) -> dict[str, int]:
    """``git show --numstat`` lines ('added\\tdeleted\\tpath') → {path: added}.

    Binary files ('-') and zero-add lines are skipped. Renamed paths come
    through in git's rename syntax and will fail blame later → counted as
    churn, an accepted approximation (see spec).
    """
    added: dict[str, int] = {}
    for line in output.splitlines():
        parts = line.split("\t")
        if len(parts) != 3 or parts[0] == "-":
            continue
        n = int(parts[0])
        if n > 0:
            added[parts[2]] = n
    return added


def count_surviving_lines(blame_output: str, sha: str) -> int:
    """Lines attributed to ``sha`` in ``git blame --line-porcelain`` output.

    Header lines start with '<40-hex sha> <orig> <final>…'; content lines are
    tab-prefixed, so a simple prefix match cannot false-positive on content.
    """
    prefix = sha + " "
    return sum(1 for line in blame_output.splitlines() if line.startswith(prefix))
