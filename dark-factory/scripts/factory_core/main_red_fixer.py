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


def build_fix_prompt(failure: str, allowed: list, blocked: list) -> str:
    return f"""main is RED — the dark-factory smoke gate (tsc + python import) is failing on origin/main.
Your job: make the smoke checks pass with the SMALLEST, safest change.

Reproduced failure output:
---
{failure[:6000]}
---

You MAY edit files under: {', '.join(allowed)}.
You MUST NOT edit: {', '.join(blocked)} (the scheduler/factory's own control loop).
If the only correct fix is in a forbidden path, make NO changes and stop — a human will take it.

Make the minimal fix, then stop. Do not commit, push, or open a PR — the harness does that.
"""


def run_once(cfg: dict, io, state: dict) -> dict:
    """One bounded fix attempt. Returns {outcome, issue, ...}."""
    issue = io.regression_issue()
    if issue is None:
        return {"outcome": "noop", "issue": None, "reason": "not-red"}

    attempts = attempts_for(state, issue)
    if should_escalate(attempts, cfg["max_attempts"], "allowed"):  # cap-only check here
        io.escalate(issue, "cap")
        return {"outcome": "escalated", "issue": issue, "reason": "cap"}
    record_attempt(state, issue)

    failure = io.reproduce()
    if not failure:
        return {"outcome": "noop", "issue": issue, "reason": "not-reproduced"}

    branch = io.start_branch(issue)
    io.apply_fix(build_fix_prompt(failure, cfg["allowed_paths"], cfg["blocked_paths"]))
    changed = io.changed_paths()
    if not changed:
        io.escalate(issue, "empty-diff")
        return {"outcome": "escalated", "issue": issue, "reason": "empty-diff"}

    scope = classify_scope(changed, cfg["allowed_paths"], cfg["blocked_paths"])
    if scope != "allowed":
        io.escalate(issue, f"scope:{scope}")
        return {"outcome": "escalated", "issue": issue, "reason": f"scope:{scope}"}

    pr = io.open_pr(branch, issue, failure)
    ci = io.poll_ci(pr)
    if ci == "green":
        io.merge(pr)
        io.notify(f"Main-red auto-fix merged PR #{pr}",
                  f"main is green again (regression #{issue}).", "info", None)
        return {"outcome": "merged", "issue": issue, "pr": pr}

    io.escalate(issue, f"ci:{ci}", pr=pr)
    return {"outcome": "fixing", "issue": issue, "pr": pr, "reason": f"ci:{ci}"}
