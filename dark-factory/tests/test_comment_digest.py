"""Tests for comment_digest.py — deterministic human feedback extractor."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import comment_digest as cd


# ── sentinel / no-feedback ────────────────────────────────────────────────────

def test_no_feedback_all_bot_comments_returns_sentinel():
    """All comments are factory/bot → no-feedback sentinel with boundary header."""
    issue_data = {
        "comments": [
            {"body": "---\n*Posted by MarketHawk Dark Factory*", "author": {"login": "bot"}, "createdAt": "2026-01-01T00:00:00Z"},
        ],
        "pr_reviews": {},
        "pr_inline_comments": [],
    }
    result = cd.build_digest(issue_data)
    assert "<!-- no-feedback: true -->" in result
    assert "No human feedback found after last factory marker." in result
    assert "<!-- comment-digest:" in result


def test_no_feedback_empty_issue_returns_sentinel():
    """No comments/reviews at all → simple no-human-feedback sentinel."""
    result = cd.build_digest({})
    assert "<!-- no-human-feedback -->" in result


def test_no_feedback_empty_lists_returns_sentinel():
    """Empty comments, reviews, inline → simple no-human-feedback sentinel."""
    result = cd.build_digest({"comments": [], "pr_reviews": {}, "pr_inline_comments": []})
    assert "<!-- no-human-feedback -->" in result


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
    """When there is no factory boundary, all human comments are included with a no-boundary note."""
    issue_data = {
        "comments": [
            {"body": "first", "author": {"login": "user"}, "createdAt": "2026-01-01T00:00:00Z"},
            {"body": "second", "author": {"login": "user"}, "createdAt": "2026-01-02T00:00:00Z"},
        ],
    }
    result = cd.build_digest(issue_data)
    assert "<!-- no-boundary: true -->" in result
    assert "first" in result
    assert "second" in result


# ── issue comment feedback ────────────────────────────────────────────────────

def test_issue_comment_section_header():
    """Issue comments produce ### Issue comments section."""
    issue_data = {
        "comments": [
            {"body": "Please fix the bug", "author": {"login": "omniscient"}, "createdAt": "2026-07-01T10:00:00Z"},
        ],
    }
    result = cd.build_digest(issue_data)
    assert "### Issue comments" in result


def test_issue_comment_body_appears():
    """Comment body appears verbatim in digest."""
    issue_data = {
        "comments": [
            {"body": "unique-feedback-xyz", "author": {"login": "alice"}, "createdAt": "2026-07-01T10:00:00Z"},
        ],
    }
    result = cd.build_digest(issue_data)
    assert "unique-feedback-xyz" in result


# ── PR review feedback ────────────────────────────────────────────────────────

def test_pr_review_section_header():
    """PR reviews produce ### PR review comments section."""
    issue_data = {
        "pr_reviews": {
            "reviews": [
                {"body": "needs changes", "author": {"login": "reviewer"}, "submittedAt": "2026-07-01T10:00:00Z", "state": "CHANGES_REQUESTED"},
            ]
        },
    }
    result = cd.build_digest(issue_data)
    assert "### PR review comments" in result


def test_pr_review_body_appears():
    """PR review body appears in digest."""
    issue_data = {
        "pr_reviews": {
            "reviews": [
                {"body": "change-this-thing", "author": {"login": "reviewer"}, "submittedAt": "2026-07-01T10:00:00Z", "state": "CHANGES_REQUESTED"},
            ]
        },
    }
    result = cd.build_digest(issue_data)
    assert "change-this-thing" in result


# ── inline comment feedback ───────────────────────────────────────────────────

def test_inline_comment_section_header():
    """Inline comments produce ### Inline review comments by file section."""
    issue_data = {
        "pr_inline_comments": [
            {"path": "backend/app/main.py", "line": 42, "body": "fix this", "created_at": "2026-07-01T10:00:00Z"},
        ],
    }
    result = cd.build_digest(issue_data)
    assert "### Inline review comments by file" in result


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
    # Both path headers present (spec uses #### path without backticks)
    assert "#### backend/app/main.py" in result
    assert "#### frontend/src/index.tsx" in result
    # backend path header appears before frontend path header (alphabetical)
    assert result.index("#### backend/app/main.py") < result.index("#### frontend/src/index.tsx")
    # Bodies present with spec format "- Line N: body"
    assert "- Line 42: first inline" in result
    assert "- Line 55: second inline" in result
    assert "frontend inline" in result


# ── digest header with cutoff/marker ─────────────────────────────────────────

