# Factory Scorecard Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement issue #331 — the Factory Scorecard (merge-rate triad, rework rate, 2-week churn, success-by-size) as a third script in the PR #217 dashboard pipeline, rendered into `docs/pipeline-report.html`.

**Architecture:** New `scripts/fetch_scorecard.py` produces `scorecard.json` from `gh pr list` + local git history; `render_report.py` merges it into the injected data blob under a `scorecard` key; `template.html` gains a guarded "Factory Scorecard" section. Pure functions for classification/arithmetic, thin subprocess wrappers for gh/git (same pattern as `fetch_metrics.py`).

**Tech Stack:** Python 3.10+ stdlib only, `gh` CLI, git, ECharts (vendored), pytest.

**Spec:** `docs/superpowers/specs/2026-06-11-factory-scorecard-design.md`

**Key facts the engineer must know (verified live 2026-06-11):**
- Factory commits are authored `MarketHawk Factory <factory@markethawk>`. All PRs (factory and human) share the GitHub login `omniscient`, so PR author is useless — commit authorship is the fingerprint.
- `gh pr list --json commits` returns per-commit `authors: [{name, email, login}]` **including co-authors** — factory commits often carry `Claude Sonnet 4.6 <noreply@anthropic.com>` as co-author, and so do the human's own commits. Rule: a commit is a factory commit **iff `factory@markethawk` appears among its authors**. Never key off the Anthropic co-author.
- Tests run from repo root: `python -m pytest tests/scripts -v` (the `-m` puts the repo root on `sys.path` so `from scripts.fetch_scorecard import …` resolves).
- `tests/scripts/render_smoke.cjs` replays the template's charts with **real ECharts** against the committed `metrics.json`. A bad chart option throws inside `setOption`, halting the page script and blanking everything after it — the stub tests cannot see this. The smoke test must learn to merge `scorecard.json` (Task 6).
- On this Windows machine, piping `gh` JSON through PowerShell mangles non-ASCII (cp1252). The scripts already handle this (`encoding="utf-8"` on subprocess); for ad-hoc verification write to a file first or use `--jq`.

---

### Task 1: PR classification & issue linkage (pure functions)

**Files:**
- Create: `scripts/fetch_scorecard.py`
- Create: `tests/scripts/test_fetch_scorecard.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/scripts/test_fetch_scorecard.py`:

