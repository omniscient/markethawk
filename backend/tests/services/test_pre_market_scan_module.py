import asyncio
from datetime import date, datetime, time, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from zoneinfo import ZoneInfo

from app.models.stock_aggregate import StockAggregate
from app.services.scanner import ScannerService

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_bar(volume=1_000_000, close=100.0, high=101.0, low=99.0):
    return SimpleNamespace(volume=volume, close=close, high=high, low=low)


def _make_db_daily_bar(ticker, ts_utc_naive, close=100.0, volume=1_000_000):
    bar = StockAggregate()
    bar.ticker = ticker
    bar.timestamp = ts_utc_naive
    bar.timespan = "day"
    bar.multiplier = 1
    bar.open = close
    bar.high = close + 1
    bar.low = close - 1
    bar.close = close
    bar.volume = volume
    bar.is_pre_market = False
    bar.is_after_market = False
    return bar


def _make_db_pm_bar(ticker, ts_utc_naive, volume=5_000_000):
    bar = StockAggregate()
    bar.ticker = ticker
    bar.timestamp = ts_utc_naive
    bar.timespan = "minute"
    bar.multiplier = 1
    bar.open = 100.5
    bar.high = 101.0
    bar.low = 100.0
    bar.close = 100.5
    bar.volume = volume
    bar.is_pre_market = True
    bar.is_after_market = False
    return bar


# ---------------------------------------------------------------------------
# Pure unit tests for _detect — no DB, no fixtures
# ---------------------------------------------------------------------------


def test_detect_returns_none_when_fewer_than_20_bars():
    from app.services.pre_market_scan import _detect

    bars = [_make_bar() for _ in range(19)]
    assert _detect("TSST", bars, 500_000, False, 2.0, 30, 4.0, MagicMock()) is None


def test_detect_returns_none_when_liquidity_criterion_fails():
    from app.services.pre_market_scan import _detect

    # avg_volume_20d = 400_000 — below 500_000 liquidity threshold
    bars = [_make_bar(volume=400_000) for _ in range(25)]
    assert _detect("TSST", bars, 2_000_000, False, 2.0, 30, 4.0, MagicMock()) is None


def test_detect_returns_none_when_volume_spike_criterion_fails():
    from app.services.pre_market_scan import _detect

    # avg_volume_20d = 1_000_000; pre_market_volume = 3_000_000 (3× < 4× threshold)
    bars = [_make_bar(volume=1_000_000) for _ in range(25)]
    assert _detect("TSST", bars, 3_000_000, False, 2.0, 30, 4.0, MagicMock()) is None


def test_detect_returns_raw_signal_when_all_criteria_met():
    from app.services.pre_market_scan import RawSignal, _detect

    # avg_volume_20d = 1_000_000; pre_market = 5_000_000 (5× > 4×); liquidity OK
    bars = [_make_bar(volume=1_000_000) for _ in range(25)]
    mock_mod = MagicMock()
    mock_mod.get_volume_forecast.return_value = None

    result = _detect("TSST", bars, 5_000_000, False, 2.0, 30, 4.0, mock_mod)

    assert isinstance(result, RawSignal)
    assert result.ticker == "TSST"
    assert result.pre_market_volume == 5_000_000
    assert result.avg_volume_20d == 1_000_000
    assert result.threshold_method == "static_4x"
    assert result.criteria_met == {
        "volume_spike": True,
        "minimum_volume": True,
        "liquidity": True,
    }


# ---------------------------------------------------------------------------
# Full-pipeline regression test — mock DB + mocked enrichment + inline assertions
# ---------------------------------------------------------------------------


def _mock_db_for_full_pipeline(ticker, event_date, daily_volumes, pm_volume):
    """Return a mock DB session wired for the full run_pre_market_scan pipeline."""
    from app.models.scanner_event import ScannerEvent

    _ET = ZoneInfo("America/New_York")
    base_et = datetime.combine(event_date, datetime.min.time(), tzinfo=_ET)

    daily_bars = [
        _make_db_daily_bar(
            ticker,
            (base_et - timedelta(days=len(daily_volumes) - i))
            .astimezone(timezone.utc)
            .replace(tzinfo=None),
            volume=v,
        )
        for i, v in enumerate(daily_volumes)
    ]

    # Mock last pre-market bar returned by _build_timing_features
    pm_ts = datetime.combine(event_date, time(6, 30), tzinfo=_ET)
    mock_pm_bar = MagicMock()
    mock_pm_bar.timestamp = pm_ts.astimezone(timezone.utc).replace(tzinfo=None)

    db = MagicMock()

    def _query(model_or_col):
        q = MagicMock()
        q.filter.return_value = q
        q.order_by.return_value = q
        if model_or_col is StockAggregate:
            q.all.return_value = daily_bars
            q.first.return_value = mock_pm_bar
            q.scalar.return_value = pm_volume
        elif model_or_col is ScannerEvent:
            q.first.return_value = None  # no existing event → insert path
        else:
            q.scalar.return_value = pm_volume  # func.sum path
        return q

    db.query.side_effect = _query
    return db


def test_run_pre_market_scan_full_pipeline():
    """run_pre_market_scan passes indicators through detect→enrich→persist correctly."""
    from app.services.pre_market_scan import run_pre_market_scan

    ticker = "TSST"
    event_date = date(2025, 3, 10)
    daily_volumes = [1_000_000] * 25  # avg_volume_20d = 1M
    pm_volume = 5_000_000  # 5× avg → spike criteria met

    db = _mock_db_for_full_pipeline(ticker, event_date, daily_volumes, pm_volume)

    _day_metrics = {
        "opening_price": 0.0,
        "closing_price": None,
        "pre_market_close": None,
        "regular_high": 0.0,
        "regular_low": 0.0,
    }

    with (
        patch.object(
            ScannerService,
            "_get_batch_enrichment_data",
            return_value=({"TSST": {}}, {}, {}),
        ),
        patch.object(
            ScannerService, "calculate_day_metrics", return_value=_day_metrics
        ),
        patch.object(
            ScannerService,
            "_save_event",
            return_value={
                "id": 99,
                "ticker": ticker,
                "scanner_type": "pre_market_volume_spike",
            },
        ) as mock_save,
    ):
        results = asyncio.run(run_pre_market_scan([ticker], db, event_date=event_date))

    assert len(results) == 1
    assert results[0]["ticker"] == ticker
    assert results[0]["scanner_type"] == "pre_market_volume_spike"

    mock_save.assert_called_once()
    kw = mock_save.call_args.kwargs
    assert kw["ticker"] == ticker
    assert kw["scanner_type"] == "pre_market_volume_spike"
    ind = kw["indicators"]
    assert ind["pre_market_volume"] == 5_000_000
    assert ind["avg_volume_20d"] == 1_000_000
    assert ind["relative_volume"] == 5.0
    assert ind["volume_spike_ratio"] == 5.0
    assert ind["volume_threshold_method"] == "static_4x"
    assert kw["criteria_met"] == {
        "volume_spike": True,
        "minimum_volume": True,
        "liquidity": True,
    }


def test_run_pre_market_scan_importable_from_module():
    from app.services.pre_market_scan import run_pre_market_scan

    assert callable(run_pre_market_scan)
