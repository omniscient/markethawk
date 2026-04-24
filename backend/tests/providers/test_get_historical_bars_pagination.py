# backend/tests/providers/test_get_historical_bars_pagination.py
from unittest.mock import MagicMock, patch, call
from app.providers.massive import MassiveDataProvider


def _make_provider():
    p = MassiveDataProvider.__new__(MassiveDataProvider)
    p._client = MagicMock()
    return p


def _make_agg(ts_ms: int, close: float = 100.0):
    agg = MagicMock()
    agg.timestamp = ts_ms
    agg.open = close
    agg.high = close
    agg.low = close
    agg.close = close
    agg.volume = 1000
    agg.vwap = close
    agg.transactions = 10
    return agg


# One minute = 60,000 ms
_1MIN_MS = 60_000

PAGE_LIMIT = 3  # use a small limit so tests don't need hundreds of fake bars


class TestGetHistoricalBarsPagination:
    def _call(self, provider, pages):
        """Set up get_aggs to return successive pages, then call get_historical_bars."""
        provider._client.get_aggs.side_effect = pages
        return provider.get_historical_bars(
            symbol="AAPL",
            timespan="minute",
            multiplier=1,
            from_date="2026-03-25",
            to_date="2026-04-24",
            limit=PAGE_LIMIT,
            paginate=True,
        )

    def test_single_page_makes_one_api_call(self):
        p = _make_provider()
        page1 = [_make_agg(1000 + i * _1MIN_MS) for i in range(2)]  # 2 < limit=3
        result = self._call(p, [page1])
        assert p._client.get_aggs.call_count == 1

    def test_single_page_returns_all_bars(self):
        p = _make_provider()
        page1 = [_make_agg(1000 + i * _1MIN_MS) for i in range(2)]
        result = self._call(p, [page1])
        assert len(result) == 2

    def test_full_page_triggers_second_api_call(self):
        p = _make_provider()
        page1 = [_make_agg(1000 + i * _1MIN_MS) for i in range(PAGE_LIMIT)]  # full
        page2 = [_make_agg(1000 + PAGE_LIMIT * _1MIN_MS)]                     # partial
        result = self._call(p, [page1, page2])
        assert p._client.get_aggs.call_count == 2

    def test_second_call_starts_one_ms_after_last_bar(self):
        p = _make_provider()
        last_ts = 1000 + (PAGE_LIMIT - 1) * _1MIN_MS
        page1 = [_make_agg(1000 + i * _1MIN_MS) for i in range(PAGE_LIMIT)]
        page2 = [_make_agg(last_ts + _1MIN_MS)]
        self._call(p, [page1, page2])

        second_call_kwargs = p._client.get_aggs.call_args_list[1]
        from_arg = second_call_kwargs.kwargs.get("from_") or second_call_kwargs.args[3]
        assert from_arg == last_ts + 1

    def test_multi_page_results_are_combined_in_order(self):
        p = _make_provider()
        page1 = [_make_agg(1000 + i * _1MIN_MS) for i in range(PAGE_LIMIT)]
        page2 = [_make_agg(1000 + (PAGE_LIMIT + i) * _1MIN_MS) for i in range(2)]
        result = self._call(p, [page1, page2])
        assert len(result) == PAGE_LIMIT + 2

    def test_empty_first_response_returns_no_bars(self):
        p = _make_provider()
        result = self._call(p, [[]])
        assert result == []
        assert p._client.get_aggs.call_count == 1

    def test_three_pages_fetches_all(self):
        p = _make_provider()
        page1 = [_make_agg(i * _1MIN_MS) for i in range(PAGE_LIMIT)]
        page2 = [_make_agg((PAGE_LIMIT + i) * _1MIN_MS) for i in range(PAGE_LIMIT)]
        page3 = [_make_agg((PAGE_LIMIT * 2 + i) * _1MIN_MS) for i in range(1)]
        result = self._call(p, [page1, page2, page3])
        assert p._client.get_aggs.call_count == 3
        assert len(result) == PAGE_LIMIT * 2 + 1