```python
from datetime import datetime, timezone

from scripts.fetch_scorecard import (
    classify_pr,
    in_window,
    is_factory_commit,
    is_factory_pr,
    linked_issue_number,
)

FACTORY = {"name": "MarketHawk Factory", "email": "factory@markethawk", "login": ""}
CLAUDE = {"name": "Claude Sonnet 4.6", "email": "noreply@anthropic.com", "login": "claude"}
HUMAN = {"name": "Francois Germain", "email": "frank.germain@gmail.com", "login": "omniscient"}

SINCE = datetime(2026, 5, 1, tzinfo=timezone.utc)
UNTIL = datetime(2026, 6, 11, 23, 59, 59, tzinfo=timezone.utc)


def _pr(number=1, state="MERGED", commits=None, labels=None,
        head="feat/issue-42-something", created="2026-06-01T00:00:00Z",
        merged="2026-06-02T00:00:00Z"):
    return {
        "number": number, "title": f"PR {number}", "state": state,
        "headRefName": head, "createdAt": created,
        "mergedAt": merged if state == "MERGED" else None,
        "closedAt": None, "labels": labels or [],
        "commits": commits if commits is not None else [{"authors": [FACTORY]}],
    }


# ── factory fingerprint ────────────────────────────────────────────────────────
def test_factory_commit_detected_by_email():
    assert is_factory_commit({"authors": [FACTORY]})


def test_factory_commit_with_claude_coauthor_is_factory():
    assert is_factory_commit({"authors": [FACTORY, CLAUDE]})


def test_human_commit_with_claude_coauthor_is_not_factory():
    assert not is_factory_commit({"authors": [HUMAN, CLAUDE]})


def test_pr_is_factory_if_any_commit_is_factory():
    assert is_factory_pr(_pr(commits=[{"authors": [HUMAN]}, {"authors": [FACTORY]}]))
    assert not is_factory_pr(_pr(commits=[{"authors": [HUMAN, CLAUDE]}]))


# ── triad classification ───────────────────────────────────────────────────────
def test_classify_open_pr():
    assert classify_pr(_pr(state="OPEN")) == "open"


def test_classify_closed_unmerged_pr():
    assert classify_pr(_pr(state="CLOSED")) == "closed"


def test_classify_merged_clean_all_factory_commits():
    pr = _pr(commits=[{"authors": [FACTORY]}, {"authors": [FACTORY, CLAUDE]}])
    assert classify_pr(pr) == "merged_clean"


def test_classify_merged_with_edits_on_human_commit():
    pr = _pr(commits=[{"authors": [FACTORY]}, {"authors": [HUMAN, CLAUDE]}])
    assert classify_pr(pr) == "merged_with_edits"


def test_classify_merged_with_edits_via_label_override():
    pr = _pr(labels=[{"name": "merged-with-edits"}])
    assert classify_pr(pr) == "merged_with_edits"


# ── issue linkage ──────────────────────────────────────────────────────────────
def test_linked_issue_from_factory_branch_convention():
    assert linked_issue_number("feat/issue-287--arch-v3--med--decompose") == 287
    assert linked_issue_number("feat/issue-276-dark-factory-scope") == 276


def test_linked_issue_none_for_human_branches():
    assert linked_issue_number("fix/compose-flower-jwt-secret") is None
    assert linked_issue_number("") is None


# ── window filtering ───────────────────────────────────────────────────────────
def test_in_window_inclusive_bounds():
    assert in_window("2026-05-01T00:00:00Z", SINCE, UNTIL)
    assert in_window("2026-06-11T23:00:00Z", SINCE, UNTIL)
    assert not in_window("2026-04-30T23:59:59Z", SINCE, UNTIL)
    assert not in_window("2026-06-12T00:00:01Z", SINCE, UNTIL)
    assert not in_window(None, SINCE, UNTIL)
```

- [ ] **Step 2: Run tests to verify they fail**

Run from repo root: `python -m pytest tests/scripts/test_fetch_scorecard.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'scripts.fetch_scorecard'`

- [ ] **Step 3: Write the implementation**

Create `scripts/fetch_scorecard.py`:

```python
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
    has_human_commit = any(
        not is_factory_commit(c) for c in pr.get("commits", [])
    )
    if has_human_commit or EDITS_LABEL in label_names:
        return "merged_with_edits"
    return "merged_clean"


def linked_issue_number(head_ref: str) -> int | None:
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/scripts/test_fetch_scorecard.py -v`
Expected: all PASS

- [ ] **Step 5: Commit**

```bash
git add scripts/fetch_scorecard.py tests/scripts/test_fetch_scorecard.py
git commit -m "feat(#331): factory PR classification and issue linkage"
```

---

### Task 2: Churn arithmetic (pure functions)

**Files:**
- Modify: `scripts/fetch_scorecard.py` (append)
- Modify: `tests/scripts/test_fetch_scorecard.py` (append)

- [ ] **Step 1: Write the failing tests**

Append to `tests/scripts/test_fetch_scorecard.py` (and add `count_surviving_lines, parse_numstat` to the existing import from `scripts.fetch_scorecard`):

