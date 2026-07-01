"""Tests for comment_digest.py — deterministic human feedback extractor."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import comment_digest as cd


# ── sentinel / no-feedback ────────────────────────────────────────────────────

def test_no_feedback_all_bot_comments_returns_sentinel():
    """All comments are factory/bot → sentinel returned."""
    issue_data = {
        "comments": [
            {"body": "---\n*Posted by MarketHawk Dark Factory*", "author": {"login": "bot"}, "createdAt": "2026-01-01T00:00:00Z"},
        ],
        "pr_reviews": {},
        "pr_inline_comments": [],
    }
    result = cd.build_digest(issue_data)
    assert result.strip() == "<!-- no-human-feedback -->"


def test_no_feedback_empty_issue_returns_sentinel():
    """No comments/reviews at all → sentinel returned."""
    result = cd.build_digest({})
    assert result.strip() == "<!-- no-human-feedback -->"


def test_no_feedback_empty_lists_returns_sentinel():
    """Empty comments, reviews, inline → sentinel."""
    result = cd.build_digest({"comments": [], "pr_reviews": {}, "pr_inline_comments": []})
    assert result.strip() == "<!-- no-human-feedback -->"


# ── boundary detection ────────────────────────────────────────────────────────

def test_boundary_excludes_comments_before_latest_factory_marker():
    """Human comment before the latest factory marker is excluded."""
    issue_data = {
        "comments": [
            {"body": "early human comment", "author": {"login": "user"}, "createdAt": "2026-01-01T00:00:00Z"},
            {"body": "---\n*Posted by MarketHawk Dark Factory*", "author": {"login": "bot"}, "createdAt": "2026-01-02T00:00:00Z"},
            {"body": "late human comment", "author": {"login": "user"}, "createdAt": "2026-01-03T00:00:00Z"},
        ],
    }
    result = cd.build_digest(issue_data)
    assert "early human comment" not in result
    assert "late human comment" in result


def test_boundary_uses_latest_factory_marker_not_first():
    """With multiple factory markers, comments after the LATEST are included."""
    issue_data = {
        "comments": [
            {"body": "first human comment", "author": {"login": "user"}, "createdAt": "2026-01-01T00:00:00Z"},
            {"body": "---\n*Posted by MarketHawk Dark Factory*", "author": {"login": "bot"}, "createdAt": "2026-01-02T00:00:00Z"},
            {"body": "middle human comment", "author": {"login": "user"}, "createdAt": "2026-01-03T00:00:00Z"},
            {"body": "---\n*Posted by MarketHawk Dark Factory*", "author": {"login": "bot"}, "createdAt": "2026-01-04T00:00:00Z"},
            {"body": "final human comment", "author": {"login": "user"}, "createdAt": "2026-01-05T00:00:00Z"},
        ],
    }
    result = cd.build_digest(issue_data)
    assert "first human comment" not in result
    assert "middle human comment" not in result
    assert "final human comment" in result


def test_no_boundary_all_human_comments_included():
    """When there is no factory boundary, all human comments are included."""
    issue_data = {
        "comments": [
            {"body": "first", "author": {"login": "user"}, "createdAt": "2026-01-01T00:00:00Z"},
            {"body": "second", "author": {"login": "user"}, "createdAt": "2026-01-02T00:00:00Z"},
        ],
    }
    result = cd.build_digest(issue_data)
    assert "first" in result
    assert "second" in result


# ── issue comment feedback ────────────────────────────────────────────────────

def test_issue_comment_section_header():
    """Issue comments produce ## Issue Comments section."""
    issue_data = {
        "comments": [
            {"body": "Please fix the bug", "author": {"login": "omniscient"}, "createdAt": "2026-07-01T10:00:00Z"},
        ],
    }
    result = cd.build_digest(issue_data)
    assert "## Issue Comments" in result


def test_issue_comment_author_and_body():
    """Author login and comment body appear verbatim in digest."""
    issue_data = {
        "comments": [
            {"body": "unique-feedback-xyz", "author": {"login": "alice"}, "createdAt": "2026-07-01T10:00:00Z"},
        ],
    }
    result = cd.build_digest(issue_data)
    assert "@alice" in result
    assert "unique-feedback-xyz" in result


# ── PR review feedback ────────────────────────────────────────────────────────

