from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from starlette.responses import StreamingResponse


def _make_db(universe_obj=None):
    db = MagicMock()
    mock_q = MagicMock()
    mock_q.filter.return_value = mock_q
    mock_q.order_by.return_value = mock_q
    mock_q.first.return_value = universe_obj
    mock_q.all.return_value = []
    mock_q.__iter__ = MagicMock(return_value=iter([]))
    db.query.return_value = mock_q
    return db


def _make_request(**kwargs):
    defaults = dict(
        tickers=["AAPL"],
        timespan="day",
        multiplier=1,
        from_date=None,
        to_date=None,
        zip_format="per_ticker",
    )
    defaults.update(kwargs)
    return SimpleNamespace(**defaults)


class TestExportAggregates:
    def test_universe_not_found_raises_domain_error(self):
        from app.exceptions import UniverseNotFoundError
        from app.services.universe_export import export_aggregates

        db = _make_db(universe_obj=None)
        with pytest.raises(UniverseNotFoundError):
            export_aggregates(999, _make_request(), db)

    def test_empty_tickers_raises_domain_error(self):
        from app.exceptions import UniverseValidationError
        from app.services.universe_export import export_aggregates

        universe = MagicMock()
        universe.name = "TestUniverse"
        db = _make_db(universe_obj=universe)
        with pytest.raises(UniverseValidationError):
            export_aggregates(1, _make_request(tickers=[]), db)

    def test_valid_request_returns_streaming_response(self):
        from app.services.universe_export import export_aggregates

        universe = MagicMock()
        universe.name = "TestUniverse"
        db = _make_db(universe_obj=universe)
        result = export_aggregates(1, _make_request(tickers=["AAPL"]), db)
        assert isinstance(result, StreamingResponse)