```python
# ── churn arithmetic ───────────────────────────────────────────────────────────
def test_parse_numstat_extracts_added_lines():
    out = "10\t2\tbackend/app/main.py\n0\t5\tREADME.md\n-\t-\tdocs/img.png\n"
    assert parse_numstat(out) == {"backend/app/main.py": 10}


def test_parse_numstat_empty_output():
    assert parse_numstat("") == {}


def test_count_surviving_lines_counts_only_header_lines_for_sha():
    sha = "a" * 40
    other = "b" * 40
    blame = "\n".join([
        f"{sha} 1 1 2",
        "author MarketHawk Factory",
        "\tline one content",
        f"{sha} 2 2",
        "\tline two content",
        f"{other} 1 3 1",
        f"\t{sha} content line that mentions the sha",
    ])
    assert count_surviving_lines(blame, sha) == 2
    assert count_surviving_lines(blame, other) == 1
    assert count_surviving_lines("", sha) == 0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/scripts/test_fetch_scorecard.py -v -k "numstat or surviving"`
Expected: FAIL — `ImportError: cannot import name 'parse_numstat'`

- [ ] **Step 3: Write the implementation**

Append to `scripts/fetch_scorecard.py`:

```python
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/scripts/test_fetch_scorecard.py -v`
Expected: all PASS

- [ ] **Step 5: Commit**

```bash
git add scripts/fetch_scorecard.py tests/scripts/test_fetch_scorecard.py
git commit -m "feat(#331): churn numstat/blame-survival arithmetic"
```

---

### Task 3: Scorecard aggregation (triad, rework, by-size)

**Files:**
- Modify: `scripts/fetch_scorecard.py` (append)
- Modify: `tests/scripts/test_fetch_scorecard.py` (append)

- [ ] **Step 1: Write the failing tests**

Append to `tests/scripts/test_fetch_scorecard.py` (add `build_scorecard, count_regressions` to the import):

```python
# ── aggregation ────────────────────────────────────────────────────────────────
CHURN_STUB = {"added_lines": 100, "surviving_lines": 80, "churn_pct": 20.0,
              "commits_analyzed": 5, "commits_too_young": 2}


def test_build_scorecard_triad_and_merge_rate():
    prs = [
        _pr(number=1),                                                  # merged_clean
        _pr(number=2, commits=[{"authors": [FACTORY]}, {"authors": [HUMAN]}]),  # with edits
        _pr(number=3, state="CLOSED"),                                  # closed
        _pr(number=4, state="OPEN"),                                    # open
        _pr(number=5, commits=[{"authors": [HUMAN]}]),                  # not factory → ignored
    ]
    sc = build_scorecard(prs, {}, 0, CHURN_STUB, SINCE, UNTIL)
    assert sc["triad"]["merged_clean"] == 1
    assert sc["triad"]["merged_with_edits"] == 1
    assert sc["triad"]["closed"] == 1
    assert sc["triad"]["open"] == 1
    # merge rate excludes open PRs: (1 clean + 1 edits) / 3 resolved
    assert abs(sc["triad"]["merge_rate_pct"] - 66.7) < 0.1
    assert len(sc["prs"]) == 4


def test_build_scorecard_by_size_with_unknown_bucket():
    prs = [
        _pr(number=1, head="feat/issue-10-a"),
        _pr(number=2, head="feat/issue-11-b"),
        _pr(number=3, head="feat/no-issue-ref"),
    ]
    sc = build_scorecard(prs, {10: "S", 11: "L"}, 0, CHURN_STUB, SINCE, UNTIL)
    assert sc["by_size"]["S"]["merged_clean"] == 1
    assert sc["by_size"]["L"]["merged_clean"] == 1
    assert sc["by_size"]["unknown"]["merged_clean"] == 1


def test_build_scorecard_window_filters_by_created_at():
    prs = [
        _pr(number=1, created="2026-04-15T00:00:00Z", merged="2026-04-16T00:00:00Z"),
        _pr(number=2, created="2026-05-15T00:00:00Z"),
    ]
    sc = build_scorecard(prs, {}, 0, CHURN_STUB, SINCE, UNTIL)
    assert [p["number"] for p in sc["prs"]] == [2]
    assert sc["triad"]["merged_clean"] == 1


def test_rework_denominator_uses_merged_at_not_created_at():
    # created before the window but merged inside it → counts toward rework
    # denominator (DORA counts deployments in period), not toward the triad.
    prs = [
        _pr(number=1, created="2026-04-15T00:00:00Z", merged="2026-05-02T00:00:00Z"),
        _pr(number=2, created="2026-05-15T00:00:00Z", merged="2026-05-16T00:00:00Z"),
    ]
    sc = build_scorecard(prs, {}, 1, CHURN_STUB, SINCE, UNTIL)
    assert sc["rework"]["merged_factory_prs"] == 2
    assert sc["rework"]["regression_count"] == 1
    assert abs(sc["rework"]["rework_rate_pct"] - 50.0) < 0.1
    assert sc["triad"]["merged_clean"] == 1  # only #2 in triad


def test_build_scorecard_zero_denominators():
    sc = build_scorecard([], {}, 0, CHURN_STUB, SINCE, UNTIL)
    assert sc["triad"]["merge_rate_pct"] == 0.0
    assert sc["rework"]["rework_rate_pct"] == 0.0


def test_count_regressions_filters_label_and_window():
    items = [
        {"createdAt": "2026-05-10T00:00:00Z", "labels": [{"name": "factory-regression"}]},
        {"createdAt": "2026-04-10T00:00:00Z", "labels": [{"name": "factory-regression"}]},
        {"createdAt": "2026-05-10T00:00:00Z", "labels": [{"name": "bug"}]},
    ]
    assert count_regressions(items, SINCE, UNTIL) == 1
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/scripts/test_fetch_scorecard.py -v -k "scorecard or regressions"`
Expected: FAIL — `ImportError: cannot import name 'build_scorecard'`

