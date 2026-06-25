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


# ── Live IO (exercised in manual validation, not unit tests) ────────────────
OWNER = "omniscient/markethawk"
CLONE_DIR = os.environ.get("CLONE_DIR", "/workspace/markethawk")
SMOKE_MARKER = "<!-- df-main-red -->"


def _run(cmd, cwd=None, timeout=600, stdin=None):
    return subprocess.run(cmd, cwd=cwd or CLONE_DIR, input=stdin,
                          capture_output=True, text=True, timeout=timeout)


class LiveIO:
    def __init__(self, cfg):
        self.cfg = cfg

    def regression_issue(self):
        path = os.path.join(os.environ.get("SCHEDULER_STATE_DIR", "/var/lib/dark-factory"),
                            "main-is-red-issue")
        try:
            with open(path) as f:
                n = f.read().strip()
            return int(n) if n else None
        except Exception:
            return None

    def reproduce(self):
        """Run the smoke checks in the clone; return combined failure text (empty if green)."""
        out = []
        tsc = _run(["npx", "tsc", "--noEmit", "-p", "frontend/tsconfig.app.json"],
                   cwd=CLONE_DIR, timeout=300)
        if tsc.returncode != 0:
            out.append("[tsc]\n" + (tsc.stdout or "") + (tsc.stderr or ""))
        imp = _run(["python", "-c", "import backend.app.main"], cwd=CLONE_DIR, timeout=120)
        if imp.returncode != 0:
            out.append("[python import]\n" + (imp.stdout or "") + (imp.stderr or ""))
        return "\n\n".join(out)

    def start_branch(self, issue):
        branch = f"fix/main-red-{issue}"
        _run(["git", "checkout", "-B", branch, "origin/main"])
        return branch

    def apply_fix(self, prompt):
        # headless claude with edit/bash tools, constrained to the clone dir
        _run(["claude", "-p", "--model", self.cfg["model"],
              "--allowedTools", "Edit,Write,Read,Bash,Grep,Glob"],
             stdin=prompt, timeout=self.cfg.get("agent_timeout", 1200))

    def changed_paths(self):
        r = _run(["git", "diff", "--name-only", "origin/main", "--"])
        return [ln.strip() for ln in (r.stdout or "").splitlines() if ln.strip()]

    def open_pr(self, branch, issue, failure):
        _run(["git", "add", "-A"])
        _run(["git", "commit", "-m", f"fix: main-red recovery (regression #{issue})"])
        _run(["git", "push", "-u", "origin", branch, "--force-with-lease"])
        body = (f"Closes #{issue}\n\nAutonomous main-red recovery. Reproduced failure:\n\n"
                f"```\n{failure[:4000]}\n```\n\n---\n*MarketHawk Main-Red Auto-Fix*")
        r = _run(["gh", "pr", "create", "--repo", OWNER, "--base", "main",
                  "--head", branch, "--title", f"fix: main-red recovery (#{issue})",
                  "--body", body])
        m = re.search(r"/pull/(\d+)", r.stdout or "")
        return int(m.group(1)) if m else 0

    def poll_ci(self, pr):
        import time
        deadline = self.cfg.get("ci_wait_minutes", 20) * 60
        waited, step = 0, 30
        while waited < deadline:
            r = _run(["gh", "pr", "checks", str(pr), "--repo", OWNER,
                      "--json", "name,bucket"], timeout=60)
            try:
                checks = json.loads(r.stdout) if r.stdout.strip() else []
            except Exception:
                checks = []
            status = ci_status(checks)
            if status in ("green", "red"):
                return status
            time.sleep(step)
            waited += step
        return "pending"

    def merge(self, pr):
        _run(["gh", "pr", "merge", str(pr), "--repo", OWNER, "--merge", "--delete-branch"])

    def comment(self, issue, body):
        _run(["gh", "issue", "comment", str(issue), "--repo", OWNER, "--body", body])

    def notify(self, title, body, severity, dedupe_key):
        token = os.environ.get("INTERNAL_API_TOKEN", "")
        if not token:
            return
        import urllib.request
        payload = {"title": title, "body": body, "severity": severity}
        if dedupe_key:
            payload["dedupe_key"] = dedupe_key
        try:
            req = urllib.request.Request(
                "http://backend:8000/api/v1/alerts/system",
                data=json.dumps(payload).encode(),
                headers={"Content-Type": "application/json", "X-Internal-Token": token},
                method="POST")
            urllib.request.urlopen(req, timeout=10)
        except Exception:
            pass

    def escalate(self, issue, reason, pr=None):
        pr_txt = f" PR #{pr} left open for review." if pr else ""
        self.comment(issue, f"\U0001f6e0️ **Main-Red Auto-Fix** — escalating to a human "
                            f"(reason: {reason}).{pr_txt}\n\n---\n*MarketHawk Main-Red Auto-Fix*")
        self.notify("Main-red auto-fix needs a human",
                    f"Regression #{issue}: {reason}.{pr_txt}", "warning", f"main-red-{issue}")


def main_once() -> int:
    state_dir = os.environ.get("SCHEDULER_STATE_DIR", "/var/lib/dark-factory")
    path = os.path.join(state_dir, "main-red-fixer-state.json")
    try:
        with open(path) as f:
            state = json.load(f)
    except Exception:
        state = {}
    cfg = dict(
        max_attempts=int(os.environ.get("MAIN_RED_AUTOFIX_MAX_ATTEMPTS", "3")),
        model=os.environ.get("MAIN_RED_AUTOFIX_MODEL", "claude-opus-4-8"),
        ci_wait_minutes=int(os.environ.get("MAIN_RED_AUTOFIX_CI_WAIT_MINUTES", "20")),
        agent_timeout=int(os.environ.get("MAIN_RED_AUTOFIX_AGENT_TIMEOUT", "1200")),
        allowed_paths=["backend/", "frontend/", "alembic/", "dark-factory/smoke_gate.sh",
                       "docker-compose", ".github/", ".env"],
        blocked_paths=["dark-factory/scheduler.sh", "dark-factory/scripts/factory_core/",
                       "dark-factory/entrypoint.sh"])
    out = run_once(cfg, LiveIO(cfg), state)
    try:
        with open(path, "w") as f:
            json.dump(state, f)
    except Exception:
        pass
    print(f"main_red_fixer={out['outcome']} issue=#{out.get('issue')}")
    return 0
