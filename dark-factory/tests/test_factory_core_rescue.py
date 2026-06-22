import json
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from factory_core import rescue


def _cp(stdout="", code=0):
    return subprocess.CompletedProcess([], code, stdout=stdout, stderr="")


def _fake_gh(pr=None, checks=None, *, record=None):
    """Build a subprocess.run replacement routing by the gh subcommand in cmd.

    pr     -> the object returned by `gh pr list ... --json number,isDraft,mergeable`
              (wrapped in a one-element array), or None for "no PR".
    checks -> list of bucket strings returned by `gh pr checks ... --json bucket`.
    record -> optional list that every cmd is appended to (for asserting side effects).
    """
    checks = checks or []

    def run(cmd, **kw):
        if record is not None:
            record.append(cmd)
        joined = " ".join(cmd)
        if "pr" in cmd and "list" in cmd:
            return _cp(json.dumps([pr] if pr else []))
        if "pr" in cmd and "checks" in cmd:
            code = 0 if all(b == "pass" for b in checks) else 1
            return _cp(json.dumps([{"bucket": b} for b in checks]), code)
        if "pr" in cmd and "ready" in cmd:
            return _cp()
        if "item-list" in joined:
            return _cp(json.dumps({"items": [
                {"id": "ITEM", "content": {"number": 7, "type": "Issue"}}]}))
        # item-edit, gh api comments lookup, gh issue comment, anything else
        if "--jq" in cmd:           # comment-id lookup -> none exists
            return _cp("")
        return _cp()

    return run


def test_rescue_green_mergeable_promotes(monkeypatch):
    calls = []
    monkeypatch.setattr(subprocess, "run", _fake_gh(
        pr={"number": 7, "isDraft": False, "mergeable": "MERGEABLE"},
        checks=["pass", "pass", "skipping"], record=calls))
    assert rescue.rescue_blocked(7) == "rescued"
    # moved to In review
    edits = [c for c in calls if "item-edit" in " ".join(c)]
    assert edits and rescue.board.STATUS_IN_REVIEW in edits[0]
    # posted the rescue comment
    assert any("comment" in " ".join(c) for c in calls)


def test_rescue_marks_draft_ready_first(monkeypatch):
    calls = []
    monkeypatch.setattr(subprocess, "run", _fake_gh(
        pr={"number": 7, "isDraft": True, "mergeable": "MERGEABLE"},
        checks=["pass"], record=calls))
    assert rescue.rescue_blocked(7) == "rescued"
    assert any("pr" in c and "ready" in c for c in calls)


def test_skip_no_pr(monkeypatch):
    monkeypatch.setattr(subprocess, "run", _fake_gh(pr=None))
    assert rescue.rescue_blocked(7) == "skip:no_pr"


def test_skip_no_checks(monkeypatch):
    monkeypatch.setattr(subprocess, "run", _fake_gh(
        pr={"number": 7, "isDraft": False, "mergeable": "MERGEABLE"}, checks=[]))
    assert rescue.rescue_blocked(7) == "skip:no_checks"


def test_skip_failing_ci(monkeypatch):
    monkeypatch.setattr(subprocess, "run", _fake_gh(
        pr={"number": 7, "isDraft": False, "mergeable": "MERGEABLE"},
        checks=["pass", "fail"]))
    assert rescue.rescue_blocked(7) == "skip:failing_ci"


def test_skip_pending_ci(monkeypatch):
    monkeypatch.setattr(subprocess, "run", _fake_gh(
        pr={"number": 7, "isDraft": False, "mergeable": "MERGEABLE"},
        checks=["pass", "pending"]))
    assert rescue.rescue_blocked(7) == "skip:pending_ci"


def test_skip_conflicting(monkeypatch):
    monkeypatch.setattr(subprocess, "run", _fake_gh(
        pr={"number": 7, "isDraft": False, "mergeable": "CONFLICTING"},
        checks=["pass"]))
    assert rescue.rescue_blocked(7) == "skip:mergeable_CONFLICTING"


def test_skip_unknown_mergeable(monkeypatch):
    monkeypatch.setattr(subprocess, "run", _fake_gh(
        pr={"number": 7, "isDraft": False, "mergeable": "UNKNOWN"},
        checks=["pass"]))
    assert rescue.rescue_blocked(7) == "skip:mergeable_UNKNOWN"


def test_failing_ci_does_not_promote(monkeypatch):
    """A red PR must never be moved to In review (board untouched)."""
    calls = []
    monkeypatch.setattr(subprocess, "run", _fake_gh(
        pr={"number": 7, "isDraft": False, "mergeable": "MERGEABLE"},
        checks=["fail"], record=calls))
    rescue.rescue_blocked(7)
    assert not any("item-edit" in " ".join(c) for c in calls)
