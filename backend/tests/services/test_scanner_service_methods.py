import json
from datetime import date
from unittest.mock import MagicMock, patch

import pytest

from app.services.scanner import ScannerService


class TestDefaultScanDate:
    def test_returns_friday_when_today_is_saturday(self):
        with patch("app.services.scanner.get_market_today", return_value=date(2026, 5, 23)):
            result = ScannerService.default_scan_date()
        assert result == date(2026, 5, 22)

    def test_returns_friday_when_today_is_monday(self):
        # Monday — must skip Sunday AND Saturday
        with patch("app.services.scanner.get_market_today", return_value=date(2026, 5, 25)):
            result = ScannerService.default_scan_date()
        assert result == date(2026, 5, 22)

    def test_returns_yesterday_when_today_is_tuesday(self):
        with patch("app.services.scanner.get_market_today", return_value=date(2026, 5, 26)):
            result = ScannerService.default_scan_date()
        assert result == date(2026, 5, 25)


class TestCheckConcurrency:
    def test_returns_none_when_no_key(self):
        mock_r = MagicMock()
        mock_r.get.return_value = None
        with patch("redis.Redis.from_url", return_value=mock_r):
            result = ScannerService.check_concurrency(
                "redis://localhost", 1, "pre_market_volume_spike"
            )
        assert result is None

    def test_returns_dict_when_key_exists(self):
        payload = {"scan_id": "abc", "task_ids": ["t1"], "started_at": "2026-05-23T10:00:00Z"}
        mock_r = MagicMock()
        mock_r.get.return_value = json.dumps(payload)
        with patch("redis.Redis.from_url", return_value=mock_r):
            result = ScannerService.check_concurrency(
                "redis://localhost", 1, "pre_market_volume_spike"
            )
        assert result == payload

    def test_clears_and_returns_none_for_corrupt_key(self):
        mock_r = MagicMock()
        mock_r.get.return_value = "not-json{"
        with patch("redis.Redis.from_url", return_value=mock_r):
            result = ScannerService.check_concurrency(
                "redis://localhost", 1, "pre_market_volume_spike"
            )
        assert result is None
        mock_r.delete.assert_called_once_with("universe:1:scan:pre_market_volume_spike")


class TestResolveDateRange:
    def test_defaults_both_to_last_weekday_when_none(self):
        with patch("app.services.scanner.get_market_today", return_value=date(2026, 5, 26)):
            start, end = ScannerService.resolve_date_range(None, None)
        assert start == date(2026, 5, 25)
        assert end == date(2026, 5, 25)

    def test_defaults_end_to_start_when_only_start_given(self):
        start, end = ScannerService.resolve_date_range(date(2026, 5, 20), None)
        assert start == date(2026, 5, 20)
        assert end == date(2026, 5, 20)

    def test_passthrough_explicit_range(self):
        start, end = ScannerService.resolve_date_range(date(2026, 5, 20), date(2026, 5, 22))
        assert start == date(2026, 5, 20)
        assert end == date(2026, 5, 22)

    def test_raises_value_error_on_inverted_range(self):
        with pytest.raises(ValueError, match="end_date"):
            ScannerService.resolve_date_range(date(2026, 5, 22), date(2026, 5, 20))


class TestCountActiveTickers:
    def test_returns_count_from_db(self):
        db = MagicMock()
        mock_q = MagicMock()
        mock_q.filter.return_value = mock_q
        mock_q.count.return_value = 42
        db.query.return_value = mock_q
        assert ScannerService.count_active_tickers(db, universe_id=1) == 42

    def test_returns_zero_for_empty_universe(self):
        db = MagicMock()
        mock_q = MagicMock()
        mock_q.filter.return_value = mock_q
        mock_q.count.return_value = 0
        db.query.return_value = mock_q
        assert ScannerService.count_active_tickers(db, universe_id=99) == 0
