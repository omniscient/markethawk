from datetime import date

from fastapi.testclient import TestClient

from app.main import app
from app.models.scanner_event import ScannerEvent

client = TestClient(app)


def _seed_event(db) -> ScannerEvent:
    event = ScannerEvent(
        ticker="TGT",
        event_date=date(2026, 7, 3),
        scanner_type="pre_market_volume_spike",
        summary="TGT target signal",
        severity="high",
        indicators={},
        criteria_met={},
        metadata_={},
        explanation={},
    )
    db.add(event)
    db.flush()
    return event


def test_text_semantic_signal_search_endpoint_labels_no_result_state(db):
    response = client.get(
        "/api/v1/outcomes/semantic-signal-search",
        params={"query": "growth query", "top_k": 3},
    )

    assert response.status_code == 200
    data = response.json()
    assert data["label"] == "Semantic matches"
    assert data["deterministic_analogs"] is None
    assert data["semantic_matches"] == []


def test_event_semantic_signal_search_endpoint_keeps_analogs_separate(db):
    event = _seed_event(db)

    response = client.get(f"/api/v1/outcomes/event/{event.id}/semantic-matches")

    assert response.status_code == 200
    data = response.json()
    assert data["label"] == "Semantic matches"
    assert data["semantic_matches"] == []
    assert data["deterministic_analogs"]["analogs"] == []