- [ ] **Step 3: Write the implementation**

Append to `scripts/fetch_scorecard.py`:

```python
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
        size = issue_sizes.get(issue, "unknown") if issue else "unknown"
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/scripts/test_fetch_scorecard.py -v`
Expected: all PASS

- [ ] **Step 5: Commit**

```bash
git add scripts/fetch_scorecard.py tests/scripts/test_fetch_scorecard.py
git commit -m "feat(#331): scorecard aggregation (triad, rework, by-size)"
```

---

### Task 4: gh/git fetchers, churn orchestration, CLI — then run it live

**Files:**
- Modify: `scripts/fetch_scorecard.py` (append)

No unit tests for this task — these are thin subprocess wrappers around `gh`
and `git`, excluded from unit testing by the same convention as
`fetch_metrics.py`'s fetchers. Validation is the live run in Step 2.

- [ ] **Step 1: Write the fetchers, churn orchestration, and CLI**

Append to `scripts/fetch_scorecard.py`:

```python
# ── subprocess wrappers (not unit-tested; validated by live run) ──────────────
def _gh(*args: str) -> list | dict:
    # gh emits UTF-8; force it so Windows' locale codec (cp1252) doesn't choke.
    result = subprocess.run(
        ["gh", *args],
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


def fetch_prs() -> list[dict]:
    return _gh(
        "pr", "list", "--repo", REPO,
        "--state", "all", "--limit", "1000",
        "--json", "number,title,headRefName,state,createdAt,closedAt,mergedAt,labels,commits",
    )


def fetch_issues() -> list[dict]:
    return _gh(
        "issue", "list", "--repo", REPO,
        "--state", "all", "--limit", "1000",
        "--json", "number,createdAt,labels",
    )


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
        f"--author={FACTORY_EMAIL}",
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
        horizon = (cdt + timedelta(days=CHURN_WINDOW_DAYS)).isoformat()
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
```

- [ ] **Step 2: Run it live for the baseline window**

Run from repo root (PowerShell):
```powershell
python scripts\fetch_scorecard.py --since 2026-05-01 --until 2026-06-11 --output scorecard.json --repo-root .
```
Expected: progress lines on stderr (PR count ~hundreds, churn over dozens of
commits — the blame pass may take a few minutes), then `Wrote scorecard.json`.

