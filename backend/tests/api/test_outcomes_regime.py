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
