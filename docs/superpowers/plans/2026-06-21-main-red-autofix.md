# Main-Red Auto-Fix Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** When the smoke gate marks main red, autonomously diagnose → fix → verify-CI-green → merge, within a bounded scope envelope, escalating to a human when it can't.

**Architecture:** A new dispatched-container path (NOT inline — a CI wait can't block the scheduler poll loop). The scheduler dispatches `"Fix main"` (mirroring the existing `"Recheck main"` dedupe/throttle pattern); `entrypoint.sh` routes that to a new `factory-core main-red-fix` command; a new pure-core + injected-IO module `main_red_fixer.py` (mirroring `epic_autopilot.py`) drives one bounded attempt: reproduce the break, run a `claude -p` fix agent constrained to allowed paths, verify the produced diff stays in scope, open a ready PR, poll branch CI, and merge only on green. Ships **OFF** behind its own kill-switch.

**Tech Stack:** Python 3 (stdlib only), POSIX sh (`scheduler.sh`, `entrypoint.sh`), `gh` CLI, `claude -p` (headless coding agent), `docker compose run`, pytest.

## Global Constraints

- **Factory self-edit → human-implemented only.** Never auto-refine/implement this. `scheduler.sh`, `entrypoint.sh`, `factory_core/` are **baked** → deploy needs `docker compose build backlog-scheduler && docker compose up -d --force-recreate backlog-scheduler`.
- **Ships OFF.** New kill-switch `main_red_autofix.enabled: false` (env `MAIN_RED_AUTOFIX_ENABLED`). The scheduler block must be gated by it.
- **Scope envelope (pipeline-yes / own-brain-no).** The fix agent may edit `backend/`, `frontend/`, `alembic/`, `dark-factory/smoke_gate.sh`, `docker-compose*`, `.github/`, `.env*`. It is BLOCKED from `dark-factory/scheduler.sh`, `dark-factory/scripts/factory_core/`, `dark-factory/entrypoint.sh`. The produced diff is verified against this envelope AFTER the agent runs (fail-closed): any blocked-path or unclassified-path change → escalate, never merge.
- **Never merge red.** Merge only when branch CI is fully green. Bounded attempt cap (default 3) per red event (keyed by regression issue number); at cap → leave PR open, notify a human, stop.
- **The regression ticket carries NO failure detail** (generic title `"main is red: tsc/python import failure"`). Diagnosis is by **reproduction**: run the smoke checks (`tsc`, python import) in the clone and capture the real errors. The ticket is used only for the issue number + comment trail.
- **Dispatched, not inline.** Mirror `"Recheck main"`: scheduler dedupes on a running `"Fix main"` container and throttles via a stamp file.
- **Reuse existing infra:** the `/api/v1/alerts/system` notify endpoint (same `X-Internal-Token` POST as `epic_autopilot.LiveIO.notify`); `factory_core` pure-core + `LiveIO` + `main_once()` conventions; `cli.py` subcommand registration; the entrypoint clone at `/workspace/markethawk` with `gh`/git auth already set up.
- **Run python tests:** `MSYS_NO_PATHCONV=1 docker run --rm -v /c/git/trading/MarketHawk:/repo -w /repo/dark-factory mh-pytest python -m pytest tests/test_main_red_fixer.py -q` (host can't import `factory_core` — `fcntl` is Unix-only; the `mh-pytest` image is a `python:3.11-slim` + pytest built locally).
- **Run scheduler/entrypoint bash tests:** `bash dark-factory/tests/test_scheduler_main_red_fixer.sh` and `bash dark-factory/tests/test_entrypoint_fix_main.sh` (grep-based, run on the host).

## File Structure

- `dark-factory/scripts/factory_core/main_red_fixer.py` — CREATE. Pure core (`classify_scope`, `ci_status`, attempt-state, `should_escalate`, `build_fix_prompt`, `run_once`) + `LiveIO` + `main_once()`.
- `dark-factory/scripts/factory_core/cli.py` — MODIFY. Add the `main-red-fix` subcommand.
- `dark-factory/entrypoint.sh` — MODIFY. Add a `fix-main` intent override + route (before the smoke-gate run so the gate's red-exit doesn't abort the fixer), invoking `factory-core main-red-fix --once`.
- `dark-factory/scheduler.sh` — MODIFY. Add `is_fixer_running`/`fixer_due`/`main_red_fixer_check`, config exports, and a call inside the existing `MAIN_IS_RED` block.
- `.claude/skills/refinement/config.yaml` — MODIFY. Add the `main_red_autofix:` section.
- `dark-factory/tests/test_main_red_fixer.py` — CREATE. Pure-core unit tests.
- `dark-factory/tests/test_scheduler_main_red_fixer.sh` — CREATE. Grep test for the scheduler wiring.
- `dark-factory/tests/test_entrypoint_fix_main.sh` — CREATE. Grep test for the entrypoint route.

---

### Task 1: Pure core — scope, CI status, attempt state

The IO-free decision logic. All unit-tested.

**Files:**
- Create: `dark-factory/scripts/factory_core/main_red_fixer.py`
- Test: `dark-factory/tests/test_main_red_fixer.py`

**Interfaces:**
- Produces: `classify_scope(changed_paths: list, allowed: list, blocked: list) -> str` (`"protected"|"allowed"|"unknown"`); `ci_status(checks: list) -> str` (`"green"|"red"|"pending"`); `attempts_for(state: dict, issue: int) -> int`; `record_attempt(state: dict, issue: int) -> None`; `should_escalate(attempts: int, cap: int, scope: str) -> bool`.

- [ ] **Step 1: Write the failing tests**

Create `dark-factory/tests/test_main_red_fixer.py`:

```python
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
from factory_core import main_red_fixer as mf  # noqa: E402

ALLOWED = ["backend/", "frontend/", "alembic/", "dark-factory/smoke_gate.sh",
           "docker-compose", ".github/", ".env"]
BLOCKED = ["dark-factory/scheduler.sh", "dark-factory/scripts/factory_core/",
           "dark-factory/entrypoint.sh"]


def test_scope_allowed():
    assert mf.classify_scope(["backend/app/main.py", "frontend/src/x.ts"], ALLOWED, BLOCKED) == "allowed"


def test_scope_allowed_includes_smoke_gate():
    assert mf.classify_scope(["dark-factory/smoke_gate.sh"], ALLOWED, BLOCKED) == "allowed"


def test_scope_protected_blocks_factory_core():
    assert mf.classify_scope(["dark-factory/scripts/factory_core/board.py"], ALLOWED, BLOCKED) == "protected"


def test_scope_protected_wins_over_allowed():
    # one allowed + one blocked → protected (blocked dominates, fail-closed)
    assert mf.classify_scope(["backend/app/x.py", "dark-factory/scheduler.sh"], ALLOWED, BLOCKED) == "protected"


def test_scope_unknown_for_unclassified_path():
    assert mf.classify_scope(["README.md"], ALLOWED, BLOCKED) == "unknown"


def test_scope_unknown_for_empty():
    assert mf.classify_scope([], ALLOWED, BLOCKED) == "unknown"


def test_ci_status_green():
    assert mf.ci_status([{"bucket": "pass"}, {"bucket": "skipping"}, {"bucket": "pass"}]) == "green"


def test_ci_status_red_on_any_fail():
    assert mf.ci_status([{"bucket": "pass"}, {"bucket": "fail"}, {"bucket": "pending"}]) == "red"


def test_ci_status_pending():
    assert mf.ci_status([{"bucket": "pass"}, {"bucket": "pending"}]) == "pending"


def test_ci_status_no_checks_is_pending():
    assert mf.ci_status([]) == "pending"


def test_attempts_roundtrip_and_cap():
    st = {}
    assert mf.attempts_for(st, 700) == 0
    mf.record_attempt(st, 700)
    mf.record_attempt(st, 700)
    assert mf.attempts_for(st, 700) == 2
    assert mf.attempts_for(st, 701) == 0  # per-issue keyed


def test_should_escalate():
    assert mf.should_escalate(3, 3, "allowed") is True          # cap reached
    assert mf.should_escalate(0, 3, "protected") is True        # protected scope
    assert mf.should_escalate(0, 3, "unknown") is True          # fail-closed
    assert mf.should_escalate(1, 3, "allowed") is False
```

- [ ] **Step 2: Run to verify failure**

Run: `MSYS_NO_PATHCONV=1 docker run --rm -v /c/git/trading/MarketHawk:/repo -w /repo/dark-factory mh-pytest python -m pytest tests/test_main_red_fixer.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'factory_core.main_red_fixer'`.

- [ ] **Step 3: Create the module pure-core**

Create `dark-factory/scripts/factory_core/main_red_fixer.py`:

```python
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
```

- [ ] **Step 4: Run to verify pass**

Run: `MSYS_NO_PATHCONV=1 docker run --rm -v /c/git/trading/MarketHawk:/repo -w /repo/dark-factory mh-pytest python -m pytest tests/test_main_red_fixer.py -q`
Expected: PASS (12 tests).

- [ ] **Step 5: Commit**

```bash
git add dark-factory/scripts/factory_core/main_red_fixer.py dark-factory/tests/test_main_red_fixer.py
git commit -m "feat(main-red-fix): pure-core scope/ci-status/attempt-state"
```

---

### Task 2: Orchestrator + fix prompt (pure control flow, injected IO)

`run_once` drives one bounded attempt; `build_fix_prompt` renders the agent instructions. Unit-tested with a FakeIO.

**Files:**
- Modify: `dark-factory/scripts/factory_core/main_red_fixer.py`
- Test: `dark-factory/tests/test_main_red_fixer.py`

**Interfaces:**
- Consumes: `classify_scope`, `ci_status`, `attempts_for`, `record_attempt`, `should_escalate` (Task 1).
- Produces: `build_fix_prompt(failure: str, allowed: list, blocked: list) -> str`; `run_once(cfg: dict, io, state: dict) -> dict` with `outcome` ∈ {`noop`, `escalated`, `merged`, `fixing`}. `io` must provide: `regression_issue() -> int|None`, `reproduce() -> str` (empty if green), `start_branch(issue) -> str`, `apply_fix(prompt) -> None`, `changed_paths() -> list`, `open_pr(branch, issue, failure) -> int`, `poll_ci(pr) -> str`, `merge(pr) -> None`, `comment(issue, body) -> None`, `notify(title, body, severity, dedupe_key) -> None`, `escalate(issue, reason, pr=None) -> None`.

- [ ] **Step 1: Write the failing tests**

Append to `dark-factory/tests/test_main_red_fixer.py`:

```python
class FakeIO:
    def __init__(self, issue=700, failure="tsc error in backend",
                 changed=None, ci="green"):
        self._issue = issue
        self._failure = failure
        self._changed = ["backend/app/x.py"] if changed is None else changed
        self._ci = ci
        self.applied = []
        self.opened = []
        self.merged = []
        self.escalations = []
        self.notes = []
        self.comments = []

    def regression_issue(self):
        return self._issue

    def reproduce(self):
        return self._failure

    def start_branch(self, issue):
        return f"fix/main-red-{issue}"

    def apply_fix(self, prompt):
        self.applied.append(prompt)

    def changed_paths(self):
        return self._changed

    def open_pr(self, branch, issue, failure):
        self.opened.append((branch, issue))
        return 999

    def poll_ci(self, pr):
        return self._ci

    def merge(self, pr):
        self.merged.append(pr)

    def comment(self, issue, body):
        self.comments.append((issue, body))

    def notify(self, title, body, severity, dedupe_key):
        self.notes.append((severity, dedupe_key))

    def escalate(self, issue, reason, pr=None):
        self.escalations.append((issue, reason, pr))


CFG = dict(max_attempts=3, model="claude-opus-4-8",
           allowed_paths=ALLOWED, blocked_paths=BLOCKED)


def test_run_noop_when_not_red():
    io = FakeIO(issue=None)
    out = mf.run_once(CFG, io, {})
    assert out["outcome"] == "noop" and io.applied == []


def test_run_merges_on_green():
    io = FakeIO(ci="green")
    st = {}
    out = mf.run_once(CFG, io, st)
    assert out["outcome"] == "merged" and io.merged == [999]
    assert any(sev == "info" for sev, _ in io.notes)        # recovered notice
    assert mf.attempts_for(st, 700) == 1                    # attempt counted


def test_run_escalates_on_protected_scope_without_pr():
    io = FakeIO(changed=["dark-factory/scheduler.sh"])
    out = mf.run_once(CFG, io, {})
    assert out["outcome"] == "escalated" and "scope" in out["reason"]
    assert io.opened == [] and io.merged == []              # never opened a PR


def test_run_escalates_at_cap_without_attempting():
    io = FakeIO()
    st = {"issues": {"700": {"attempts": 3}}}
    out = mf.run_once(CFG, io, st)
    assert out["outcome"] == "escalated" and out["reason"] == "cap"
    assert io.applied == [] and io.escalations and io.escalations[0][0] == 700


def test_run_escalates_on_red_ci_leaving_pr_open():
    io = FakeIO(ci="red")
    out = mf.run_once(CFG, io, {})
    assert out["outcome"] == "fixing" and io.merged == []
    assert io.escalations and io.escalations[0][2] == 999    # pr passed to escalate


def test_run_escalates_on_empty_diff():
    io = FakeIO(changed=[])
    out = mf.run_once(CFG, io, {})
    assert out["outcome"] == "escalated" and out["reason"] == "empty-diff"


def test_build_fix_prompt_names_scope():
    p = mf.build_fix_prompt("tsc: x.ts(3,1) error", ALLOWED, BLOCKED)
    assert "tsc: x.ts(3,1) error" in p
    assert "dark-factory/scheduler.sh" in p          # blocked list shown
    assert "backend/" in p                            # allowed list shown
```

- [ ] **Step 2: Run to verify failure**

Run: `MSYS_NO_PATHCONV=1 docker run --rm -v /c/git/trading/MarketHawk:/repo -w /repo/dark-factory mh-pytest python -m pytest tests/test_main_red_fixer.py -k "run_ or build_fix" -q`
Expected: FAIL — `run_once`/`build_fix_prompt` not defined.

- [ ] **Step 3: Implement the orchestrator + prompt**

Append to `main_red_fixer.py` (after `should_escalate`):

```python
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
```

(Note: `should_escalate` is called with `"allowed"` here because the cap is the only escalation reason known *before* a fix exists; the scope-based escalation is handled explicitly after `classify_scope`. Keeping `should_escalate` covering both lets it be reused/extended and keeps the cap rule in one place.)

- [ ] **Step 4: Run to verify pass**

Run: `MSYS_NO_PATHCONV=1 docker run --rm -v /c/git/trading/MarketHawk:/repo -w /repo/dark-factory mh-pytest python -m pytest tests/test_main_red_fixer.py -q`
Expected: PASS (all Task 1 + Task 2 tests).

- [ ] **Step 5: Commit**

```bash
git add dark-factory/scripts/factory_core/main_red_fixer.py dark-factory/tests/test_main_red_fixer.py
git commit -m "feat(main-red-fix): run_once orchestrator + scoped fix prompt"
```

---

### Task 3: Live IO + cli wiring

Real adapters (gh, git, claude -p, the smoke checks, the notify endpoint) + `main_once()` + the `cli.py` subcommand. IO-heavy → validated manually (Task 7), no new unit tests (mirrors the `epic_autopilot.LiveIO` convention).

**Files:**
- Modify: `dark-factory/scripts/factory_core/main_red_fixer.py` (add `LiveIO`, `main_once`)
- Modify: `dark-factory/scripts/factory_core/cli.py` (add `main-red-fix` subcommand)

**Interfaces:**
- Consumes: `factory_core.board` constants are not needed here; reuse the `epic_autopilot.LiveIO.notify` HTTP shape.
- Produces: `LiveIO` implementing the `io` methods from Task 2; `main_once() -> int`; cli `main-red-fix --once`.

- [ ] **Step 1: Add `LiveIO` + `main_once`**

Append to `main_red_fixer.py`:

```python
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
```

- [ ] **Step 2: Add the cli subcommand**

In `dark-factory/scripts/factory_core/cli.py`, add a handler near `_epic_autopilot` (after line ~78):

```python
def _main_red_fix(args):
    from factory_core.main_red_fixer import main_once
    main_once()
```

and register it in `main()` after the `epic-autopilot` parser (after line ~119):

```python
    mr = sub.add_parser("main-red-fix")
    mr.add_argument("--once", action="store_true")
    mr.set_defaults(func=_main_red_fix)
```

- [ ] **Step 3: Verify import + suite still green**

Run:
```
MSYS_NO_PATHCONV=1 docker run --rm -v /c/git/trading/MarketHawk:/repo -w /repo/dark-factory mh-pytest python -c "import sys; sys.path.insert(0,'scripts'); import factory_core.main_red_fixer as mf; print(hasattr(mf,'LiveIO'), hasattr(mf,'main_once'))"
MSYS_NO_PATHCONV=1 docker run --rm -v /c/git/trading/MarketHawk:/repo -w /repo/dark-factory mh-pytest python -m pytest tests/test_main_red_fixer.py -q
```
Expected: `True True`; all unit tests pass (LiveIO is not unit-tested but must import cleanly).

- [ ] **Step 4: Commit**

```bash
git add dark-factory/scripts/factory_core/main_red_fixer.py dark-factory/scripts/factory_core/cli.py
git commit -m "feat(main-red-fix): LiveIO adapters + main_once + cli subcommand"
```

---

### Task 4: entrypoint.sh `fix-main` route

Route the dispatched `"Fix main"` command to the fixer, BEFORE the smoke gate runs (so the gate's red-exit-0 doesn't abort the fixer), and disambiguate it from `INTENT=fix`.

**Files:**
- Modify: `dark-factory/entrypoint.sh`
- Create: `dark-factory/tests/test_entrypoint_fix_main.sh`

**Interfaces:**
- Consumes: `factory-core main-red-fix --once` (Task 3).

- [ ] **Step 1: Write the grep test**

Create `dark-factory/tests/test_entrypoint_fix_main.sh`:

```bash
#!/usr/bin/env bash
# Verifies entrypoint.sh routes "Fix main" to the fixer, disambiguated from INTENT=fix,
# and BEFORE the smoke gate can red-exit.
# Run: bash dark-factory/tests/test_entrypoint_fix_main.sh
set -euo pipefail
ep="$(cd "$(dirname "$0")" && pwd)/../entrypoint.sh"

grep -q 'fix-main' "$ep" \
  || { echo "FAIL: no fix-main intent override"; exit 1; }
grep -q 'main-red-fix --once' "$ep" \
  || { echo "FAIL: entrypoint does not invoke the main-red-fix CLI"; exit 1; }

# The fix-main route must appear BEFORE the smoke-gate invocation (so the gate's
# red-exit-0 cannot abort the fixer). Compare line numbers.
route_ln=$(grep -n 'INTENT" = "fix-main"' "$ep" | head -1 | cut -d: -f1)
smoke_ln=$(grep -n 'run_smoke_gate\|smoke_gate.sh' "$ep" | head -1 | cut -d: -f1)
[ -n "$route_ln" ] && [ -n "$smoke_ln" ] && [ "$route_ln" -lt "$smoke_ln" ] \
  || { echo "FAIL: fix-main route ($route_ln) not before smoke gate ($smoke_ln)"; exit 1; }

echo "PASS"
```

- [ ] **Step 2: Run to verify failure**

Run: `bash dark-factory/tests/test_entrypoint_fix_main.sh`
Expected: FAIL (`no fix-main intent override`).

- [ ] **Step 3: Add the intent override**

In `entrypoint.sh`, immediately after the `INTENT=${INTENT:-fix}` line (~line 86), add an exact-match override (the INTENT regex would otherwise reduce `"Fix main"` to `fix`):

```sh
case "$ARGUMENTS" in
  "Fix main"|"fix main") INTENT="fix-main" ;;
esac
```

- [ ] **Step 4: Add the route before the smoke gate**

Find the smoke-gate invocation (the block around line 493 that runs the gate for `fix|continue|deconflict|recheck`). Immediately BEFORE it, add:

```sh
if [ "$INTENT" = "fix-main" ]; then
  echo "[fix-main] dispatched main-red auto-fix; repo cloned at ${CLONE_DIR}"
  if [ "${MAIN_RED_AUTOFIX_ENABLED:-false}" != "true" ]; then
    echo "[fix-main] disabled (MAIN_RED_AUTOFIX_ENABLED != true); exiting"
    exit 0
  fi
  python3 "${FACTORY_CORE_CLI:-/opt/dark-factory/scripts/factory_core/cli.py}" main-red-fix --once || true
  exit 0
fi
```

Also ensure the smoke-gate guard does NOT include `fix-main` (it only lists `fix|continue|deconflict|recheck`, and our exact-match override set INTENT to `fix-main`, so the gate guard already won't match — but add a defensive `fix-main` exclusion comment so a future editor doesn't add it).

- [ ] **Step 5: Run both bash checks**

Run: `bash dark-factory/tests/test_entrypoint_fix_main.sh`
Expected: `PASS`.
Also syntax-check: `bash -n dark-factory/entrypoint.sh && echo "entrypoint syntax ok"`
Expected: `entrypoint syntax ok`.

- [ ] **Step 6: Commit**

```bash
git add dark-factory/entrypoint.sh dark-factory/tests/test_entrypoint_fix_main.sh
git commit -m "feat(entrypoint): route 'Fix main' to the main-red fixer before the smoke gate"
```

---

### Task 5: scheduler.sh dispatch + dedupe + throttle

When main is red and the feature is enabled, dispatch `"Fix main"` once per throttle window, deduped on a running fixer container.

**Files:**
- Modify: `dark-factory/scheduler.sh`
- Create: `dark-factory/tests/test_scheduler_main_red_fixer.sh`

- [ ] **Step 1: Write the grep test**

Create `dark-factory/tests/test_scheduler_main_red_fixer.sh`:

```bash
#!/usr/bin/env bash
# Verifies scheduler.sh dispatches a main-red fixer, gated by enable + dedupe + throttle,
# only inside the MAIN_IS_RED block.
# Run: bash dark-factory/tests/test_scheduler_main_red_fixer.sh
set -euo pipefail
sched="$(cd "$(dirname "$0")" && pwd)/../scheduler.sh"

grep -q 'MAIN_RED_AUTOFIX_ENABLED' "$sched" \
  || { echo "FAIL: no MAIN_RED_AUTOFIX_ENABLED kill-switch"; exit 1; }
grep -q 'is_fixer_running' "$sched" \
  || { echo "FAIL: no is_fixer_running dedupe helper"; exit 1; }
grep -qE 'dispatch "Fix main"' "$sched" \
  || { echo "FAIL: scheduler never dispatches 'Fix main'"; exit 1; }

# The fixer dispatch must live inside the MAIN_IS_RED block (after the recheck call).
block="$(awk '/Read main-is-red sentinel/{f=1} f{print} f&&/^fi$/{exit}' "$sched")"
echo "$block" | grep -q 'main_red_fixer_check' \
  || { echo "FAIL: main_red_fixer_check not called in the MAIN_IS_RED block"; exit 1; }

echo "PASS"
```

- [ ] **Step 2: Run to verify failure**

Run: `bash dark-factory/tests/test_scheduler_main_red_fixer.sh`
Expected: FAIL (`no MAIN_RED_AUTOFIX_ENABLED kill-switch`).

- [ ] **Step 3: Add config exports**

In `scheduler.sh`'s `read_config` (after the `_set_cfg EPIC_AUTOPILOT_*` lines, ~line 84), add:

```sh
  _set_cfg MAIN_RED_AUTOFIX_ENABLED        '.main_red_autofix.enabled'
  _set_cfg MAIN_RED_AUTOFIX_MODEL          '.main_red_autofix.model'
  _set_cfg MAIN_RED_AUTOFIX_MAX_ATTEMPTS   '.main_red_autofix.max_attempts'
  _set_cfg MAIN_RED_AUTOFIX_THROTTLE_MIN   '.main_red_autofix.throttle_minutes'
```

- [ ] **Step 4: Add dedupe + throttle + dispatch helpers**

Near the `is_recheck_running`/`recheck_due`/`main_red_recheck_check` helpers (~line 176-206), add:

```sh
FIXER_STAMP_FILE="${SCHEDULER_STATE_DIR}/main-red-fixer-last-run"

is_fixer_running() {
  docker ps --no-trunc --format '{{.Command}}' 2>/dev/null | grep -q 'Fix main' && return 0
  return 1
}

fixer_due() {
  [ -f "$FIXER_STAMP_FILE" ] || return 0
  local last now
  last=$(stat -c %Y "$FIXER_STAMP_FILE" 2>/dev/null || echo 0)
  now=$(date +%s)
  [ $(( now - last )) -ge $(( ${MAIN_RED_AUTOFIX_THROTTLE_MIN:-15} * 60 )) ]
}

main_red_fixer_check() {
  [ "${MAIN_RED_AUTOFIX_ENABLED:-false}" = "true" ] || return 0
  is_fixer_running && return 0
  fixer_due || return 0
  if dispatch "Fix main"; then
    DISPATCHED="Fix main"
    touch "$FIXER_STAMP_FILE"
    echo "[$(date -u +%FT%TZ)] main_red_fixer=dispatched"
  fi
}
```

- [ ] **Step 5: Call it in the MAIN_IS_RED block**

In the `if [ "$MAIN_IS_RED" = "true" ]; then` block (~line 869), add `main_red_fixer_check` right after the existing `main_red_recheck_check`:

```sh
if [ "$MAIN_IS_RED" = "true" ]; then
  echo "[$(date -u +%FT%TZ)] main_red_gate=active action=skip_implement_dispatch"
  main_red_recheck_check
  main_red_fixer_check
fi
```

- [ ] **Step 6: Run the scheduler bash tests**

Run: `bash dark-factory/tests/test_scheduler_main_red_fixer.sh && bash dark-factory/tests/test_scheduler_ceiling.sh && bash dark-factory/tests/test_scheduler_autopilot_guard.sh`
Expected: all `PASS` (the existing two must remain green).
Also: `bash -n dark-factory/scheduler.sh && echo "scheduler syntax ok"`.

- [ ] **Step 7: Commit**

```bash
git add dark-factory/scheduler.sh dark-factory/tests/test_scheduler_main_red_fixer.sh
git commit -m "feat(scheduler): dispatch main-red fixer (enable+dedupe+throttle) in the red block"
```

---

### Task 6: config.yaml knobs

**Files:**
- Modify: `.claude/skills/refinement/config.yaml`

- [ ] **Step 1: Add the section**

Add a top-level `main_red_autofix:` section (sibling of `epic_autopilot:` / `dispatch_ceiling:`):

```yaml
main_red_autofix:
  enabled: false              # kill-switch — ships OFF. env MAIN_RED_AUTOFIX_ENABLED
  model: claude-opus-4-8      # fix-agent model. env MAIN_RED_AUTOFIX_MODEL
  max_attempts: 3             # fix→CI cycles per red event. env MAIN_RED_AUTOFIX_MAX_ATTEMPTS
  throttle_minutes: 15        # min minutes between fixer dispatches. env MAIN_RED_AUTOFIX_THROTTLE_MIN
  ci_wait_minutes: 20         # bounded wait for branch CI. env MAIN_RED_AUTOFIX_CI_WAIT_MINUTES
```

- [ ] **Step 2: Verify the YAML parses**

Run:
```
MSYS_NO_PATHCONV=1 docker run --rm -v /c/git/trading/MarketHawk:/repo -w /repo python:3.11-slim sh -c "pip install -q pyyaml >/dev/null 2>&1 && python -c \"import yaml; d=yaml.safe_load(open('.claude/skills/refinement/config.yaml')); print(sorted(d['main_red_autofix'].keys()))\""
```
Expected: `['ci_wait_minutes', 'enabled', 'max_attempts', 'model', 'throttle_minutes']`.

- [ ] **Step 3: Commit**

```bash
git add .claude/skills/refinement/config.yaml
git commit -m "feat(config): main_red_autofix knobs (ships OFF)"
```

---

### Task 7: Deploy + manual validation

Operational gate — not a code task.

- [ ] **Step 1: Full test sweep**

Run:
```
MSYS_NO_PATHCONV=1 docker run --rm -v /c/git/trading/MarketHawk:/repo -w /repo/dark-factory mh-pytest python -m pytest tests/test_main_red_fixer.py -q
bash dark-factory/tests/test_entrypoint_fix_main.sh
bash dark-factory/tests/test_scheduler_main_red_fixer.sh
bash dark-factory/tests/test_scheduler_ceiling.sh
bash dark-factory/tests/test_scheduler_autopilot_guard.sh
```
Expected: all green / PASS.

- [ ] **Step 2: Rebuild + recreate the baked scheduler**

```bash
docker compose build backlog-scheduler
docker compose up -d --force-recreate backlog-scheduler
```

- [ ] **Step 3: Staging drill — app-code break**

With `MAIN_RED_AUTOFIX_ENABLED=true`, introduce a deliberate tsc/import break on a throwaway main (staging), let the smoke gate trip, and confirm: a `Fix main` container is dispatched (`docker ps` shows it), it reproduces the failure, opens a ready PR, the PR CI goes green, it merges, the sentinel clears, the regression ticket closes, and a "recovered" notification arrives. Confirm `main-red-fixer-state.json` recorded one attempt.

- [ ] **Step 4: Staging drill — protected-zone cause**

Induce a red whose only fix is in `dark-factory/scheduler.sh` (protected). Confirm the fixer escalates immediately (comment + warning notification), opens NO PR, and does not merge.

- [ ] **Step 5: Staging drill — attempt cap**

Force `max_attempts` failures (e.g. CI stays red). Confirm escalation after the cap, the last PR is left open, and no further fixer dispatches occur until a new red event (new regression issue number).

- [ ] **Step 6: Push + open the PR**

```bash
git push -u origin <branch>
gh pr create --repo omniscient/markethawk --base main \
  --title "feat(main-red-fix): autonomous pipeline recovery — closes #591" \
  --body "Implements docs/superpowers/specs/2026-06-21-main-red-autofix-design.md. Ships OFF. Closes #591."
```

---

## Self-Review

**Spec coverage:**
- Trigger (red-only, top-of-loop, dedupe, throttle, ships OFF) → Task 5. ✅
- Diagnosis by reproduction (ticket has no detail) → Task 3 `reproduce()` + Task 2 `run_once`. ✅
- Scope envelope (allowed/blocked, fail-closed, protected → escalate) → Task 1 `classify_scope`, Task 2 enforcement. ✅
- Fix loop: branch → claude -p agent → verify-scope → ready PR → wait-CI-green → merge → existing recheck clears sentinel → Tasks 2-3. ✅
- Attempt cap + escalate, never-merge-red → Task 1/2 (`should_escalate`, `ci_status`, `fixing`/`escalated`). ✅
- Notifications (recovered/escalation) via `/api/v1/alerts/system` → Task 3 `notify`/`escalate`. ✅
- Separate kill-switch + config → Tasks 5-6. ✅
- Dispatched-container route (not inline) + intent disambiguation + before-smoke-gate → Task 4. ✅
- Validation (unit, scheduler/entrypoint grep, manual drills) → Tasks 1-2 (unit), 4-5 (grep), 7 (manual). ✅

**Spec deltas surfaced during planning (incorporated, flag for the spec):**
1. Regression ticket has no failure text → diagnosis is reproduction-first (spec said "read the regression ticket"; the ticket only gives the issue number/linkage).
2. `"Fix main"` collides with `INTENT=fix` → explicit exact-match override in entrypoint (Task 4).
3. `claude -p` is not an existing code-editing pattern (factory edits via Archon); this plan uses headless `claude -p --allowedTools Edit,…` constrained to the clone, with the produced diff verified against the scope envelope after the fact (defense: the agent has broad tool access, so the post-hoc `classify_scope` check is the real guard, not the prompt).
4. No CI-poll loop exists → `LiveIO.poll_ci` implements a bounded sleep-poll inside the container.

**Placeholder scan:** No TBD/TODO; every code step has complete code. The only environment-specific value is `FACTORY_CORE_CLI` inside the container (Task 4 uses `${FACTORY_CORE_CLI:-/opt/dark-factory/scripts/factory_core/cli.py}`); confirm the baked path during Task 7.

**Type consistency:** `classify_scope(changed_paths, allowed, blocked)`, `ci_status(checks)`, `attempts_for(state, issue)`, `record_attempt(state, issue)`, `should_escalate(attempts, cap, scope)`, `build_fix_prompt(failure, allowed, blocked)`, `run_once(cfg, io, state)` — the `io` method set used in `run_once` (Task 2) matches the `LiveIO` methods (Task 3) exactly. Outcome strings `noop|escalated|merged|fixing` are internal only (the scheduler matches on the printed `main_red_fixer=<outcome>` but does not branch on the value, since the dispatch itself already set `DISPATCHED`).
