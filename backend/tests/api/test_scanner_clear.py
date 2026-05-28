import datetime

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.main import app
from app.models import ScannerEvent

client = TestClient(app)


def _make_event(ticker: str, scanner_type: str = "pre_market_volume") -> ScannerEvent:
    return ScannerEvent(
        ticker=ticker,
        event_date=datetime.date(2025, 1, 2),
        scanner_type=scanner_type,
        indicators={},
        criteria_met={},
        metadata_={},
    )


def test_clear_events_returns_count(db: Session):
    db.add(_make_event("AAPL", "pre_market_volume"))
    db.add(_make_event("AAPL", "oversold_bounce"))
    db.flush()

    response = client.delete("/api/scanner/events/AAPL")

    assert response.status_code == 200
    body = response.json()
    assert body["ticker"] == "AAPL"
    assert body["deleted_count"] == 2


def test_clear_events_zero_when_none_exist(db: Session):
    response = client.delete("/api/scanner/events/ZZZZ")

    assert response.status_code == 200
    assert response.json()["deleted_count"] == 0


def test_clear_events_does_not_affect_other_tickers(db: Session):
    db.add(_make_event("TSLA"))
    db.add(_make_event("MSFT"))
    db.flush()

    response = client.delete("/api/scanner/events/TSLA")

    assert response.status_code == 200
    assert response.json()["deleted_count"] == 1
    remaining = db.query(ScannerEvent).filter(ScannerEvent.ticker == "MSFT").all()
    assert len(remaining) == 1


def test_clear_events_normalises_ticker_case(db: Session):
    db.add(_make_event("AMZN"))
    db.flush()

    response = client.delete("/api/scanner/events/amzn")

    assert response.status_code == 200
    body = response.json()
    assert body["ticker"] == "AMZN"
    assert body["deleted_count"] == 1
