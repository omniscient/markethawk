from datetime import date

from fastapi.testclient import TestClient

from app.main import app
from app.models.scanner_event import ScannerEvent

client = TestClient(app)


def _seed_event(db, *, ticker="TGT", scanner_type="pre_market_volume_spike"):
    event = ScannerEvent(
        ticker=ticker,
        event_date=date(2026, 7, 3),
        scanner_type=scanner_type,
        summary=f"{ticker} signal",
        severity="high",
        indicators={},
        criteria_met={},
        metadata_={},
        explanation={},
    )
    db.add(event)
    db.flush()
    return event


def test_event_analyst_qa_endpoint_disabled_by_default(db):
    event = _seed_event(db)

    response = client.get(
        f"/api/v1/outcomes/event/{event.id}/analyst-qa",
        params={"question": "Why did this signal work?"},
    )

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "disabled"
    assert data["answer"] is None


def test_filtered_analyst_qa_endpoint_disabled_by_default(db):
    _seed_event(db, ticker="TGT", scanner_type="pre_market_volume_spike")

    response = client.get(
        "/api/v1/outcomes/analyst-qa",
        params={
            "question": "Summarize pre-market volume signals.",
            "scanner_type": "pre_market_volume_spike",
        },
    )

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "disabled"
    assert data["answer"] is None