def test_digest_header_includes_cutoff_and_marker():
    """Output with boundary includes <!-- comment-digest: cutoff=… marker="…" --> header."""
    issue_data = {
        "comments": [
            {"body": "Posted by MarketHawk Dark Factory\nRun complete.", "author": {"login": "bot"}, "createdAt": "2026-01-03T12:00:00Z"},
            {"body": "human-feedback-here", "author": {"login": "user"}, "createdAt": "2026-01-04T10:00:00Z"},
        ],
    }
    result = cd.build_digest(issue_data)
    assert '<!-- comment-digest: cutoff=2026-01-03T12:00:00Z marker="Posted by MarketHawk Dark Factory" -->' in result
    assert "## Marker" in result
    assert "2026-01-03T12:00:00Z" in result


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
                # Factory boundary comment — body starts with the marker text
                {"body": f"{marker}: run complete.", "author": {"login": "bot"}, "createdAt": "2026-01-01T00:00:00Z"},
                # Human comment that comes after — should appear in feedback
                {"body": "after-human-unique-xyz", "author": {"login": "user"}, "createdAt": "2026-01-02T00:00:00Z"},
            ]
        }
        result = cd.build_digest(issue_data)
        assert "after-human-unique-xyz" in result, f"Human comment after marker not included for: {marker}"
        # The boundary marker itself should appear only in the header/Marker section,
        # not as a human feedback entry in the Issue comments section
        assert "### Issue comments" in result or "<!-- comment-digest:" in result, \
            f"Expected digest structure not found for: {marker}"


# ── PR review / inline boundary filtering ─────────────────────────────────────

def test_pr_review_before_boundary_excluded():
    """PR review submitted before the factory boundary timestamp is excluded."""
    issue_data = {
        "comments": [
            {"body": "---\n*Posted by MarketHawk Dark Factory*", "author": {"login": "bot"}, "createdAt": "2026-01-05T00:00:00Z"},
        ],
        "pr_reviews": {
            "reviews": [
                {"body": "old-review-before-factory", "author": {"login": "reviewer"}, "submittedAt": "2026-01-04T00:00:00Z", "state": "CHANGES_REQUESTED"},
            ]
        },
        "pr_inline_comments": [],
    }
    result = cd.build_digest(issue_data)
    assert "<!-- no-feedback: true -->" in result
    assert "old-review-before-factory" not in result


def test_pr_review_after_boundary_included():
    """PR review submitted after the factory boundary timestamp is included."""
    issue_data = {
        "comments": [
            {"body": "---\n*Posted by MarketHawk Dark Factory*", "author": {"login": "bot"}, "createdAt": "2026-01-03T00:00:00Z"},
        ],
        "pr_reviews": {
            "reviews": [
                {"body": "new-review-after-factory", "author": {"login": "reviewer"}, "submittedAt": "2026-01-04T00:00:00Z", "state": "APPROVED"},
            ]
        },
        "pr_inline_comments": [],
    }
    result = cd.build_digest(issue_data)
    assert "new-review-after-factory" in result


def test_inline_comment_before_boundary_kept_as_finding():
    """Inline comments are kept in FULL even before the factory boundary. Line-level PR
    comments are code-review FINDINGS — the AI reviewer posts them just before its factory
    'Code Review — Blocked' comment — and a fix-Continue run must act on them. Filtering
    them out by the boundary timestamp would strand exactly the findings the run exists to
    fix (regression guard for the digest's fix-Continue support)."""
    issue_data = {
        "comments": [
            {"body": "---\n*Posted by MarketHawk Dark Factory*", "author": {"login": "bot"}, "createdAt": "2026-01-05T00:00:00Z"},
        ],
        "pr_reviews": {},
        "pr_inline_comments": [
            {"path": "backend/app/main.py", "line": 10, "body": "review-finding-before-factory", "created_at": "2026-01-04T00:00:00Z"},
        ],
    }
    result = cd.build_digest(issue_data)
    assert "review-finding-before-factory" in result
    assert "<!-- no-feedback: true -->" not in result


def test_inline_comment_after_boundary_included():
    """Inline comment with created_at after boundary timestamp is included."""
    issue_data = {
        "comments": [
            {"body": "---\n*Posted by MarketHawk Dark Factory*", "author": {"login": "bot"}, "createdAt": "2026-01-03T00:00:00Z"},
        ],
        "pr_reviews": {},
        "pr_inline_comments": [
            {"path": "backend/app/main.py", "line": 10, "body": "new-inline-after-factory", "created_at": "2026-01-04T00:00:00Z"},
        ],
    }
    result = cd.build_digest(issue_data)
    assert "new-inline-after-factory" in result


def test_no_boundary_includes_all_pr_reviews_and_inline():
    """When no factory boundary exists, all PR reviews and inline comments are included."""
    issue_data = {
        "comments": [],
        "pr_reviews": {
            "reviews": [
                {"body": "unbounded-review", "author": {"login": "reviewer"}, "submittedAt": "2026-01-01T00:00:00Z", "state": "APPROVED"},
            ]
        },
        "pr_inline_comments": [
            {"path": "backend/app/main.py", "line": 5, "body": "unbounded-inline", "created_at": "2026-01-01T00:00:00Z"},
        ],
    }
    result = cd.build_digest(issue_data)
    assert "unbounded-review" in result
    assert "unbounded-inline" in result


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
