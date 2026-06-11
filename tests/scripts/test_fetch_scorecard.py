from datetime import datetime, timezone

from scripts.fetch_scorecard import (
    build_scorecard,
    classify_pr,
    count_regressions,
    count_surviving_lines,
    in_window,
    is_factory_commit,
    is_factory_pr,
    linked_issue_number,
    parse_numstat,
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


# ── churn arithmetic ───────────────────────────────────────────────────────────
def test_parse_numstat_extracts_added_lines():
    out = "10\t2\tbackend/app/main.py\n0\t5\tREADME.md\n-\t-\tdocs/img.png\n"
    assert parse_numstat(out) == {"backend/app/main.py": 10}


def test_parse_numstat_empty_output():
    assert parse_numstat("") == {}


_BLAME_ATTRS = (
    "author Test\nauthor-mail <t@t.com>\nauthor-time 1000000000\nauthor-tz +0000\n"
    "committer Test\ncommitter-mail <t@t.com>\ncommitter-time 1000000000\n"
    "committer-tz +0000\nsummary test commit\nfilename test.py"
)


def test_count_surviving_lines_counts_only_header_lines_for_sha():
    sha = "a" * 40
    other = "b" * 40
    blame = "\n".join([
        f"{sha} 1 1 2",
        _BLAME_ATTRS,
        "\tline one content",
        f"{sha} 2 2",
        _BLAME_ATTRS,
        "\tline two content",
        f"{other} 1 3 1",
        _BLAME_ATTRS,
        f"\t{sha} content line that mentions the sha",
    ])
    assert count_surviving_lines(blame, sha) == 2
    assert count_surviving_lines(blame, other) == 1
    assert count_surviving_lines("", sha) == 0


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
    # the dashboard reads all four keys unconditionally
    assert set(sc["by_size"]["S"]) == {"merged_clean", "merged_with_edits", "closed", "open"}


def test_build_scorecard_window_filters_by_created_at():
    prs = [
        _pr(number=1, created="2026-04-15T00:00:00Z", merged="2026-04-16T00:00:00Z"),
        _pr(number=2, created="2026-05-15T00:00:00Z"),
    ]
    sc = build_scorecard(prs, {}, 0, CHURN_STUB, SINCE, UNTIL)
    assert [p["number"] for p in sc["prs"]] == [2]
    assert sc["triad"]["merged_clean"] == 1
    assert sc["rework"]["merged_factory_prs"] == 1  # PR #1 merged pre-window


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


def test_rework_rate_can_exceed_100_pct():
    # one bad PR can spawn several regression tickets — uncapped by design
    prs = [_pr(number=1, merged="2026-05-16T00:00:00Z")]
    sc = build_scorecard(prs, {}, 3, CHURN_STUB, SINCE, UNTIL)
    assert sc["rework"]["rework_rate_pct"] == 300.0


def test_count_regressions_filters_label_and_window():
    items = [
        {"createdAt": "2026-05-10T00:00:00Z", "labels": [{"name": "factory-regression"}]},
        {"createdAt": "2026-04-10T00:00:00Z", "labels": [{"name": "factory-regression"}]},
        {"createdAt": "2026-05-10T00:00:00Z", "labels": [{"name": "bug"}]},
    ]
    assert count_regressions(items, SINCE, UNTIL) == 1
