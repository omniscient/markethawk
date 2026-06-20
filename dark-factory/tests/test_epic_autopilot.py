import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
from factory_core import epic_autopilot as ap  # noqa: E402

CEIL = "migration|migrate|performance|perf|architectur|refactor"


def c(**kw):
    base = dict(
        number=1, title="t", body="b", labels=["ready-for-agent"], size="S",
        status="spec-pending-review", spec_text="touches backend/app/services/foo.py",
        target_paths=["backend/app/services/foo.py"],
    )
    base.update(kw)
    return base


# ── Task 2: eligibility + hard-rule exclusions ──────────────────────────────

def test_eligible_happy():
    ok, why = ap.is_eligible(c(), "no-autopilot", CEIL)
    assert ok, why


def test_ineligible_opt_out():
    ok, _ = ap.is_eligible(c(labels=["ready-for-agent", "no-autopilot"]), "no-autopilot", CEIL)
    assert not ok


def test_ineligible_already_direct_to_pr():
    ok, _ = ap.is_eligible(c(labels=["direct-to-pr"]), "no-autopilot", CEIL)
    assert not ok


def test_ineligible_wrong_status():
    ok, _ = ap.is_eligible(c(status="Ready"), "no-autopilot", CEIL)
    assert not ok


def test_ineligible_above_ceiling_size_l():
    ok, _ = ap.is_eligible(c(size="L"), "no-autopilot", CEIL)
    assert not ok


def test_ineligible_m_with_ceiling_keyword():
    ok, _ = ap.is_eligible(c(size="M", title="perf refactor of scanner"), "no-autopilot", CEIL)
    assert not ok


def test_eligible_m_without_keyword():
    ok, why = ap.is_eligible(c(size="M", title="add data quality preflight"), "no-autopilot", CEIL)
    assert ok, why


def test_size_from_label_prefix():
    # size carried as a label "size: L" rather than the size field
    ok, _ = ap.is_eligible(c(size=None, labels=["ready-for-agent", "size: L"]), "no-autopilot", CEIL)
    assert not ok


def test_extract_paths():
    paths = ap.extract_target_paths("Modifies `backend/app/services/x.py` and dark-factory/seed/y.sql")
    assert "backend/app/services/x.py" in paths
    assert "dark-factory/seed/y.sql" in paths


def test_hard_exclude_factory_self():
    ex, why = ap.hard_excluded(c(target_paths=["dark-factory/scheduler.sh"]),
                               ["dark-factory/", "app/core/auth"])
    assert ex and "dark-factory/" in why


def test_hard_exclude_auth():
    ex, _ = ap.hard_excluded(c(target_paths=["backend/app/core/auth/jwt.py"]),
                             ["app/core/auth"])
    assert ex


def test_hard_exclude_undeclared_scope_fails_closed():
    ex, why = ap.hard_excluded(c(target_paths=[]), ["app/core/auth"])
    assert ex and why == "undeclared-scope"


def test_security_label_not_excluded():
    ex, _ = ap.hard_excluded(
        c(labels=["security", "ready-for-agent"], target_paths=["backend/app/services/redaction.py"]),
        ["app/core/auth", "app/services/trading"])
    assert not ex


# ── Task 3: verdict parsing + decision rule ─────────────────────────────────

def test_parse_clean_json():
    v = ap.parse_verdict('{"decision":"ADVANCE","risk":"low","confidence":0.9,"reasons":["ok"],"concerns":[]}')
    assert v["decision"] == "ADVANCE" and v["confidence"] == 0.9


def test_parse_json_in_fence():
    v = ap.parse_verdict('blah\n```json\n{"decision":"HOLD","risk":"medium","confidence":0.5,"reasons":[],"concerns":["x"]}\n```\n')
    assert v["decision"] == "HOLD"


def test_parse_garbage_fails_closed():
    v = ap.parse_verdict("the model rambled with no json")
    assert v["decision"] == "HOLD" and v["risk"] == "high"


def test_parse_empty_fails_closed():
    assert ap.parse_verdict("")["decision"] == "HOLD"


def test_parse_bad_decision_value_fails_closed():
    assert ap.parse_verdict('{"decision":"MAYBE","risk":"low","confidence":1.0}')["decision"] == "HOLD"


def test_should_advance_only_on_low_and_floor():
    assert ap.should_advance({"decision": "ADVANCE", "risk": "low", "confidence": 0.8}, 0.7)
    assert not ap.should_advance({"decision": "ADVANCE", "risk": "medium", "confidence": 0.9}, 0.7)
    assert not ap.should_advance({"decision": "ADVANCE", "risk": "low", "confidence": 0.6}, 0.7)
    assert not ap.should_advance({"decision": "HOLD", "risk": "low", "confidence": 0.99}, 0.7)
