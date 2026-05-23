# backend/tests/providers/test_ibkr_provider.py
"""
Verify that IBKRDataProvider satisfies the sync BaseDataProvider interface.
All futures-specific async methods are out of scope here.
"""
from app.providers.ibkr import IBKRDataProvider


def _make_provider() -> IBKRDataProvider:
    return IBKRDataProvider.__new__(IBKRDataProvider)


class TestIBKRSyncInterface:
    def test_get_bars_returns_empty_list(self):
        p = _make_provider()
        result = p.get_bars(
            symbol="ES",
            timespan="day",
            multiplier=1,
            from_date="2026-01-01",
            to_date="2026-01-31",
        )
        assert result == []

    def test_get_bars_is_not_a_coroutine(self):
        import inspect
        p = _make_provider()
        result = p.get_bars(
            symbol="ES", timespan="day", multiplier=1,
            from_date="2026-01-01", to_date="2026-01-31",
        )
        assert not inspect.iscoroutine(result), "get_bars must be sync, not a coroutine"

    def test_get_snapshots_returns_empty_list(self):
        p = _make_provider()
        assert p.get_snapshots() == []
        assert p.get_snapshots(symbols=["ES", "NQ"]) == []

    def test_get_snapshots_is_not_a_coroutine(self):
        import inspect
        p = _make_provider()
        result = p.get_snapshots()
        assert not inspect.iscoroutine(result), "get_snapshots must be sync, not a coroutine"

    def test_get_ticker_details_returns_empty_dict(self):
        p = _make_provider()
        assert p.get_ticker_details("ES") == {}

    def test_get_ticker_details_is_not_a_coroutine(self):
        import inspect
        p = _make_provider()
        result = p.get_ticker_details("ES")
        assert not inspect.iscoroutine(result), "get_ticker_details must be sync, not a coroutine"

    def test_supported_asset_classes_is_futures(self):
        p = _make_provider()
        assert p.supported_asset_classes == ["futures"]

    def test_name_is_ibkr(self):
        p = _make_provider()
        assert p.name == "ibkr"
