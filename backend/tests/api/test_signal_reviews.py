"""
Integration tests for POST/GET /api/signal-reviews.
"""
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.main import app
from app.core.database import get_db
from app.models.scanner_event import ScannerEvent
from tests.fixtures.scanner import seed_scanner_events

client = TestClient(app)


def _get_first_event_id(db: Session) -> int:
    seed_scanner_events(db)
    event = db.query(ScannerEvent).first()
    return event.id


def test_create_confirmed_review(db: Session):
    event_id = _get_first_event_id(db)

    app.dependency_overrides[get_db] = lambda: db
    response = client.post("/api/signal-reviews", json={
        "scanner_event_id": event_id,
        "verdict": "confirmed",
    })
    app.dependency_overrides.clear()

    assert response.status_code == 201
    data = response.json()
    assert data["verdict"] == "confirmed"
    assert data["scanner_event_id"] == event_id
    assert data["id"] > 0


def test_create_rejected_review_requires_reason(db: Session):
    event_id = _get_first_event_id(db)

    app.dependency_overrides[get_db] = lambda: db
    response = client.post("/api/signal-reviews", json={
        "scanner_event_id": event_id,
        "verdict": "rejected",
        # missing reject_reason
    })
    app.dependency_overrides.clear()

    assert response.status_code == 422


def test_create_rejected_review_with_reason(db: Session):
    event_id = _get_first_event_id(db)

    app.dependency_overrides[get_db] = lambda: db
    response = client.post("/api/signal-reviews", json={
        "scanner_event_id": event_id,
        "verdict": "rejected",
        "reject_reason": "noise",
        "notes": "Volume spike was a data artifact",
    })
    app.dependency_overrides.clear()

    assert response.status_code == 201
    data = response.json()
    assert data["reject_reason"] == "noise"


def test_create_review_invalid_event_id(db: Session):
    app.dependency_overrides[get_db] = lambda: db
    response = client.post("/api/signal-reviews", json={
        "scanner_event_id": 999999,
        "verdict": "confirmed",
    })
    app.dependency_overrides.clear()

    assert response.status_code == 404


def test_create_review_invalid_verdict(db: Session):
    event_id = _get_first_event_id(db)

    app.dependency_overrides[get_db] = lambda: db
    response = client.post("/api/signal-reviews", json={
        "scanner_event_id": event_id,
        "verdict": "maybe",
    })
    app.dependency_overrides.clear()

    assert response.status_code == 422


def test_list_reviews_by_scanner_type(db: Session):
    event_id = _get_first_event_id(db)
    event = db.query(ScannerEvent).filter(ScannerEvent.id == event_id).first()
    scanner_type = event.scanner_type

    from app.models.signal_review import SignalReview
    review = SignalReview(scanner_event_id=event_id, verdict="confirmed")
    db.add(review)
    db.flush()

    app.dependency_overrides[get_db] = lambda: db
    response = client.get(f"/api/signal-reviews?scanner_type={scanner_type}")
    app.dependency_overrides.clear()

    assert response.status_code == 200
    data = response.json()
    assert len(data) >= 1
    assert all(r["scanner_type"] == scanner_type for r in data)


def test_list_reviews_liquidity_hunt_alias(db: Session):
    # seed_scanner_events creates liquidity_hunt_pre events; querying with
    # the 'liquidity_hunt' umbrella alias must return them
    seed_scanner_events(db)
    lh_event = (
        db.query(ScannerEvent)
        .filter(ScannerEvent.scanner_type == "liquidity_hunt_pre")
        .first()
    )
    from app.models.signal_review import SignalReview
    review = SignalReview(scanner_event_id=lh_event.id, verdict="confirmed")
    db.add(review)
    db.flush()

    app.dependency_overrides[get_db] = lambda: db
    response = client.get("/api/signal-reviews?scanner_type=liquidity_hunt")
    app.dependency_overrides.clear()

    assert response.status_code == 200
    data = response.json()
    assert len(data) >= 1
    assert all(r["scanner_type"] in ("liquidity_hunt", "liquidity_hunt_pre", "liquidity_hunt_post") for r in data)


def test_list_reviews_missing_scanner_type(db: Session):
    app.dependency_overrides[get_db] = lambda: db
    response = client.get("/api/signal-reviews")
    app.dependency_overrides.clear()

    assert response.status_code == 422
