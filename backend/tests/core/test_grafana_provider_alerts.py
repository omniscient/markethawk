"""#388: Grafana provisioning references the provider-health metrics."""

import json
import os

import pytest
import yaml

_REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
_RULES = os.path.join(_REPO_ROOT, "grafana/provisioning/alerting/rules.yaml")
_DASH = os.path.join(_REPO_ROOT, "grafana/provisioning/dashboards")

pytestmark = pytest.mark.skipif(
    not os.path.exists(_RULES), reason="grafana provisioning not accessible"
)


def _rules():
    with open(_RULES) as f:
        doc = yaml.safe_load(f)
    return {r["uid"]: r for g in doc["groups"] for r in g["rules"]}


def _exprs(rule):
    return " ".join(d["model"].get("expr", "") for d in rule["data"])


def test_polygon_provider_degraded_rule():
    rule = _rules()["polygon-provider-degraded"]
    assert rule["labels"]["severity"] == "critical"
    assert rule["for"] == "2m"
    exprs = _exprs(rule)
    for metric in (
        "provider_circuit_breaker_state",
        "provider_error_rate",
        "polygon_ws_connected",
    ):
        assert metric in exprs


def test_polygon_latency_rule_is_warning_only():
    rule = _rules()["polygon-latency-elevated"]
    assert rule["labels"]["severity"] == "warning"
    assert "provider_request_latency_p95_seconds" in _exprs(rule)


def test_pre_market_provider_gap_rule():
    rule = _rules()["pre-market-scan-provider-gap"]
    assert rule["labels"]["severity"] == "critical"
    assert "scan_provider_gap_severity" in _exprs(rule)


@pytest.mark.parametrize("name", ["infrastructure.json", "scanner-performance.json"])
def test_dashboards_have_provider_panels(name):
    with open(os.path.join(_DASH, name)) as f:
        dash = json.load(f)
    exprs = " ".join(
        t.get("expr", "") for p in dash["panels"] for t in p.get("targets", [])
    )
    assert "provider_error_rate" in exprs
    assert "provider_circuit_breaker_state" in exprs
    ids = [p["id"] for p in dash["panels"]]
    assert len(ids) == len(set(ids))