- [ ] **Step 3: Sanity-check the output**

```powershell
python -c "import json; d=json.load(open('scorecard.json', encoding='utf-8')); print(json.dumps({k: d[k] for k in ('window','triad','rework','churn','by_size')}, indent=1)); print('prs:', len(d['prs']))"
```
Check: triad counts are non-zero and plausible (most factory PRs merge);
`merge_rate_pct` between 0–100; `churn.added_lines` > 0;
`rework.regression_count` is 0 (label doesn't exist yet — expected);
every PR row has a classification.

- [ ] **Step 4: Run the full suite (no regressions)**

Run: `python -m pytest tests/scripts -v`
Expected: all PASS

- [ ] **Step 5: Commit (script only — scorecard.json snapshot is committed in Task 6 after the labels exist)**

```bash
git add scripts/fetch_scorecard.py
git commit -m "feat(#331): scorecard CLI, gh/git fetchers, churn orchestration"
```

---

### Task 5: Merge scorecard into the render pipeline

**Files:**
- Modify: `scripts/render_report.py`
- Modify: `scripts/generate.sh`
- Modify: `tests/scripts/test_render_report.py` (append)

- [ ] **Step 1: Write the failing tests**

Append to `tests/scripts/test_render_report.py`:

```python
# ── scorecard merge (#331) ─────────────────────────────────────────────────────
def test_render_merges_scorecard_when_present(tmp_path, monkeypatch):
    monkeypatch.setattr(render_report, "_get_echarts_js", lambda: STUB_ECHARTS)
    metrics_path = _write_metrics(tmp_path)
    scorecard_path = tmp_path / "scorecard.json"
    scorecard_path.write_text(json.dumps({"triad": {"merged_clean": 5}}))
    output_path = tmp_path / "report.html"
    render(str(metrics_path), str(TEMPLATE), str(output_path), str(scorecard_path))
    html = output_path.read_text(encoding="utf-8")
    assert '"scorecard"' in html
    assert '"merged_clean": 5' in html


def test_render_without_scorecard_file_still_works(tmp_path, monkeypatch):
    monkeypatch.setattr(render_report, "_get_echarts_js", lambda: STUB_ECHARTS)
    metrics_path = _write_metrics(tmp_path)
    output_path = tmp_path / "report.html"
    render(str(metrics_path), str(TEMPLATE), str(output_path),
           str(tmp_path / "missing.json"))
    html = output_path.read_text(encoding="utf-8")
    assert '"scorecard"' not in html
    assert html.startswith("<!DOCTYPE html")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/scripts/test_render_report.py -v -k scorecard`
Expected: FAIL — `render() takes 3 positional arguments but 4 were given`

- [ ] **Step 3: Update render_report.py**

In `scripts/render_report.py`, change the `render` function signature and body:

```python
def render(
    metrics_path: str,
    template_path: str,
    output_path: str,
    scorecard_path: str | None = None,
) -> None:
    """Render the pipeline report.

    Reads metrics JSON (merging scorecard.json under a ``scorecard`` key when
    present — the template skips the Factory Scorecard section otherwise),
    injects ECharts (vendored) and the data into the template, writes a single
    self-contained HTML file.
    """
    metrics = json.loads(Path(metrics_path).read_text(encoding="utf-8"))
    if scorecard_path and Path(scorecard_path).exists():
        metrics["scorecard"] = json.loads(
            Path(scorecard_path).read_text(encoding="utf-8")
        )
    template = Path(template_path).read_text(encoding="utf-8")
    echarts_js = _get_echarts_js()

    html = template.replace("{{ECHARTS_JS}}", echarts_js, 1)
    html = html.replace(
        "{{METRICS_JSON}}", json.dumps(metrics, indent=2, default=str), 1
    )

    Path(output_path).write_text(html, encoding="utf-8")
    print(f"Wrote {output_path} ({len(html) // 1024} KB)", file=sys.stderr)
```

And in the `__main__` block add the argument and pass it through:

```python
    parser.add_argument("--metrics", default="metrics.json")
    parser.add_argument("--scorecard", default="scorecard.json")
    parser.add_argument("--template", default="scripts/template.html")
    parser.add_argument("--output", default="docs/pipeline-report.html")
    args = parser.parse_args()

    render(args.metrics, args.template, args.output, args.scorecard)
```

- [ ] **Step 4: Update generate.sh**

Replace the body of `scripts/generate.sh` with:

```bash
#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
METRICS_OUT="${METRICS_OUT:-${REPO_ROOT}/metrics.json}"
SCORECARD_OUT="${SCORECARD_OUT:-${REPO_ROOT}/scorecard.json}"
TEMPLATE="${TEMPLATE:-${REPO_ROOT}/scripts/template.html}"
REPORT_OUT="${REPORT_OUT:-${REPO_ROOT}/docs/pipeline-report.html}"

echo "==> Stage 1: fetch metrics"
python3 "${REPO_ROOT}/scripts/fetch_metrics.py" --output "${METRICS_OUT}"

echo "==> Stage 1b: fetch factory scorecard"
python3 "${REPO_ROOT}/scripts/fetch_scorecard.py" \
  --output "${SCORECARD_OUT}" \
  --repo-root "${REPO_ROOT}"

echo "==> Stage 2: render report"
python3 "${REPO_ROOT}/scripts/render_report.py" \
  --metrics "${METRICS_OUT}" \
  --scorecard "${SCORECARD_OUT}" \
  --template "${TEMPLATE}" \
  --output "${REPORT_OUT}"

echo "Done. Report: ${REPORT_OUT}"
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `python -m pytest tests/scripts/test_render_report.py -v`
Expected: all PASS (including the pre-existing tests — `scorecard_path` is optional so they're unaffected)

- [ ] **Step 6: Commit**

```bash
git add scripts/render_report.py scripts/generate.sh tests/scripts/test_render_report.py
git commit -m "feat(#331): merge scorecard.json into the rendered dashboard blob"
```

---

### Task 6: Dashboard section + smoke-test coverage

**Files:**
- Modify: `scripts/template.html`
- Modify: `tests/scripts/render_smoke.cjs`

- [ ] **Step 1: Add the Factory Scorecard section to the template HTML**

In `scripts/template.html`, insert between the closing `</section>` of
`<!-- ── Section 6: Pipeline Health ── -->` and `<!-- ── Issue table ── -->`:

```html
  <!-- ── Section 7: Factory Scorecard (#331) ── -->
  <section id="s-scorecard">
    <h2>Factory Scorecard</h2>
    <div class="kpi-grid" id="scorecard-kpis"></div>
    <div class="chart-grid-2" style="margin-top:1rem">
      <div class="chart-panel">
        <h3>Merge-rate triad</h3>
        <div class="chart-box" id="chart-triad"></div>
      </div>
      <div class="chart-panel">
        <h3>Success by size</h3>
        <div class="chart-box" id="chart-triad-by-size"></div>
      </div>
    </div>
  </section>
```

- [ ] **Step 2: Add the section's JS**

In the same file, insert after the `buildHealth` IIFE (the block ending `})();`
just before `// ── Issue table ──`):

