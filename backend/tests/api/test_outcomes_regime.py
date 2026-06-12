"""Integration tests for regime-related outcomes endpoints."""

from fastapi.testclient import TestClient

from app.main import app
from app.schemas.regime import RegimeBreakdownResponse, RegimeSliceSchema

client = TestClient(app)


def test_regime_slice_schema_fields():
    s = RegimeSliceSchema(
        sample_size=10, win_rate_pct=60.0, avg_mfe_pct=2.1, avg_mae_pct=1.2
    )
    assert s.sample_size == 10
    assert s.win_rate_pct == 60.0


def test_regime_breakdown_response_structure():
    resp = RegimeBreakdownResponse(
        scanner_type="pre_market_volume_spike",
        total_events=100,
        breakdown={
            "risk_on": RegimeSliceSchema(
                sample_size=60, win_rate_pct=65.0, avg_mfe_pct=3.0, avg_mae_pct=1.0
            )
        },
    )
    assert resp.total_events == 100
    assert "risk_on" in resp.breakdown


# ── T14: StatsService regime filter + breakdown ───────────────────────────────


def test_get_scorecard_accepts_regime_filter(db):
    from app.services.stats import StatsService

    result = StatsService.get_scorecard(db, "pre_market_volume_spike", regime="risk_on")
    assert "scanner_type" in result
    assert result["scanner_type"] == "pre_market_volume_spike"


def test_get_regime_breakdown_returns_expected_shape(db):
    from app.services.stats import StatsService

    result = StatsService.get_regime_breakdown(db, "pre_market_volume_spike")
    assert result["scanner_type"] == "pre_market_volume_spike"
    assert "total_events" in result
    assert "breakdown" in result
    assert isinstance(result["breakdown"], dict)


def test_get_regime_breakdown_empty_db_has_no_breakdown(db):
    from app.services.stats import StatsService

    result = StatsService.get_regime_breakdown(db, "pre_market_volume_spike")
    assert result["total_events"] == 0
    assert result["breakdown"] == {}


# ── T15: Outcomes router endpoints ────────────────────────────────────────────


def test_scorecard_endpoint_accepts_regime_param(db):
    resp = client.get(
        "/api/v1/outcomes/scorecard/pre_market_volume_spike?regime=risk_on"
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["scanner_type"] == "pre_market_volume_spike"


def test_regime_breakdown_endpoint_shape(db):
    resp = client.get("/api/v1/outcomes/regime-breakdown/pre_market_volume_spike")
    assert resp.status_code == 200
    data = resp.json()
    assert data["scanner_type"] == "pre_market_volume_spike"
    assert "total_events" in data
    assert "breakdown" in data


def test_regime_breakdown_empty_returns_empty_breakdown(db):
    resp = client.get("/api/v1/outcomes/regime-breakdown/pre_market_volume_spike")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total_events"] == 0
    assert data["breakdown"] == {}
