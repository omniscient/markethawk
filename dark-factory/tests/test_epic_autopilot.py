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


def test_undeclared_scope_is_soft_and_flags():
    cand = c(target_paths=[])
    ex, why = ap.hard_excluded(cand, ["app/core/auth"])
    assert not ex and why == "undeclared-scope"
    assert cand.get("scope_undeclared") is True


def test_sensitive_keyword_hard_drops_even_without_paths():
    cand = c(title="Live IBKR order path kill switch", body="", target_paths=[])
    ex, why = ap.hard_excluded(cand, ["app/core/auth"],
                               sensitive_keywords=r"trading|ibkr|order|jwt|/auth")
    assert ex and why == "sensitive-keyword"


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


# ── Task 4: daily cap + verdict cache ───────────────────────────────────────

def test_daily_cap_counts_and_resets():
    st = {}
    assert ap.daily_remaining(st, 5, "2026-06-20") == 5
    ap.record_advance(st, "2026-06-20")
    ap.record_advance(st, "2026-06-20")
    assert ap.daily_remaining(st, 5, "2026-06-20") == 3
    # next UTC day resets the counter
    assert ap.daily_remaining(st, 5, "2026-06-21") == 5


def test_verdict_cache_roundtrip_and_hash_invalidation():
    st = {}
    h1 = ap.spec_hash("spec A")
    assert ap.cached_verdict(st, 402, h1) is None
    ap.record_verdict(st, 402, h1, "HOLD")
    assert ap.cached_verdict(st, 402, h1) == "HOLD"
    # regenerated spec → different hash → cache miss (re-review)
    assert ap.cached_verdict(st, 402, ap.spec_hash("spec A v2")) is None


# ── Task 5: orchestrator with injected IO ───────────────────────────────────

class FakeIO:
    def __init__(self, candidates, review_text):
        self._cands = candidates
        self._review = review_text
        self.advanced = []
        self.comments = []
        self.notes = []

    def fetch_candidates(self):
        return self._cands

    def review(self, prompt, model):
        return self._review

    def advance(self, issue):
        self.advanced.append(issue)

    def comment(self, issue, body):
        self.comments.append((issue, body))

    def notify(self, title, body, severity, dedupe_key):
        self.notes.append((severity, dedupe_key))


CFG = dict(exclude_paths=["app/core/auth", "dark-factory/"], opt_out_label="no-autopilot",
           ceiling_keywords=CEIL, confidence_floor=0.7, daily_cap=5, model="claude-opus-4-8")


def test_run_advances_low_risk():
    io = FakeIO([c(number=402)], '{"decision":"ADVANCE","risk":"low","confidence":0.9,"reasons":["safe"],"concerns":[]}')
    st = {}
    out = ap.run_once(CFG, io, st, "2026-06-20")
    assert out["outcome"] == "advanced" and out["issue"] == 402
    assert io.advanced == [402]
    assert any(sev == "info" for sev, _ in io.notes)          # advance notice
    assert ap.daily_remaining(st, 5, "2026-06-20") == 4


def test_run_holds_medium_risk():
    io = FakeIO([c(number=402)], '{"decision":"ADVANCE","risk":"medium","confidence":0.9,"reasons":[],"concerns":["risky"]}')
    st = {}
    out = ap.run_once(CFG, io, st, "2026-06-20")
    assert out["outcome"] == "hold" and io.advanced == []
    assert ap.cached_verdict(st, 402, ap.spec_hash(c(number=402)["spec_text"])) == "HOLD"


def test_run_no_candidates_notifies_stuck():
    io = FakeIO([c(number=402, labels=["no-autopilot", "ready-for-agent"])], "x")
    out = ap.run_once(CFG, io, {}, "2026-06-20")
    assert out["outcome"] == "no_candidates"
    assert any(sev == "warning" and key == "autopilot-stuck" for sev, key in io.notes)


def test_run_daily_cap_reached_notifies():
    io = FakeIO([c(number=402)], "x")
    st = {"daily": {"date": "2026-06-20", "count": 5}}
    out = ap.run_once(CFG, io, st, "2026-06-20")
    assert out["outcome"] == "daily_cap_reached"
    assert io.advanced == []
    assert any(key == "autopilot-cap" for _, key in io.notes)


def test_run_skips_cached_hold():
    cand = c(number=402)
    st = {}
    ap.record_verdict(st, 402, ap.spec_hash(cand["spec_text"]), "HOLD")
    io = FakeIO([cand], '{"decision":"ADVANCE","risk":"low","confidence":0.9}')
    out = ap.run_once(CFG, io, st, "2026-06-20")
    assert out["outcome"] == "no_candidates"   # only candidate is cache-suppressed
    assert io.advanced == []
