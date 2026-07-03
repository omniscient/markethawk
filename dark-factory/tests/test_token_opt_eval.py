"""Smoke tests for token_opt_eval.py — issue #672 / #718."""
import glob
import importlib.util
import os
import sys

SCRIPT_PATH = os.path.join(
    os.path.dirname(__file__), "..", "evals", "token_opt_eval.py"
)


def _load_module():
    spec = importlib.util.spec_from_file_location("token_opt_eval", SCRIPT_PATH)
    mod = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(mod)
    except SystemExit:
        pass
    return mod


def test_eval_script_exists():
    assert os.path.exists(SCRIPT_PATH), f"Missing: {SCRIPT_PATH}"


def test_eval_script_importable():
    mod = _load_module()
    assert hasattr(mod, "SAFETY_RULES")
    assert hasattr(mod, "ENFORCEMENT_SCENARIOS")
    assert hasattr(mod, "TIER1_SCENARIOS")


def test_verdict_flags_dropped_required_section_as_regression():
    """The verdict must be driven by section_check (the sliced surface), not just the
    CLAUDE.md-anchored SAFETY_RULES. A component-required ARCHITECTURE.md section that the
    optimized slice dropped ('missing') is a real regression the eval must catch — even when
    every SAFETY_RULES string is present (they live in CLAUDE.md, which is never sliced)."""
    mod = _load_module()
    all_rules_pass = {rule: "pass" for rule in mod.SAFETY_RULES}
    # SAFETY_RULES all pass but a required section was dropped by the slice → REGRESSION.
    assert mod.safety_verdict(all_rules_pass, {"Backend Module Map": "missing"}) == "🔴 REGRESSION"
    # All required sections present → the (passing) rules yield PASS.
    assert mod.safety_verdict(all_rules_pass, {"Backend Module Map": "present"}) == "✅ PASS"


def test_reports_dir_exists():
    reports_dir = os.path.join(
        os.path.dirname(__file__), "..", "evals", "reports"
    )
    assert os.path.isdir(reports_dir), f"Missing dir: {reports_dir}"


def test_safety_rules_nonempty():
    mod = _load_module()
    assert len(mod.SAFETY_RULES) >= 7
    assert "alembic upgrade head" in mod.SAFETY_RULES
    assert "npx tsc --noEmit" in mod.SAFETY_RULES


def test_enforcement_scenarios():
    mod = _load_module()
    assert mod.ENFORCEMENT_SCENARIOS == ["refine", "plan", "implement", "conformance", "code-review"]


def test_tier1_scenarios_alias():
    """TIER1_SCENARIOS must remain as backward-compat alias pointing to ENFORCEMENT_SCENARIOS."""
    mod = _load_module()
    assert mod.TIER1_SCENARIOS is mod.ENFORCEMENT_SCENARIOS


def test_scorecard_report_committed():
    reports_dir = os.path.join(
        os.path.dirname(__file__), "..", "evals", "reports"
    )
    scorecards = glob.glob(os.path.join(reports_dir, "token-opt-scorecard-*.md"))
    assert scorecards, f"No scorecard reports found in {reports_dir}"


def test_scorecard_has_required_sections():
    reports_dir = os.path.join(
        os.path.dirname(__file__), "..", "evals", "reports"
    )
    scorecards = sorted(glob.glob(os.path.join(reports_dir, "token-opt-scorecard-*.md")))
    with open(scorecards[-1], encoding="utf-8") as f:
        text = f.read()
    assert "Per-Issue Savings" in text
    assert "Safety Check Details" in text
    assert "Section Coverage" in text
    assert "Recommendations" in text


