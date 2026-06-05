import json
from pathlib import Path

from scripts.fetch_metrics import (
    build_issue_metrics,
    parse_cost_comment,
    parse_run_headers,
    parse_step_table,
)

FIXTURES = Path(__file__).parent / "fixtures"


# ── Task 1: cost-report parsing ────────────────────────────────────────────────
def test_parse_cost_comment_extracts_totals(cost_comment):
    result = parse_cost_comment(cost_comment)
    assert result is not None
    assert abs(result["cost"] - 7.197) < 0.001
    assert result["in_tokens"] == 310
    assert result["out_tokens"] == 123906


def test_parse_cost_comment_returns_none_when_absent():
    assert parse_cost_comment("just a regular comment") is None


def test_parse_run_headers_extracts_all_runs(cost_comment):
    runs = parse_run_headers(cost_comment)
    assert len(runs) == 3
    assert runs[0]["run_type"] == "plan"
    assert runs[0]["status"] == "completed"
    assert runs[0]["timestamp"] == "2026-06-04 12:42 UTC"
    assert runs[2]["run_type"] == "fix"


def test_parse_step_table_extracts_steps(cost_comment):
    runs = parse_run_headers(cost_comment)
    steps = parse_step_table(cost_comment, run_index=0)
    non_subtotal = [s for s in steps if s["step"] != "Subtotal"]
    assert len(non_subtotal) == 3
    plan_step = next(s for s in non_subtotal if s["step"] == "plan")
    assert plan_step["in_tokens"] == 38
    assert abs(plan_step["cost_usd"] - 2.8727) < 0.0001


def test_parse_step_table_aggregates_by_step_name(cost_comment):
    # "implement" appears in run 1 and run 2 — aggregate should sum both
    all_steps = parse_step_table(cost_comment)
    by_name = {s["step"]: s for s in all_steps}
    assert "implement" in by_name
    assert abs(by_name["implement"]["cost_usd"] - (1.9607 + 2.0224)) < 0.001


def test_parse_step_table_handles_k_suffixed_tokens():
    # Real cost reports write token counts like "66.2K"/"39K" — these must parse.
    body = (
        "<!-- dark-factory-cost-report -->\n"
        "### Run: 2026-06-04 18:47 UTC (plan, completed)\n\n"
        "| Step | Model | In tokens | Out tokens | Cost | Duration |\n"
        "|------|-------|-----------|------------|------|----------|\n"
        "| plan |  | 50 | 66.2K | $6.0044 | 30m 53s |\n"
        "| **Subtotal** | | **50** | **66.2K** | **$6.0044** | |\n"
    )
    steps = parse_step_table(body)
    by_name = {s["step"]: s for s in steps}
    assert "plan" in by_name
    assert by_name["plan"]["out_tokens"] == 66200
    assert abs(by_name["plan"]["cost_usd"] - 6.0044) < 0.0001


# ── Task 2: issue metrics ──────────────────────────────────────────────────────
def test_build_issue_metrics_lead_time():
    issues = json.loads((FIXTURES / "sample_issues.json").read_text())
    comments_map = json.loads((FIXTURES / "sample_comments.json").read_text())
    result = build_issue_metrics(issues, comments_map)
    closed = {i["number"]: i for i in result["issues"] if i["state"] == "CLOSED"}
    assert abs(closed[1]["lead_time_hours"] - 2.5) < 0.1
    assert abs(closed[2]["lead_time_hours"] - 54.0) < 0.1


def test_build_issue_metrics_autonomous_flag():
    issues = json.loads((FIXTURES / "sample_issues.json").read_text())
    comments_map = json.loads((FIXTURES / "sample_comments.json").read_text())
    result = build_issue_metrics(issues, comments_map)
    by_num = {i["number"]: i for i in result["issues"]}
    assert by_num[1]["autonomous"] is True
    assert by_num[2]["autonomous"] is False


def test_build_issue_metrics_summary_counts():
    issues = json.loads((FIXTURES / "sample_issues.json").read_text())
    comments_map = json.loads((FIXTURES / "sample_comments.json").read_text())
    result = build_issue_metrics(issues, comments_map)
    s = result["summary"]
    assert s["total_issues"] == 3
    assert s["closed_issues"] == 2
    assert s["open_issues"] == 1
    assert s["autonomous_issues"] == 1
    assert abs(s["total_cost_usd"] - 2.50) < 0.01


def test_build_issue_metrics_label_extraction():
    issues = json.loads((FIXTURES / "sample_issues.json").read_text())
    comments_map = json.loads((FIXTURES / "sample_comments.json").read_text())
    result = build_issue_metrics(issues, comments_map)
    by_num = {i["number"]: i for i in result["issues"]}
    assert by_num[1]["size"] == "S"
    assert by_num[2]["size"] == "M"
    assert by_num[2]["priority"] == "must-have"


def test_build_issue_metrics_factory_cycle_stored():
    # Run-header timestamps are minute precision — factory cycle must compute, not crash.
    issues = json.loads((FIXTURES / "sample_issues.json").read_text())
    comments_map = json.loads((FIXTURES / "sample_comments.json").read_text())
    result = build_issue_metrics(issues, comments_map)
    by_num = {i["number"]: i for i in result["issues"]}
    # issue 1: first run 2026-01-10 09:30 UTC, closed 2026-01-10T11:30:00Z → 2.0h
    assert by_num[1]["factory_cycle_hours"] is not None
    assert abs(by_num[1]["factory_cycle_hours"] - 2.0) < 0.1
    # issue 2 has no cost report → no factory cycle
    assert by_num[2]["factory_cycle_hours"] is None


# ── Task 5: cost by step ───────────────────────────────────────────────────────
def test_build_issue_metrics_cost_by_step():
    issues = json.loads((FIXTURES / "sample_issues.json").read_text())
    comments_map = json.loads((FIXTURES / "sample_comments.json").read_text())
    result = build_issue_metrics(issues, comments_map)
    cbs = result["cost_by_step"]
    assert "plan" in cbs
    assert "implement" in cbs
    assert abs(cbs["plan"] - 1.25) < 0.01


# ── Task 6: weekly timeseries ──────────────────────────────────────────────────
def test_build_issue_metrics_timeseries():
    issues = json.loads((FIXTURES / "sample_issues.json").read_text())
    comments_map = json.loads((FIXTURES / "sample_comments.json").read_text())
    result = build_issue_metrics(issues, comments_map)
    ts = result["timeseries"]["weekly"]
    assert isinstance(ts, list)
    for week in ts:
        assert "week" in week and "created" in week and "closed" in week
