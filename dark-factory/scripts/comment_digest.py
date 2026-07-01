"""Deterministic filter: extract human feedback after latest factory boundary.

Reads issue.json, finds the latest factory-posted comment (using the same
6-marker bot_re as scheduler.sh), then extracts human-authored comments after
that boundary plus all PR reviews and inline comments.  No LLM involved.

Usage:
  python3 comment_digest.py --issue-json /path/to/issue.json \
    --out /path/to/comment-digest.md
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys

_BOT_RE = re.compile(
    r"Posted by MarketHawk Refinement Pipeline"
    r"|Posted by MarketHawk Backlog Scheduler"
    r"|Posted by MarketHawk Dark Factory"
    r"|Updated by MarketHawk Dark Factory"
    r"|dark-factory-cost-report"
    r"|Posted by MarketHawk Epic Autopilot",
)

_NO_FEEDBACK_SENTINEL = "<!-- no-human-feedback -->\n"


def _is_factory_comment(body: str) -> bool:
    return bool(_BOT_RE.search(body))


def build_digest(issue_data: dict) -> str:
    """Build a comment digest from parsed issue.json data.

    Finds the latest factory boundary marker in the comments array, then
    extracts human-authored comments, PR reviews, and inline comments after
    that boundary.  Filters by timestamp > boundary for reviews and inline.

    Returns a markdown string, or the no-feedback sentinel if nothing human is found.
    """
    comments: list[dict] = issue_data.get("comments") or []
    pr_reviews_data: dict = issue_data.get("pr_reviews") or {}
    inline_comments: list[dict] = issue_data.get("pr_inline_comments") or []

    # Find index and timestamp of the last factory boundary marker
    last_factory_idx = -1
    boundary_ts: str = ""
    for i, comment in enumerate(comments):
        body = comment.get("body") or ""
        if _is_factory_comment(body):
            last_factory_idx = i
            boundary_ts = comment.get("createdAt") or ""

    # Human comments are those after the latest factory marker that aren't bots
    human_comments = [
        c for c in comments[last_factory_idx + 1:]
        if not _is_factory_comment(c.get("body") or "")
    ]

    # PR reviews — filtered by timestamp > boundary and bot body detection
    all_reviews: list[dict] = pr_reviews_data.get("reviews") or []
    reviews = [
        r for r in all_reviews
        if (not boundary_ts or (r.get("submittedAt") or "") > boundary_ts)
        and not _is_factory_comment(r.get("body") or "")
    ]

    # Inline comments — filtered by timestamp > boundary
    inline = [
        c for c in inline_comments
        if not boundary_ts or (c.get("created_at") or "") > boundary_ts
    ]

    if not human_comments and not reviews and not inline:
        return _NO_FEEDBACK_SENTINEL

    parts: list[str] = ["# Comment Digest\n"]

    if human_comments:
        parts.append("## Issue Comments\n")
        for comment in human_comments:
            author = (comment.get("author") or {}).get("login") or "unknown"
            created_at = comment.get("createdAt") or ""
            body = comment.get("body") or ""
            parts.append(f"### @{author} — {created_at}\n\n{body}\n\n---\n")

    if reviews:
        parts.append("## PR Reviews\n")
        for review in reviews:
            author = (review.get("author") or {}).get("login") or "unknown"
            submitted_at = review.get("submittedAt") or ""
            state = review.get("state") or ""
            body = review.get("body") or ""
            state_label = f" ({state})" if state else ""
            parts.append(f"### @{author} — {submitted_at}{state_label}\n\n{body}\n\n---\n")

    if inline:
        parts.append("## Inline Code Review Comments\n")
        by_path: dict[str, list[dict]] = {}
        for c in inline:
            path = c.get("path") or "unknown"
            by_path.setdefault(path, []).append(c)

        for path in sorted(by_path):
            parts.append(f"### `{path}`\n")
            for c in by_path[path]:
                line = c.get("line")
                created_at = c.get("created_at") or ""
                body = c.get("body") or ""
                line_label = f"**Line {line}**" if line else "**Unanchored**"
                parts.append(f"{line_label} — {created_at}:\n{body}\n")
            parts.append("")

    return "\n".join(parts)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Build comment digest from issue.json for Dark Factory continue runs."
    )
    parser.add_argument("--issue-json", required=True, help="Path to issue.json")
    parser.add_argument("--out", required=True, help="Output path for comment-digest.md")
    args = parser.parse_args()

    try:
        with open(args.issue_json, encoding="utf-8") as f:
            issue_data = json.load(f)
    except FileNotFoundError:
        print(f"ERROR: issue.json not found: {args.issue_json}", file=sys.stderr)
        sys.exit(1)
    except json.JSONDecodeError as exc:
        print(f"ERROR: invalid JSON in {args.issue_json}: {exc}", file=sys.stderr)
        sys.exit(1)

    digest = build_digest(issue_data)
    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        f.write(digest)
    print(f"comment-digest.md written to {args.out}", file=sys.stderr)


if __name__ == "__main__":
    main()
