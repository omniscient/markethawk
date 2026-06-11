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
    """``git show --numstat --format=`` lines ('added\\tdeleted\\tpath') → {path: added}.

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


# ── aggregation ────────────────────────────────────────────────────────────────
_TRIAD_KEYS = ("merged_clean", "merged_with_edits", "closed", "open")


def _empty_triad() -> dict:
    return {k: 0 for k in _TRIAD_KEYS}


def count_regressions(items: list[dict], since: datetime, until: datetime) -> int:
    """Issues/PRs carrying the factory-regression label, created in window."""
    return sum(
        1
        for item in items
        if any(lbl["name"] == REGRESSION_LABEL for lbl in item.get("labels", []))
        and in_window(item.get("createdAt"), since, until)
    )


def build_scorecard(
    prs: list[dict],
    issue_sizes: dict[int, str],
    regression_count: int,
    churn: dict,
    since: datetime,
    until: datetime,
) -> dict:
    """Assemble the scorecard.json structure (see spec output contract).

    Triad buckets factory PRs by createdAt; the rework denominator counts
    factory PRs by mergedAt (DORA counts deployments in the period).
    Rework rate is deliberately uncapped — one bad PR can spawn several
    regression tickets, so values above 100% are meaningful.
    """
    triad = _empty_triad()
    by_size: dict[str, dict] = {}
    pr_rows = []
    merged_in_window = 0

    for pr in prs:
        if not is_factory_pr(pr):
            continue
        merged_at = _dt(pr.get("mergedAt"))
        if merged_at and since <= merged_at <= until:
            merged_in_window += 1
        if not in_window(pr.get("createdAt"), since, until):
            continue
        cls = classify_pr(pr)
        triad[cls] += 1
        issue = linked_issue_number(pr.get("headRefName", ""))
        # `or` also catches a None/empty stored value, not just a missing key
        size = (issue_sizes.get(issue) if issue else None) or "unknown"
        by_size.setdefault(size, _empty_triad())[cls] += 1
        pr_rows.append(
            {
                "number": pr["number"],
                "title": pr["title"],
                "classification": cls,
                "issue": issue,
                "size": size,
                "merged_at": pr.get("mergedAt"),
            }
        )

    merged = triad["merged_clean"] + triad["merged_with_edits"]
    resolved = merged + triad["closed"]
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "window": {
            "since": since.date().isoformat(),
            "until": until.date().isoformat(),
        },
        "triad": {
            **triad,
            "merge_rate_pct": round(merged / resolved * 100, 1) if resolved else 0.0,
        },
        "rework": {
            "regression_count": regression_count,
            "merged_factory_prs": merged_in_window,
            "rework_rate_pct": round(regression_count / merged_in_window * 100, 1)
            if merged_in_window
            else 0.0,
        },
        "churn": churn,
        "by_size": by_size,
        "prs": sorted(pr_rows, key=lambda r: r["number"]),
    }


# ── subprocess wrappers (not unit-tested; validated by live run) ──────────────
def _gh(*args: str, paginate: bool = False) -> list | dict:
    # gh emits UTF-8; force it so Windows' locale codec (cp1252) doesn't choke.
    cmd = ["gh", *args] + (["--paginate"] if paginate else [])
    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        check=True,
        encoding="utf-8",
    )
    return json.loads(result.stdout)


def _git(repo_root: str, *args: str) -> str:
    """Run git, returning stdout ('' on failure — e.g. blame on a renamed/deleted
    path, which the churn model counts as churned)."""
    result = subprocess.run(
        ["git", "-C", repo_root, *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    return result.stdout if result.returncode == 0 else ""


_OWNER_REPO = REPO  # "omniscient/markethawk"

_STATE_MAP = {"open": "OPEN", "closed": "CLOSED"}


def _commit_email(c: dict) -> str:
    author = (c.get("commit") or {}).get("author") or {}
    return author.get("email") or ""


def _fetch_pr_commits_rest(pr_number: int) -> list[dict]:
    """Fetch commits for a PR via REST API, returning ``[{authors: [{email}]}]``.

    Each REST commit has ``commit.author.email`` for the primary author.  The
    ``authors`` list mirrors the shape ``is_factory_commit`` expects: a list of
    dicts with an ``email`` key.  Note: co-authors in the commit message body
    (``Co-Authored-By:``) are NOT included; however factory PRs always have
    ``factory@markethawk`` as the *primary* commit author, so omitting
    co-authors is an acceptable approximation.
    Commits with a null author block (deleted accounts, some bots) yield an empty email.
    """
    raw: list[dict] = _gh("api", f"repos/{_OWNER_REPO}/pulls/{pr_number}/commits")
    return [{"authors": [{"email": _commit_email(c)}]} for c in raw]


def fetch_prs() -> list[dict]:
    """Fetch all PRs with commit-author data via the REST v3 API.

    Uses ``gh api --paginate`` for the PR list (avoids GraphQL node-count
    limits that arise when fetching ``commits.authors`` inline) and a separate
    REST call per PR for commit-author data.
    """
    raw_prs: list[dict] = _gh(
        "api", f"repos/{_OWNER_REPO}/pulls?state=all&per_page=100", paginate=True
    )

    prs: list[dict] = []
    for i, rp in enumerate(raw_prs, 1):
        print(f"  [commits {i}/{len(raw_prs)}] PR #{rp['number']}", file=sys.stderr)
        state = "MERGED" if rp.get("merged_at") else _STATE_MAP.get(rp["state"], rp["state"].upper())
        labels = [{"name": lbl["name"]} for lbl in rp.get("labels", [])]
        commits = _fetch_pr_commits_rest(rp["number"])
        prs.append({
            "number": rp["number"],
            "title": rp["title"],
            "headRefName": rp["head"]["ref"],
            "state": state,
            "createdAt": rp["created_at"],
            "closedAt": rp.get("closed_at"),
            "mergedAt": rp.get("merged_at"),
            "labels": labels,
            "commits": commits,
        })
    return prs


def fetch_issues() -> list[dict]:
    """Fetch all issues via the REST v3 API (avoids GraphQL quota)."""
    raw: list[dict] = _gh(
        "api", f"repos/{_OWNER_REPO}/issues?state=all&per_page=100", paginate=True
    )
    # The REST issues endpoint returns both issues and pull requests; filter to
    # issues only (PRs have a 'pull_request' key).
    issues_only = [item for item in raw if "pull_request" not in item]
    return [
        {
            "number": iss["number"],
            "createdAt": iss["created_at"],
            "labels": [{"name": lbl["name"]} for lbl in iss.get("labels", [])],
        }
        for iss in issues_only
    ]


def compute_churn(repo_root: str, since: datetime, until: datetime) -> dict:
    """Blame-based 14-day line survival for factory commits on main.

    For each factory-authored, non-merge commit on main old enough to measure
    (≥14 days before ``until``): added lines from ``git show --numstat``,
    surviving lines via ``git blame --line-porcelain`` at the latest main rev
    ≤ commit date + 14 days. Renames/moves and deleted files count as churn;
    binary files are skipped.
    """
    cutoff = until - timedelta(days=CHURN_WINDOW_DAYS)
    log = _git(
        repo_root, "log", "main", "--no-merges",
        # angle brackets anchor the regex to the exact email field
        f"--author=<{FACTORY_EMAIL}>",
        f"--since={since.isoformat()}", f"--until={until.isoformat()}",
        "--format=%H|%cI",
    )
    commits: list[tuple[str, datetime]] = []
    too_young = 0
    for line in log.splitlines():
        sha, _, ciso = line.partition("|")
        cdt = _dt(ciso)
        if cdt is None:
            continue
        if cdt > cutoff:
            too_young += 1
        else:
            commits.append((sha, cdt))

    total_added = 0
    total_surviving = 0
    for i, (sha, cdt) in enumerate(commits, 1):
        print(f"  [churn {i}/{len(commits)}] {sha[:8]}", file=sys.stderr)
        added = parse_numstat(_git(repo_root, "show", "--numstat", "--format=", sha))
        if not added:
            continue
        # normalize to UTC; offset-bearing ISO strings have had parsing quirks
        # in git-for-Windows
        horizon = (cdt.astimezone(timezone.utc) + timedelta(days=CHURN_WINDOW_DAYS)).strftime(
            "%Y-%m-%dT%H:%M:%SZ"
        )
        rev = _git(repo_root, "rev-list", "-1", f"--before={horizon}", "main").strip()
        if not rev:
            continue
        for path, n in added.items():
            total_added += n
            blame = _git(repo_root, "blame", "--line-porcelain", rev, "--", path)
            # cap at n: blame can attribute context-shifted lines beyond what
            # this commit added
            total_surviving += min(count_surviving_lines(blame, sha), n)

    churned = total_added - total_surviving
    return {
        "added_lines": total_added,
        "surviving_lines": total_surviving,
        "churn_pct": round(churned / total_added * 100, 1) if total_added else 0.0,
        "commits_analyzed": len(commits),
        "commits_too_young": too_young,
    }


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--since", default="2026-05-01", help="YYYY-MM-DD, inclusive")
    parser.add_argument("--until", default=None, help="YYYY-MM-DD, inclusive (default: today UTC)")
    parser.add_argument("--output", default="scorecard.json")
    parser.add_argument("--repo-root", default=".")
    args = parser.parse_args()

    since = datetime.fromisoformat(args.since).replace(tzinfo=timezone.utc)
    until_base = (
        datetime.fromisoformat(args.until).replace(tzinfo=timezone.utc)
        if args.until
        else datetime.now(timezone.utc)
    )
    until = until_base.replace(hour=23, minute=59, second=59)

    print("Fetching PRs…", file=sys.stderr)
    prs = fetch_prs()
    print(f"  {len(prs)} PRs", file=sys.stderr)

    print("Fetching issues…", file=sys.stderr)
    issues = fetch_issues()
    print(f"  {len(issues)} issues", file=sys.stderr)

    issue_sizes: dict[int, str] = {}
    for iss in issues:
        for lbl in iss.get("labels", []):
            m = _SIZE_RE.match(lbl["name"])
            if m:
                issue_sizes[iss["number"]] = m.group(1)

    regression_count = count_regressions(issues + prs, since, until)

    print("Computing churn (git blame survival)…", file=sys.stderr)
    churn = compute_churn(args.repo_root, since, until)

    scorecard = build_scorecard(prs, issue_sizes, regression_count, churn, since, until)
    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(scorecard, f, indent=2)
    print(f"Wrote {args.output}", file=sys.stderr)