def test_simulate_enforcement_without_budget_enforce():
    """simulate_enforcement must return calibration_error row when budget_enforce unavailable."""
    mod = _load_module()
    orig = mod._BUDGET_ENFORCE_AVAILABLE
    mod._BUDGET_ENFORCE_AVAILABLE = False
    try:
        result = {
            "issue": 999,
            "scenario": "implement",
            "opt_tokens": 25000,
            "fallback": True,
            "opt_manifest": {"sections": {}},
            "section_check": {},
        }
        row = mod.simulate_enforcement(result, budget=30000, config={})
        assert row["status"] == "calibration_error"
        assert row["issue"] == 999
        assert row["scenario"] == "implement"
        assert row["budget"] == 30000
    finally:
        mod._BUDGET_ENFORCE_AVAILABLE = orig


def test_safe_budget_recommendation_qualifies():
    """safe_budget_recommendation returns lowest budget where both gates pass."""
    mod = _load_module()
    # All rows at 30000: no over_budget, no section_at_risk
    rows = [
        {"budget": 28000, "over_budget": True, "section_at_risk": False},
        {"budget": 28000, "over_budget": True, "section_at_risk": False},
        {"budget": 30000, "over_budget": False, "section_at_risk": False},
        {"budget": 30000, "over_budget": False, "section_at_risk": False},
    ]
    rec = mod.safe_budget_recommendation(rows, [28000, 30000])
    assert rec == "30000"


def test_safe_budget_recommendation_none():
    """safe_budget_recommendation returns 'none — widen --budgets' when no budget qualifies."""
    mod = _load_module()
    rows = [
        {"budget": 30000, "over_budget": False, "section_at_risk": True},
    ]
    rec = mod.safe_budget_recommendation(rows, [30000])
    assert rec == "none — widen --budgets"


def test_safe_budget_recommendation_over_budget_threshold():
    """over_budget_rate > 10% disqualifies a candidate."""
    mod = _load_module()
    # 2 out of 10 rows over_budget at 30k = 20% > 10% threshold → disqualified
    rows = []
    for i in range(10):
        rows.append({"budget": 30000, "over_budget": i < 2, "section_at_risk": False})
    rec = mod.safe_budget_recommendation(rows, [30000])
    assert rec == "none — widen --budgets"


def test_build_budget_sweep_includes_config_default():
    """_build_budget_sweep always includes config default_budget_tokens."""
    mod = _load_module()
    sweep = mod._build_budget_sweep(None, "/workspace/markethawk")
    assert 30000 in sweep  # config default


def test_build_budget_sweep_override():
    """_build_budget_sweep uses provided list + adds config default."""
    mod = _load_module()
    sweep = mod._build_budget_sweep([22000, 24000], "/workspace/markethawk")
    assert 22000 in sweep
    assert 24000 in sweep
    assert 30000 in sweep  # config default always included


def test_percentile_basic():
    mod = _load_module()
    vals = [10.0, 20.0, 30.0, 40.0, 50.0]
    assert mod._percentile(vals, 50) == 30.0
    assert mod._percentile([], 50) == 0.0


def test_calibrate_issue_returns_per_budget_rows():
    """calibrate_issue returns one row per budget in the sweep."""
    mod = _load_module()
    orig = mod._BUDGET_ENFORCE_AVAILABLE
    mod._BUDGET_ENFORCE_AVAILABLE = False
    try:
        result = {
            "issue": 100,
            "scenario": "refine",
            "opt_tokens": 20000,
            "fallback": True,
            "opt_manifest": {"sections": {}},
            "section_check": {},
        }
        rows = mod.calibrate_issue(result, [22000, 30000], {})
        assert len(rows) == 2
        budgets = {r["budget"] for r in rows}
        assert budgets == {22000, 30000}
    finally:
        mod._BUDGET_ENFORCE_AVAILABLE = orig


def test_opt_manifest_in_eval_result_shape():
    """eval_issue_scenario return dict must include opt_manifest key."""
    # This is a structural test on the return shape contract — not a live assembly call.
    import inspect
    mod = _load_module()
    src = inspect.getsource(mod.eval_issue_scenario)
    assert '"opt_manifest"' in src or "'opt_manifest'" in src
