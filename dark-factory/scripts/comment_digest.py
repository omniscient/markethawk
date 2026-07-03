"""Deterministic filter: extract human feedback after latest factory boundary.

Reads issue.json, finds the latest factory-posted comment (using the same
6-marker bot_re as scheduler.sh), then extracts human-authored comments after
that boundary plus PR reviews and inline comments filtered by timestamp.
No LLM involved.

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
from pathlib import Path

_COMMENT_CONFIG_PATHS = [
    "/workspace/project/.claude/skills/refinement/config.yaml",
    "/opt/refinement-skills/config.yaml",
]

_COMMENT_DEFAULT_MAX_TOKENS = 2000


def _get_comments_max_tokens() -> int:
    """Return the max_tokens cap for comment digest output.

    Priority: TOKEN_OPTIMIZATION_COMMENTS_MAX_TOKENS env var → config value → 2000.
    """
    env_val = os.environ.get("TOKEN_OPTIMIZATION_COMMENTS_MAX_TOKENS", "").strip()
    if env_val:
        try:
            v = int(env_val)
            if v > 0:
                return v
        except ValueError:
            pass
    try:
        import yaml  # type: ignore[import]
        for path in _COMMENT_CONFIG_PATHS:
            try:
                with open(path, encoding="utf-8") as f:
                    data = yaml.safe_load(f)
                val = (data or {}).get("token_optimization", {}).get("comments", {}).get("max_tokens")
                if val is not None:
                    return int(val)
            except Exception:
                continue
    except Exception:
        pass
    return _COMMENT_DEFAULT_MAX_TOKENS


_BOT_RE = re.compile(
    r"Posted by MarketHawk Refinement Pipeline"
    r"|Posted by MarketHawk Backlog Scheduler"
    r"|Posted by MarketHawk Dark Factory"
    r"|Updated by MarketHawk Dark Factory"
    r"|dark-factory-cost-report"
    r"|Posted by MarketHawk Epic Autopilot",
)


def _is_factory_comment(body: str) -> bool:
    return bool(_BOT_RE.search(body))


def _matched_marker(body: str) -> str:
    m = _BOT_RE.search(body)
    return m.group(0) if m else ""


def _feedback_sections(human_comments: list[dict], reviews: list[dict], inline: list[dict]) -> str:
    parts: list[str] = []

    if human_comments:
        parts.append("\n### Issue comments\n\n")
        for c in human_comments:
            created_at = c.get("createdAt") or ""
            body = c.get("body") or ""
            parts.append(f"- [{created_at}] {body}\n")

    if reviews:
        parts.append("\n### PR review comments\n\n")
        for r in reviews:
            submitted_at = r.get("submittedAt") or ""
            body = r.get("body") or ""
            parts.append(f"- [{submitted_at}] {body}\n")

    if inline:
        parts.append("\n### Inline review comments by file\n\n")
        by_path: dict[str, list[dict]] = {}
        for c in inline:
            path = c.get("path") or "unknown"
            by_path.setdefault(path, []).append(c)
        for path in sorted(by_path):
            parts.append(f"#### {path}\n")
            for c in by_path[path]:
                line = c.get("line")
                body = c.get("body") or ""
                line_label = f"Line {line}" if line else "Unanchored"
                parts.append(f"- {line_label}: {body}\n")
            parts.append("\n")

    return "".join(parts)


def build_digest(issue_data: dict) -> str:
    """Build a comment digest from parsed issue.json data.

    Finds the latest factory boundary marker in the comments array, then
    extracts human-authored comments, PR reviews (filtered by submittedAt >
    boundary AND non-bot body), and inline comments (filtered by created_at >
    boundary). Returns a spec-format markdown string, or a sentinel if nothing
    human is found.
    """
    comments: list[dict] = issue_data.get("comments") or []
    pr_reviews_data: dict = issue_data.get("pr_reviews") or {}
    inline_comments: list[dict] = issue_data.get("pr_inline_comments") or []

    # Find index, timestamp, matched marker, and body of the last factory boundary
    last_factory_idx = -1
    boundary_ts: str = ""
    boundary_marker: str = ""
    boundary_body: str = ""
    for i, comment in enumerate(comments):
        body = comment.get("body") or ""
        if _is_factory_comment(body):
            last_factory_idx = i
            boundary_marker = _matched_marker(body)
            boundary_body = body
            # Cutoff = NEWEST factory createdAt, not just the last-by-index comment's
            # (which may be missing/empty). An empty createdAt must not collapse the cutoff
            # to "" and let stale pre-boundary reviews leak in (AI code-review finding).
            ts = comment.get("createdAt") or ""
            if ts > boundary_ts:
                boundary_ts = ts

    # Human comments: after latest factory marker, non-bot
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

    # Inline comments — kept in FULL, never boundary-filtered. Line-level PR comments are
    # code-review FINDINGS (the signal a fix-Continue must act on), not bot noise: the AI
    # reviewer posts them just before its factory "Code Review — Blocked" comment, so a
    # timestamp>boundary filter would drop exactly the findings the run exists to fix.
    # Bot noise lives in issue-level comments (filtered above), not inline threads.
    inline = list(inline_comments)

    no_boundary = last_factory_idx == -1

    # No-boundary case: all human content with a note, or empty sentinel
    if no_boundary:
        all_human = [c for c in comments if not _is_factory_comment(c.get("body") or "")]
        all_reviews_nb = [r for r in all_reviews if not _is_factory_comment(r.get("body") or "")]
        all_inline = inline_comments
        if not all_human and not all_reviews_nb and not all_inline:
            return "<!-- no-human-feedback -->\n"
        sections = _feedback_sections(all_human, all_reviews_nb, all_inline)
        return f"<!-- no-boundary: true -->\n## Human feedback since last factory run\n{sections}"

    # With boundary
    header = f'<!-- comment-digest: cutoff={boundary_ts} marker="{boundary_marker}" -->'

    if not human_comments and not reviews and not inline:
        return (
            f"{header}\n"
            "<!-- no-feedback: true -->\n"
            "No human feedback found after last factory marker.\n"
        )

    snippet = boundary_body[:80] + ("…" if len(boundary_body) > 80 else "")
    sections = _feedback_sections(human_comments, reviews, inline)
    return (
        f"{header}\n"
        f"## Marker\n\n"
        f'Latest factory comment at {boundary_ts}: "{snippet}"\n\n'
        f"## Human feedback since last factory run\n"
        f"{sections}"
    )


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
    max_tokens = _get_comments_max_tokens()
    max_chars = max_tokens * 4
    if len(digest) > max_chars:
        # If max_chars would cut inside a leading HTML comment, extend to its closing -->
        # so the marker is never emitted in a malformed (mid-token) state.
        safe_cut = max_chars
        if digest.startswith("<!--"):
            close = digest.find("-->")
            if close >= 0 and max_chars < close + 3:
                safe_cut = close + 3
        dropped = len(digest) - safe_cut
        digest = digest[:safe_cut] + f"\n<!-- truncated: {dropped} chars dropped (cap={max_tokens} tokens) -->\n"
    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        f.write(digest)
    print(f"comment-digest.md written to {args.out}", file=sys.stderr)


if __name__ == "__main__":
    main()
