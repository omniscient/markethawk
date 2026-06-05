import json
import re
from pathlib import Path

import scripts.render_report as render_report
from scripts.render_report import render

FIXTURES = Path(__file__).parent / "fixtures"
TEMPLATE = Path(__file__).parent.parent.parent / "scripts" / "template.html"
STUB_ECHARTS = (
    "var echarts={init:function(){return {setOption:function(){},"
    "resize:function(){}};},graphic:{LinearGradient:function(){}}}"
)

SAMPLE_METRICS = {
    "generated_at": "2026-06-04T18:00:00Z",
    "summary": {
        "total_issues": 3, "closed_issues": 2, "open_issues": 1,
        "autonomous_issues": 1, "pct_autonomous": 33.3,
        "total_cost_usd": 2.50, "avg_cost_per_ticket": 2.50,
        "median_lead_time_hours": 2.5, "p85_lead_time_hours": 54.0,
    },
    "issues": [],
    "cost_by_step": {"plan": 1.25, "implement": 1.25},
}


def _write_metrics(tmp_path):
    metrics_path = tmp_path / "metrics.json"
    metrics_path.write_text(json.dumps(SAMPLE_METRICS))
    return metrics_path


def test_render_produces_html(tmp_path, monkeypatch):
    monkeypatch.setattr(render_report, "_get_echarts_js", lambda: STUB_ECHARTS)
    metrics_path = _write_metrics(tmp_path)
    output_path = tmp_path / "report.html"
    render(str(metrics_path), str(TEMPLATE), str(output_path))
    assert output_path.exists()
    html = output_path.read_text(encoding="utf-8")
    assert html.startswith("<!DOCTYPE html")


def test_render_embeds_metrics(tmp_path, monkeypatch):
    monkeypatch.setattr(render_report, "_get_echarts_js", lambda: STUB_ECHARTS)
    metrics_path = _write_metrics(tmp_path)
    output_path = tmp_path / "report.html"
    render(str(metrics_path), str(TEMPLATE), str(output_path))
    html = output_path.read_text(encoding="utf-8")
    assert "window.__METRICS__" in html
    assert '"total_issues": 3' in html


def test_render_no_external_scripts(tmp_path, monkeypatch):
    monkeypatch.setattr(render_report, "_get_echarts_js", lambda: STUB_ECHARTS)
    metrics_path = _write_metrics(tmp_path)
    output_path = tmp_path / "report.html"
    render(str(metrics_path), str(TEMPLATE), str(output_path))
    html = output_path.read_text(encoding="utf-8")
    external = re.findall(r'src=["\']https?://', html)
    assert external == [], f"External script references found: {external}"


def test_render_no_placeholder_leakage(tmp_path, monkeypatch):
    monkeypatch.setattr(render_report, "_get_echarts_js", lambda: STUB_ECHARTS)
    metrics_path = _write_metrics(tmp_path)
    output_path = tmp_path / "report.html"
    render(str(metrics_path), str(TEMPLATE), str(output_path))
    html = output_path.read_text(encoding="utf-8")
    assert "{{ECHARTS_JS}}" not in html
    assert "{{METRICS_JSON}}" not in html
