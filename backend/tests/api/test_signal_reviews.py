"""
Integration tests for signal review endpoints under /api/scanner/.
"""

import uuid as uuid_lib

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.main import app
from app.models.scanner_event import ScannerEvent
from app.models.signal_review import SignalReview
from tests.fixtures.scanner import seed_scanner_events

client = TestClient(app)


def _get_first_event(db: Session) -> ScannerEvent:
    seed_scanner_events(db)
    return db.query(ScannerEvent).first()


def test_create_confirmed_review(db: Session):
    event = _get_first_event(db)
    response = client.post(
        f"/api/scanner/events/{event.uuid}/review",
        json={
            "verdict": "confirmed",
        },
    )
    assert response.status_code == 201
    data = response.json()
    assert data["verdict"] == "confirmed"
    assert data["scanner_event_id"] == event.id


def test_create_uncertain_review(db: Session):
    event = _get_first_event(db)
    response = client.post(
        f"/api/scanner/events/{event.uuid}/review",
        json={
            "verdict": "uncertain",
            "notes": "Need to check chart",
        },
    )
    assert response.status_code == 201
    assert response.json()["verdict"] == "uncertain"


def test_create_rejected_review_requires_reason(db: Session):
    event = _get_first_event(db)
    response = client.post(
        f"/api/scanner/events/{event.uuid}/review",
        json={
            "verdict": "rejected",
        },
    )
    assert response.status_code == 422


def test_create_rejected_review_with_reason(db: Session):
    event = _get_first_event(db)
    response = client.post(
        f"/api/scanner/events/{event.uuid}/review",
        json={
            "verdict": "rejected",
            "reject_reason": "noise",
            "notes": "Volume spike was a data artifact",
        },
    )
    assert response.status_code == 201
    assert response.json()["reject_reason"] == "noise"


def test_create_review_invalid_uuid(db: Session):
    response = client.post(
        "/api/scanner/events/not-a-uuid/review",
        json={
            "verdict": "confirmed",
        },
    )
    assert response.status_code == 400


def test_create_review_nonexistent_event(db: Session):
    fake_uuid = str(uuid_lib.uuid4())
    response = client.post(
        f"/api/scanner/events/{fake_uuid}/review",
        json={
            "verdict": "confirmed",
        },
    )
    assert response.status_code == 404


def test_create_review_invalid_verdict(db: Session):
    event = _get_first_event(db)
    response = client.post(
        f"/api/scanner/events/{event.uuid}/review",
        json={
            "verdict": "maybe",
        },
    )
    assert response.status_code == 422


def test_list_reviews_by_scanner_type(db: Session):
    event = _get_first_event(db)
    review = SignalReview(scanner_event_id=event.id, verdict="confirmed")
    db.add(review)
    db.flush()

    response = client.get(
        f"/api/scanner/events/reviews?scanner_type={event.scanner_type}"
    )
    assert response.status_code == 200
    data = response.json()
    assert len(data) >= 1
    assert all(r["scanner_type"] == event.scanner_type for r in data)


def test_list_reviews_liquidity_hunt_alias(db: Session):
    events = seed_scanner_events(db)
    lh_event = next(e for e in events if e.scanner_type == "liquidity_hunt_pre")
    review = SignalReview(scanner_event_id=lh_event.id, verdict="confirmed")
    db.add(review)
    db.flush()

    response = client.get("/api/scanner/events/reviews?scanner_type=liquidity_hunt")
    assert response.status_code == 200
    data = response.json()
    assert len(data) >= 1


def test_list_reviews_filter_by_verdict(db: Session):
    event = _get_first_event(db)
    db.add(SignalReview(scanner_event_id=event.id, verdict="confirmed"))
    db.add(
        SignalReview(
            scanner_event_id=event.id, verdict="rejected", reject_reason="noise"
        )
    )
    db.flush()

    response = client.get(
        f"/api/scanner/events/reviews?scanner_type={event.scanner_type}&verdict=confirmed"
    )
    assert response.status_code == 200
    data = response.json()
    assert all(r["verdict"] == "confirmed" for r in data)


def test_list_reviews_missing_scanner_type(db: Session):
    response = client.get("/api/scanner/events/reviews")
    assert response.status_code == 422


def test_review_stats(db: Session):
    events = seed_scanner_events(db)
    db.add(SignalReview(scanner_event_id=events[0].id, verdict="confirmed"))
    db.add(
        SignalReview(
            scanner_event_id=events[1].id, verdict="rejected", reject_reason="noise"
        )
    )
    db.add(SignalReview(scanner_event_id=events[2].id, verdict="uncertain"))
    db.flush()

    response = client.get("/api/scanner/reviews/stats")
    assert response.status_code == 200
    data = response.json()
    assert data["total_events"] > 0
    assert data["reviewed_count"] == 3
    assert 0.0 <= data["acceptance_rate"] <= 1.0
    assert isinstance(data["by_scanner_type"], list)
    assert isinstance(data["top_rejection_reasons"], list)


def test_review_stats_with_scanner_type_filter(db: Session):
    events = seed_scanner_events(db)
    pmvs_events = [e for e in events if e.scanner_type == "pre_market_volume_spike"]
    for e in pmvs_events:
        db.add(SignalReview(scanner_event_id=e.id, verdict="confirmed"))
    db.flush()

    response = client.get(
        "/api/scanner/reviews/stats?scanner_type=pre_market_volume_spike"
    )
    assert response.status_code == 200
    data = response.json()
    assert data["reviewed_count"] > 0
    assert all(
        row["scanner_type"] == "pre_market_volume_spike"
        for row in data["by_scanner_type"]
    )


def test_scanner_results_include_latest_review(db: Session):
    event = _get_first_event(db)
    db.add(SignalReview(scanner_event_id=event.id, verdict="confirmed"))
    db.flush()

    response = client.get(f"/api/scanner/results?scanner_type={event.scanner_type}")
    assert response.status_code == 200
    data = response.json()
    reviewed = [e for e in data if e.get("latest_review") is not None]
    assert len(reviewed) >= 1
    assert reviewed[0]["latest_review"]["verdict"] == "confirmed"
