"""Smoke tests for token_opt_eval.py — issue #672."""
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
    assert hasattr(mod, "TIER1_SCENARIOS")


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


def test_tier1_scenarios():
    mod = _load_module()
    assert mod.TIER1_SCENARIOS == ["refine", "plan", "implement"]


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
