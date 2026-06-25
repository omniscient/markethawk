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
