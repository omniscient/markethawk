"""Tests for ScannerEvent model — relationship ordering and latest_review property."""

from datetime import date, datetime

import pytest
from sqlalchemy.orm import Session

from app.models.scanner_event import ScannerEvent
from app.models.signal_review import SignalReview


@pytest.fixture
def event(db: Session):
    e = ScannerEvent(
        ticker="AAPL",
        event_date=date(2026, 5, 1),
        scanner_type="test_type",
    )
    db.add(e)
    db.flush()
    return e


def test_latest_review_returns_none_when_no_reviews(db: Session, event):
    assert event.latest_review is None


def test_reviews_ordered_by_reviewed_at_desc(db: Session, event):
    """reviews relationship must be ordered most-recent-first so latest_review = reviews[0]."""
    old_review = SignalReview(
        scanner_event_id=event.id,
        verdict="confirmed",
        reviewed_at=datetime(2026, 5, 1, 9, 0, 0),
    )
    new_review = SignalReview(
        scanner_event_id=event.id,
        verdict="rejected",
        reviewed_at=datetime(2026, 5, 2, 10, 0, 0),
    )
    db.add(old_review)
    db.add(new_review)
    db.flush()
    db.expire(event)

    # reviews[0] must be the most recent when order_by DESC is set
    assert event.reviews[0].id == new_review.id


def test_latest_review_returns_most_recent(db: Session, event):
    old_review = SignalReview(
        scanner_event_id=event.id,
        verdict="confirmed",
        reviewed_at=datetime(2026, 5, 1, 9, 0, 0),
    )
    new_review = SignalReview(
        scanner_event_id=event.id,
        verdict="rejected",
        reviewed_at=datetime(2026, 5, 2, 10, 0, 0),
    )
    db.add(old_review)
    db.add(new_review)
    db.flush()
    db.expire(event)

    assert event.latest_review.id == new_review.id