```js
// ── Section 7: Factory Scorecard (#331) ─────────────────────────────────────
(function buildScorecard() {
  const sc = M.scorecard;
  const sect = document.getElementById('s-scorecard');
  if (!sc) { if (sect) sect.style.display = 'none'; return; }

  function kpi(label, value, sub) {
    return `<div class="kpi-card">
      <div class="label">${label}</div>
      <div class="value">${value}</div>
      ${sub ? `<div class="sub">${sub}</div>` : ''}
    </div>`;
  }
  const t = sc.triad;
  document.getElementById('scorecard-kpis').innerHTML = [
    kpi('Merge rate', t.merge_rate_pct.toFixed(1) + '%',
        `${t.merged_clean} clean · ${t.merged_with_edits} w/ edits · ${t.closed} closed`),
    kpi('Rework rate', sc.rework.rework_rate_pct.toFixed(1) + '%',
        `${sc.rework.regression_count} regressions / ${sc.rework.merged_factory_prs} merged PRs`),
    kpi('2-week churn', sc.churn.churn_pct.toFixed(1) + '%',
        `${sc.churn.added_lines.toLocaleString()} lines · ${sc.churn.commits_analyzed} commits`),
    kpi('Window', sc.window.since, `→ ${sc.window.until}`),
  ].join('');

  const TRIAD_NAMES = ['Merged clean', 'Merged w/ edits', 'Closed', 'Open'];
  const TRIAD_KEYS = ['merged_clean', 'merged_with_edits', 'closed', 'open'];
  const TRIAD_COLORS = [C.green, C.amber, C.red, C.mut2];

  eChart('chart-triad', {
    legend:{data:TRIAD_NAMES,textStyle:{color:C.mut},bottom:0},
    xAxis:{type:'value',splitLine:{lineStyle:{color:C.line}},axisLabel:{color:C.mut2}},
    yAxis:{type:'category',data:['Factory PRs'],axisLabel:{color:C.mut2}},
    series:TRIAD_KEYS.map((k,i)=>({
      name:TRIAD_NAMES[i],type:'bar',stack:'t',data:[t[k]],
      itemStyle:{color:TRIAD_COLORS[i]},
    }))
  });

  const sizes = ['S','M','L','XL','unknown'].filter(s => sc.by_size[s]);
  eChart('chart-triad-by-size', {
    legend:{data:TRIAD_NAMES,textStyle:{color:C.mut},bottom:0},
    xAxis:{type:'category',data:sizes,axisLabel:{color:C.mut2},axisLine:{lineStyle:{color:C.line}}},
    yAxis:{type:'value',splitLine:{lineStyle:{color:C.line}},axisLabel:{color:C.mut2}},
    series:TRIAD_KEYS.map((k,i)=>({
      name:TRIAD_NAMES[i],type:'bar',stack:'t',
      data:sizes.map(s=>sc.by_size[s][k]||0),
      itemStyle:{color:TRIAD_COLORS[i]},
    }))
  });
})();
```

