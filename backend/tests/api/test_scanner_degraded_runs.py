"""#388: degraded runs are visible and queryable via the scanner API."""

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.main import app
from app.models.scanner_run import ScannerRun
from tests.fixtures.core import seed_universes

client = TestClient(app)

_LIVE_ISSUE = {
    "code": "provider_gap",
    "severity": "blocker",
    "message": "No pre-market minute bars ingested for 2026-06-02",
    "detail": {
        "subtype": "live_degradation",
        "provider": "polygon",
        "reason": "no_fresh_premarket_bars",
        "worker": "celery:1",
    },
}
_HISTORICAL_ISSUE = {
    "code": "provider_gap",
    "severity": "warning",
    "message": "One or more tickers have provider data gaps",
    "detail": {"subtype": "structural"},
}


def _gate(*issues):
    return {"schema_version": "quality_gate.v1", "issues": list(issues)}


def _seed(db: Session):
    universe = seed_universes(db)[0]
    degraded = ScannerRun(
        scanner_type="pre_market_volume_spike",
        status="completed",
        universe_id=universe.id,
        data_degraded=True,
        quality_gate=_gate(_LIVE_ISSUE, _HISTORICAL_ISSUE),
    )
    clean = ScannerRun(
        scanner_type="pre_market_volume_spike",
        status="completed",
        universe_id=universe.id,
        data_degraded=False,
        quality_gate=_gate(_HISTORICAL_ISSUE),
    )
    other = ScannerRun(
        scanner_type="liquidity_hunt", status="completed", data_degraded=False
    )
    db.add_all([degraded, clean, other])
    db.flush()
    return universe, degraded


def test_history_exposes_data_degraded_and_live_gaps(db: Session):
    _seed(db)
    data = client.get("/api/v1/scanner/history").json()
    by_degraded = {
        r["data_degraded"]: r
        for r in data
        if r["scanner_type"] == "pre_market_volume_spike"
    }
    assert by_degraded[True]["live_provider_gaps"] == [_LIVE_ISSUE]
    assert by_degraded[False]["live_provider_gaps"] == []  # historical gaps excluded


def test_history_filters_by_data_degraded(db: Session):
    _seed(db)
    data = client.get("/api/v1/scanner/history?data_degraded=true").json()
    assert len(data) == 1
    assert data[0]["data_degraded"] is True


def test_history_filters_by_universe_and_scanner_type(db: Session):
    universe, _ = _seed(db)
    data = client.get(
        f"/api/v1/scanner/history?universe_id={universe.id}"
        "&scanner_type=pre_market_volume_spike&limit=1"
    ).json()
    assert len(data) == 1
    assert data[0]["scanner_type"] == "pre_market_volume_spike"


def test_status_endpoint_exposes_degradation(db: Session):
    _, degraded = _seed(db)
    data = client.get(f"/api/v1/scanner/runs/{degraded.uuid}/status").json()
    assert data["data_degraded"] is True
    assert (
        data["live_provider_gaps"][0]["detail"]["reason"] == "no_fresh_premarket_bars"
    )