def test_pr_review_section_header():
    """PR reviews produce ## PR Reviews section."""
    issue_data = {
        "pr_reviews": {
            "reviews": [
                {"body": "needs changes", "author": {"login": "reviewer"}, "submittedAt": "2026-07-01T10:00:00Z", "state": "CHANGES_REQUESTED"},
            ]
        },
    }
    result = cd.build_digest(issue_data)
    assert "## PR Reviews" in result


def test_pr_review_body_and_state():
    """PR review body and state appear in digest."""
    issue_data = {
        "pr_reviews": {
            "reviews": [
                {"body": "change-this-thing", "author": {"login": "reviewer"}, "submittedAt": "2026-07-01T10:00:00Z", "state": "CHANGES_REQUESTED"},
            ]
        },
    }
    result = cd.build_digest(issue_data)
    assert "change-this-thing" in result
    assert "CHANGES_REQUESTED" in result


# ── inline comment feedback ───────────────────────────────────────────────────

def test_inline_comment_section_header():
    """Inline comments produce ## Inline Code Review Comments section."""
    issue_data = {
        "pr_inline_comments": [
            {"path": "backend/app/main.py", "line": 42, "body": "fix this", "created_at": "2026-07-01T10:00:00Z"},
        ],
    }
    result = cd.build_digest(issue_data)
    assert "## Inline Code Review Comments" in result


def test_inline_comments_grouped_by_path():
    """Inline comments from the same file appear under the same path header."""
    issue_data = {
        "pr_inline_comments": [
            {"path": "backend/app/main.py", "line": 42, "body": "first inline", "created_at": "2026-07-01T10:00:00Z"},
            {"path": "frontend/src/index.tsx", "line": 10, "body": "frontend inline", "created_at": "2026-07-01T11:00:00Z"},
            {"path": "backend/app/main.py", "line": 55, "body": "second inline", "created_at": "2026-07-01T12:00:00Z"},
        ],
    }
    result = cd.build_digest(issue_data)
    # Both backend lines appear under the same path header
    assert "`backend/app/main.py`" in result
    assert "`frontend/src/index.tsx`" in result
    # backend path header appears before frontend path header (alphabetical)
    assert result.index("`backend/app/main.py`") < result.index("`frontend/src/index.tsx`")
    # Both inline bodies present
    assert "first inline" in result
    assert "second inline" in result
    assert "frontend inline" in result


# ── all 6 bot markers ─────────────────────────────────────────────────────────

def test_all_six_bot_markers_detected():
    """All six marker strings from bot_re are recognized as factory boundaries."""
    markers = [
        "Posted by MarketHawk Refinement Pipeline",
        "Posted by MarketHawk Backlog Scheduler",
        "Posted by MarketHawk Dark Factory",
        "Updated by MarketHawk Dark Factory",
        "dark-factory-cost-report",
        "Posted by MarketHawk Epic Autopilot",
    ]
    for marker in markers:
        issue_data = {
            "comments": [
                {"body": f"before comment\n---\n*{marker}*", "author": {"login": "bot"}, "createdAt": "2026-01-01T00:00:00Z"},
                {"body": "after human comment", "author": {"login": "user"}, "createdAt": "2026-01-02T00:00:00Z"},
            ]
        }
        result = cd.build_digest(issue_data)
        assert "after human comment" in result, f"Human comment after marker not included for: {marker}"
        assert "before comment" not in result, f"Comment before marker not excluded for: {marker}"


# ── CLI round-trip ────────────────────────────────────────────────────────────

def test_cli_roundtrip(tmp_path):
    """CLI reads issue.json, writes comment-digest.md with expected content."""
    import sys as _sys
    issue_data = {
        "comments": [
            {"body": "cli-roundtrip-feedback", "author": {"login": "user"}, "createdAt": "2026-07-01T10:00:00Z"},
        ],
    }
    issue_json = tmp_path / "issue.json"
    issue_json.write_text(json.dumps(issue_data))
    out_path = tmp_path / "comment-digest.md"

    old_argv = _sys.argv[:]
    try:
        _sys.argv = ["comment_digest.py", "--issue-json", str(issue_json), "--out", str(out_path)]
        cd.main()
    finally:
        _sys.argv = old_argv

    content = out_path.read_text()
    assert "cli-roundtrip-feedback" in content