- [ ] **Step 3: Teach the smoke test to merge scorecard.json**

In `tests/scripts/render_smoke.cjs`, after the `metricsPath` constant add:

```js
const scorecardPath = path.join(ROOT, "scorecard.json");
```

(do NOT add it to the required-files loop — the smoke test must keep passing
without a scorecard snapshot), and replace these two lines:

```js
const metrics = fs.readFileSync(metricsPath, "utf8");
```
…and later…
```js
const code = scripts[1].replace("{{METRICS_JSON}}", metrics);
```

with:

```js
const metricsObj = JSON.parse(fs.readFileSync(metricsPath, "utf8"));
if (fs.existsSync(scorecardPath)) {
  metricsObj.scorecard = JSON.parse(fs.readFileSync(scorecardPath, "utf8"));
}
```
…and…
```js
const code = scripts[1].replace("{{METRICS_JSON}}", JSON.stringify(metricsObj));
```

- [ ] **Step 4: Run the smoke test against real data (real ECharts, real scorecard)**

Run from repo root: `node tests/scripts/render_smoke.cjs`
Expected: exit 0, no `THROW` lines, and the chart list now includes
`chart-triad` and `chart-triad-by-size`.

- [ ] **Step 5: Run the full suite**

Run: `python -m pytest tests/scripts -v`
Expected: all PASS (the real-ECharts test now exercises the scorecard charts via the snapshot from Task 4)

- [ ] **Step 6: Commit**

