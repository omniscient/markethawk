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
