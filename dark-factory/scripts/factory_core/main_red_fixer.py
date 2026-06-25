"""Main-Red Auto-Fix — bounded autonomous pipeline recovery (pure core + injected IO).

When the smoke gate marks main red, reproduce the break, run a claude -p fix agent
constrained to allowed paths, verify the diff stays in scope, open a ready PR, poll
branch CI, and merge only on green. See
docs/superpowers/specs/2026-06-21-main-red-autofix-design.md. Ships OFF.

The pure functions below take/return plain data so they unit-test with no IO.
"""
import json
import os
import re
import subprocess


def classify_scope(changed_paths: list, allowed: list, blocked: list) -> str:
    """'protected' if ANY changed path matches a blocked prefix (fail-closed, dominates);
    'allowed' only if EVERY path matches an allowed prefix; else 'unknown'. Empty → 'unknown'."""
    if not changed_paths:
        return "unknown"
    for p in changed_paths:
        if any(b in p for b in blocked):
            return "protected"
    if all(any(a in p for a in allowed) for p in changed_paths):
        return "allowed"
    return "unknown"


def ci_status(checks: list) -> str:
    """Reduce `gh pr checks --json bucket` to green|red|pending. Any fail → red;
    else any pending → pending; else (and at least one check) all pass/skipping → green;
    no checks yet → pending (keep waiting)."""
    buckets = [c.get("bucket") for c in checks]
    if any(b == "fail" for b in buckets):
        return "red"
    if any(b == "pending" for b in buckets):
        return "pending"
    if buckets and all(b in ("pass", "skipping") for b in buckets):
        return "green"
    return "pending"


def attempts_for(state: dict, issue: int) -> int:
    return (state.get("issues") or {}).get(str(issue), {}).get("attempts", 0)


def record_attempt(state: dict, issue: int) -> None:
    d = state.setdefault("issues", {}).setdefault(str(issue), {"attempts": 0})
    d["attempts"] = d.get("attempts", 0) + 1


def should_escalate(attempts: int, cap: int, scope: str) -> bool:
    """Escalate when the attempt cap is reached or the fix scope is not cleanly 'allowed'."""
    return attempts >= cap or scope in ("protected", "unknown")
