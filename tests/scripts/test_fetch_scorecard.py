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


def test_pr_with_no_commits_is_not_factory():
    assert not is_factory_pr(_pr(commits=[]))


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
    assert in_window("2026-06-11T23:59:59Z", SINCE, UNTIL)
    assert not in_window("2026-04-30T23:59:59Z", SINCE, UNTIL)
    assert not in_window("2026-06-12T00:00:01Z", SINCE, UNTIL)
    assert not in_window(None, SINCE, UNTIL)
