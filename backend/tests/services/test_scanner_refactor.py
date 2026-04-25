# backend/tests/services/test_scanner_refactor.py
import asyncio
from datetime import date, datetime, timezone
from unittest.mock import MagicMock, patch

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
        mock_q.filter.return_value = mock_q
        mock_q.order_by.return_value = mock_q
        if model is StockAggregate:
            mock_q.all.return_value = daily_bars
        else:
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


def _make_daily_bar_full(ticker, i, close, high, low, open_, volume):
    b = StockAggregate()
    b.ticker = ticker
    b.timestamp = datetime(2025, 1, i + 1, 14, 30, tzinfo=timezone.utc).replace(tzinfo=None)
    b.timespan = 'day'
    b.multiplier = 1
    b.open = open_
    b.high = high
    b.low = low
    b.close = close
    b.volume = volume
    b.is_pre_market = False
    b.is_after_market = False
    return b


def test_oversold_bounce_detects_rsi_crossover():
    """run_oversold_bounce_scan detects dual RSI crossover using only DB daily bars."""
    ticker = "BOUNCE"
    event_date = date(2025, 1, 20)

    # 18 bars at 100, then sharp dip to 60, then recovery to 100.
    # The dip to 60 pushes RSI-2 and RSI-5 well below their thresholds (15 and 27),
    # and the recovery to 100 causes both to cross back above on the final bar.
    closes = [100.0] * 18 + [60.0, 100.0]
    opens  = closes[:]
    highs  = [c + 1 for c in closes]
    lows   = [c - 1 for c in closes]
    vols   = [800_000] * len(closes)

    daily_bars = [
        _make_daily_bar_full(ticker, i, closes[i], highs[i], lows[i], opens[i], vols[i])
        for i in range(len(closes))
    ]

    db = MagicMock()
    mock_q = MagicMock()
    mock_q.filter.return_value = mock_q
    mock_q.order_by.return_value = mock_q
    mock_q.all.return_value = daily_bars
    db.query.return_value = mock_q

    with patch.object(ScannerService, '_get_batch_enrichment_data', return_value={ticker: {}}), \
         patch.object(ScannerService, 'calculate_day_metrics', return_value={
             "closing_price": 100.0, "pre_market_close": 99.0,
             "opening_price": 100.0, "regular_high": 101.0, "regular_low": 99.0,
         }), \
         patch.object(ScannerService, '_save_event', return_value={"id": 2}) as mock_save:

        results = asyncio.run(
            ScannerService.run_oversold_bounce_scan([ticker], db, event_date=event_date)
        )

    mock_save.assert_called_once()
    assert len(results) == 1


def test_oversold_bounce_skips_with_insufficient_bars():
    """run_oversold_bounce_scan skips tickers with fewer than 10 daily bars."""
    ticker = "THIN2"
    event_date = date(2025, 3, 10)

    daily_bars = [_make_daily_bar_full(ticker, i, 50.0, 51.0, 49.0, 50.0, 600_000) for i in range(5)]

    db = MagicMock()
    mock_q = MagicMock()
    mock_q.filter.return_value = mock_q
    mock_q.order_by.return_value = mock_q
    mock_q.all.return_value = daily_bars
    db.query.return_value = mock_q

    with patch.object(ScannerService, '_get_batch_enrichment_data', return_value={ticker: {}}), \
         patch.object(ScannerService, '_save_event') as mock_save:

        results = asyncio.run(
            ScannerService.run_oversold_bounce_scan([ticker], db, event_date=event_date)
        )

    mock_save.assert_not_called()
    assert results == []


def test_liquidity_hunt_date_filter_respected():
    """run_liquidity_hunt_scan with start_date/end_date applies date filters to candidates query."""
    ticker = "DATECHK"
    target_date = date(2025, 3, 10)

    db = MagicMock()
    mock_q = MagicMock()
    mock_q.filter.return_value = mock_q
    mock_q.group_by.return_value = mock_q
    mock_q.having.return_value = mock_q
    mock_q.all.return_value = []
    db.query.return_value = mock_q

    result = asyncio.run(
        ScannerService.run_liquidity_hunt_scan(
            [ticker], db, start_date=target_date, end_date=target_date
        )
    )
    assert result == []
    # Base filter + start_date filter + end_date filter = at least 3 filter calls
    assert mock_q.filter.call_count >= 3


def test_for_date_wrappers_exist():
    """*_for_date wrapper methods exist and are async callables."""
    assert hasattr(ScannerService, 'run_pre_market_scan_for_date')
    assert hasattr(ScannerService, 'run_oversold_bounce_scan_for_date')
    assert hasattr(ScannerService, 'run_liquidity_hunt_scan_for_date')
    # Verify they are coroutine functions (async def)
    assert asyncio.iscoroutinefunction(ScannerService.run_pre_market_scan_for_date)
    assert asyncio.iscoroutinefunction(ScannerService.run_oversold_bounce_scan_for_date)
    assert asyncio.iscoroutinefunction(ScannerService.run_liquidity_hunt_scan_for_date)
