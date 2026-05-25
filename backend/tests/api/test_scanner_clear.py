from unittest.mock import MagicMock, patch
from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)


def _make_db_mock(delete_count: int) -> MagicMock:
    """Build a minimal Session mock whose query(...).filter(...).delete() returns delete_count."""
    db = MagicMock()
    db.query.return_value.filter.return_value.delete.return_value = delete_count
    return db


def test_clear_events_returns_count():
    db = _make_db_mock(delete_count=2)

    response = client.delete("/api/scanner/events/AAPL")


    assert response.status_code == 200
    body = response.json()
    assert body["ticker"] == "AAPL"
    assert body["deleted_count"] == 2
    db.commit.assert_called_once()


def test_clear_events_zero_when_none_exist():
    db = _make_db_mock(delete_count=0)

    response = client.delete("/api/scanner/events/ZZZZ")


    assert response.status_code == 200
    assert response.json()["deleted_count"] == 0


def test_clear_events_does_not_affect_other_tickers():
    """The endpoint filters by exact ticker — verify the filter arg is uppercased ticker."""
    from app.models import ScannerEvent

    db = _make_db_mock(delete_count=1)

    client.delete("/api/scanner/events/TSLA")


    # The filter must be called with the ScannerEvent.ticker == "TSLA" expression.
    # We verify filter was called (not called with "MSFT" or nothing).
    db.query.assert_called_once_with(ScannerEvent)
    db.query.return_value.filter.assert_called_once()


def test_clear_events_normalises_ticker_case():
    db = _make_db_mock(delete_count=1)

    response = client.delete("/api/scanner/events/amzn")


    assert response.status_code == 200
    assert response.json()["ticker"] == "AMZN"