```bash
git add scripts/template.html tests/scripts/render_smoke.cjs
git commit -m "feat(#331): factory scorecard dashboard section"
```

---

### Task 7: Labels, regenerated artifacts, baseline comment (close out #331)

**Files:**
- Commit: `scorecard.json`, `docs/pipeline-report.html` (regenerated artifacts)

- [ ] **Step 1: Create the two labels (acceptance criterion #1)**

```powershell
gh label create factory-regression --repo omniscient/markethawk --color B60205 --description "Fixes something a factory PR broke (feeds the scorecard rework rate)"
gh label create merged-with-edits --repo omniscient/markethawk --color FBCA04 --description "Factory PR needed human commits before merge (manual override; normally derived from commit authorship)"
```
Expected: both succeed. Verify: `gh label list --repo omniscient/markethawk --search factory-regression`

- [ ] **Step 2: Regenerate the full dashboard**

Run from repo root (PowerShell — generate.sh's `python3` may not resolve on Windows, so run the stages directly):

```powershell
python scripts\fetch_metrics.py --output metrics.json
python scripts\fetch_scorecard.py --since 2026-05-01 --until 2026-06-11 --output scorecard.json --repo-root .
python scripts\render_report.py --metrics metrics.json --scorecard scorecard.json --template scripts\template.html --output docs\pipeline-report.html
```
Expected: `Wrote docs/pipeline-report.html (… KB)`.

- [ ] **Step 3: Open the report in a browser and eyeball the section**

```powershell
Start-Process docs\pipeline-report.html
```
Check: Factory Scorecard section shows 4 KPI cards with plausible values and
two populated charts; the rest of the report is unchanged.

- [ ] **Step 4: Commit the regenerated artifacts**

```bash
git add metrics.json scorecard.json docs/pipeline-report.html
git commit -m "chore(#331): regenerate dashboard with factory scorecard baseline"
```

- [ ] **Step 5: Post the baseline comment on #331 (acceptance criterion #3)**

Write the numbers from `scorecard.json` into a temp markdown file (NEVER a
heredoc on Windows — use Write + `--body-file`), e.g.
`$env:TEMP\331-baseline.md`:

```markdown
## Baseline: 2026-05-01 → 2026-06-11

| Metric | Value |
|---|---|
| Merge rate | <merge_rate_pct>% (<merged_clean> clean / <merged_with_edits> with edits / <closed> closed; <open> still open) |
| Rework rate | <rework_rate_pct>% (<regression_count> `factory-regression` items / <merged_factory_prs> merged factory PRs) — label created today, so 0 is expected; meaningful from now on |
| 2-week churn | <churn_pct>% (<surviving_lines>/<added_lines> lines survived; <commits_analyzed> commits ≥14d old, <commits_too_young> too young to measure) |

**Success by size** (merged-clean / merged-with-edits / closed / open):
- S: <…> · M: <…> · L: <…> · unknown: <…>

Generated by `python scripts/fetch_scorecard.py --since 2026-05-01 --until 2026-06-11`; rendered on the [pipeline report](../blob/main/docs/pipeline-report.html) Factory Scorecard section.
```

(Replace every `<…>` with the actual values from `scorecard.json` before posting.)

```powershell
gh issue comment 331 --repo omniscient/markethawk --body-file $env:TEMP\331-baseline.md
```

- [ ] **Step 6: Verify all four acceptance criteria, then close #331**

Checklist against the ticket:
1. Labels exist with descriptions — Step 1 ✓
2. Script computes the four metrics for an arbitrary window — `--since/--until` ✓
3. Baseline published as a comment — Step 5 ✓
4. Metrics visible on the dashboard — Steps 2–4 ✓

```powershell
gh issue close 331 --repo omniscient/markethawk --comment "Implemented interactively on main (not via the factory). Spec: docs/superpowers/specs/2026-06-11-factory-scorecard-design.md; plan: docs/superpowers/plans/2026-06-11-factory-scorecard.md."
```
