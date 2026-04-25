# backend/tests/services/test_scanner_refactor.py
import asyncio
import pytest
from datetime import date, datetime, timezone
from unittest.mock import MagicMock, patch, AsyncMock

from app.services.scanner import ScannerService
from app.models.stock_aggregate import StockAggregate


def _make_daily_bar(ticker, timestamp_utc, close, volume):
    b = StockAggregate()
    b.ticker = ticker
    b.timestamp = timestamp_utc
    b.timespan = 'day'
    b.multiplier = 1
    b.open = close
    b.high = close
    b.low = close
    b.close = close
    b.volume = volume
    b.is_pre_market = False
    b.is_after_market = False
    return b


def _mock_db_for_pre_market(ticker, event_date, daily_closes, daily_volumes, pm_volume):
    """Return a mock DB session wired for run_pre_market_scan."""
    from datetime import timedelta
    from zoneinfo import ZoneInfo
    _ET = ZoneInfo("America/New_York")
    base = datetime.combine(event_date - timedelta(days=len(daily_closes)), datetime.min.time(), tzinfo=_ET)

    daily_bars = [
        _make_daily_bar(ticker, (base + timedelta(days=i)).astimezone(timezone.utc).replace(tzinfo=None), c, v)
        for i, (c, v) in enumerate(zip(daily_closes, daily_volumes))
    ]

    db = MagicMock()

    def query_side_effect(model):
        mock_q = MagicMock()
        # daily bars query returns daily_bars
        mock_q.filter.return_value = mock_q
        mock_q.order_by.return_value = mock_q
        mock_q.all.return_value = daily_bars
        # pre-market volume scalar
        mock_q.scalar.return_value = pm_volume
        return mock_q

    db.query.side_effect = query_side_effect
    return db


def test_pre_market_scan_detects_spike_from_db():
    """Refactored run_pre_market_scan finds events using only DB aggregates."""
    ticker = "TEST"
    event_date = date(2025, 3, 10)

    # 25 daily bars at close=100, volume=1_000_000 each — avg_volume_20d = 1M
    daily_closes = [100.0] * 25
    daily_volumes = [1_000_000] * 25
    pm_volume = 5_000_000  # 5x avg → triggers volume_spike criterion

    db = _mock_db_for_pre_market(ticker, event_date, daily_closes, daily_volumes, pm_volume)

    with patch.object(ScannerService, '_get_batch_enrichment_data', return_value={ticker: {}}), \
         patch.object(ScannerService, 'calculate_day_metrics', return_value={
             "closing_price": 102.0, "pre_market_close": 101.0,
             "opening_price": 101.0, "regular_high": 103.0, "regular_low": 99.0,
         }), \
         patch.object(ScannerService, '_save_event', return_value={"id": 1}) as mock_save:

        results = asyncio.run(ScannerService.run_pre_market_scan([ticker], db, event_date=event_date))

    mock_save.assert_called_once()
    call_kwargs = mock_save.call_args.kwargs
    assert call_kwargs["scanner_type"] == "pre_market_volume_spike"
    assert call_kwargs["ticker"] == ticker
    assert call_kwargs["event_date"] == event_date
    assert len(results) == 1


def test_pre_market_scan_skips_insufficient_daily_bars():
    """run_pre_market_scan skips tickers with fewer than 20 daily bars."""
    ticker = "THIN"
    event_date = date(2025, 3, 10)

    db = _mock_db_for_pre_market(ticker, event_date, [100.0] * 5, [1_000_000] * 5, 5_000_000)

    with patch.object(ScannerService, '_get_batch_enrichment_data', return_value={ticker: {}}), \
         patch.object(ScannerService, '_save_event') as mock_save:

        results = asyncio.run(ScannerService.run_pre_market_scan([ticker], db, event_date=event_date))

    mock_save.assert_not_called()
    assert results == []
