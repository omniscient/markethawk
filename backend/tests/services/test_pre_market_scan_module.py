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
# Full-pipeline regression test — real transaction-rollback DB fixture
# ---------------------------------------------------------------------------


def test_run_pre_market_scan_golden_day(db):
    """Full-pipeline regression: detect→enrich→persist against the real DB fixture."""
    from app.services.pre_market_scan import run_pre_market_scan

    ticker = "TSST"
    event_date = date(2025, 3, 10)
    _ET = ZoneInfo("America/New_York")
    base_et = datetime.combine(event_date, datetime.min.time(), tzinfo=_ET)

    # Seed 25 daily bars (avg_volume_20d = 1M)
    for i in range(25):
        bar = _make_db_daily_bar(
            ticker,
            (base_et - timedelta(days=25 - i))
            .astimezone(timezone.utc)
            .replace(tzinfo=None),
            volume=1_000_000,
        )
        db.add(bar)

    # Seed one pre-market minute bar (5M volume → 5× avg → spike passes)
    pm_ts = datetime.combine(event_date, time(7, 0), tzinfo=_ET)
    db.add(
        _make_db_pm_bar(
            ticker,
            pm_ts.astimezone(timezone.utc).replace(tzinfo=None),
            volume=5_000_000,
        )
    )
    db.flush()

    with (
        patch.object(
            ScannerService,
            "_get_batch_enrichment_data",
            return_value=({"TSST": {}}, {}, {}),
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


def test_enriched_signal_has_spec_shape():
    """EnrichedSignal must carry raw: RawSignal and day_metrics: dict per spec."""
    from app.services.pre_market_scan import EnrichedSignal

    fields = EnrichedSignal.__dataclass_fields__
    assert "raw" in fields, "EnrichedSignal must carry a 'raw: RawSignal' reference"
    assert "day_metrics" in fields, "EnrichedSignal must carry 'day_metrics: dict'"


def test_run_pre_market_scan_importable_from_module():
    from app.services.pre_market_scan import run_pre_market_scan

    assert callable(run_pre_market_scan)


def test_pre_market_scan_observes_slo_metrics(db):
    """After a successful run, scan_last_success_timestamp, scan_failed_tickers_ratio,
    and scan_data_to_detection_seconds must all be observed."""
    import asyncio
    import datetime as _dt
    import time
    from unittest.mock import MagicMock, patch

    from app.models.stock_aggregate import StockAggregate
    from app.services.scanner import ScannerService

    ticker = "SLOM"
    event_date = date(2025, 3, 10)
    _ET = ZoneInfo("America/New_York")
    base_et = datetime.combine(event_date, datetime.min.time(), tzinfo=_ET)

    # Seed 25 daily bars so _detect's 20-bar history check passes
    for i in range(25):
        bar = StockAggregate()
        bar.ticker = ticker
        bar.timestamp = (
            (base_et - timedelta(days=25 - i))
            .astimezone(timezone.utc)
            .replace(tzinfo=None)
        )
        bar.timespan = "day"
        bar.multiplier = 1
        bar.open = bar.high = bar.low = bar.close = 100.0
        bar.volume = 1_000_000
        bar.is_pre_market = False
        bar.is_after_market = False
        db.add(bar)

    # Seed one pre-market minute bar (5× avg → spike passes, also provides max_bar_ts)
    pm_ts = datetime.combine(event_date, _dt.time(7, 0), tzinfo=_ET)
    pm_bar = StockAggregate()
    pm_bar.ticker = ticker
    pm_bar.timestamp = pm_ts.astimezone(timezone.utc).replace(tzinfo=None)
    pm_bar.timespan = "minute"
    pm_bar.multiplier = 1
    pm_bar.open = pm_bar.high = pm_bar.low = pm_bar.close = 100.5
    pm_bar.volume = 5_000_000
    pm_bar.is_pre_market = True
    pm_bar.is_after_market = False
    db.add(pm_bar)
    db.flush()

    with (
        patch.object(
            ScannerService,
            "_get_batch_enrichment_data",
            return_value=({"SLOM": {}}, {}, {}),
        ),
        patch.object(
            ScannerService,
            "_save_event",
            return_value={
                "id": 1,
                "ticker": ticker,
                "scanner_type": "pre_market_volume_spike",
            },
        ),
        patch("app.services.pre_market_scan.scan_last_success_timestamp") as mock_ts,
        patch("app.services.pre_market_scan.scan_failed_tickers_ratio") as mock_ratio,
        patch(
            "app.services.pre_market_scan.scan_data_to_detection_seconds"
        ) as mock_dtd,
    ):
        mock_ts_lbl = MagicMock()
        mock_ts.labels.return_value = mock_ts_lbl
        mock_ratio_lbl = MagicMock()
        mock_ratio.labels.return_value = mock_ratio_lbl
        mock_dtd_lbl = MagicMock()
        mock_dtd.labels.return_value = mock_dtd_lbl

        from app.services.pre_market_scan import run_pre_market_scan

        asyncio.run(run_pre_market_scan([ticker], db, event_date=event_date))

    mock_ts.labels.assert_called_with(scanner_type="pre_market_volume_spike")
    mock_ts_lbl.set.assert_called_once()
    ts_arg = mock_ts_lbl.set.call_args[0][0]
    assert abs(ts_arg - time.time()) < 30

    mock_ratio.labels.assert_called_with(scanner_type="pre_market_volume_spike")
    mock_ratio_lbl.set.assert_called_once()
    ratio_arg = mock_ratio_lbl.set.call_args[0][0]
    assert 0.0 <= ratio_arg <= 1.0

    mock_dtd.labels.assert_called_with(scanner_type="pre_market_volume_spike")
    mock_dtd_lbl.observe.assert_called_once()
    dtd_arg = mock_dtd_lbl.observe.call_args[0][0]
    assert dtd_arg >= 0


def test_pre_market_scan_total_failure_does_not_mark_success(db):
    """A total ticker failure (every ticker errors) must NOT advance
    scan_last_success_timestamp — otherwise the missed-slot staleness alert can
    never fire on a full outage. Duration is still recorded; ratio is 1.0."""
    from app.exceptions import ScanError

    ticker = "FAILALL"
    event_date = date(2025, 3, 10)

    with (
        patch.object(
            ScannerService,
            "_get_batch_enrichment_data",
            return_value=({"FAILALL": {}}, {}, {}),
        ),
        patch("app.services.pre_market_scan._detect", side_effect=ScanError("boom")),
        patch("app.services.pre_market_scan.scan_last_success_timestamp") as mock_ts,
        patch("app.services.pre_market_scan.scan_failed_tickers_ratio") as mock_ratio,
        patch("app.services.pre_market_scan.scan_duration_seconds") as mock_dur,
    ):
        mock_ts_lbl = MagicMock()
        mock_ts.labels.return_value = mock_ts_lbl
        mock_ratio_lbl = MagicMock()
        mock_ratio.labels.return_value = mock_ratio_lbl
        mock_dur_lbl = MagicMock()
        mock_dur.labels.return_value = mock_dur_lbl

        from app.services.pre_market_scan import run_pre_market_scan

        results = asyncio.run(run_pre_market_scan([ticker], db, event_date=event_date))

    assert results == []
    # last-success must NOT advance on a total failure
    mock_ts_lbl.set.assert_not_called()
    # every ticker failed -> ratio 1.0, still observed
    mock_ratio_lbl.set.assert_called_once()
    assert mock_ratio_lbl.set.call_args[0][0] == 1.0
    # duration is always recorded
    mock_dur_lbl.observe.assert_called_once()


def test_pre_market_scan_records_duration_when_persist_raises(db):
    """If _persist raises, scan_duration_seconds must still be observed (try/finally)
    and last-success must NOT be marked."""
    import pytest

    with (
        patch.object(
            ScannerService, "_get_batch_enrichment_data", return_value=({}, {}, {})
        ),
        patch(
            "app.services.pre_market_scan._persist",
            side_effect=RuntimeError("db down"),
        ),
        patch("app.services.pre_market_scan.scan_last_success_timestamp") as mock_ts,
        patch("app.services.pre_market_scan.scan_duration_seconds") as mock_dur,
    ):
        mock_ts_lbl = MagicMock()
        mock_ts.labels.return_value = mock_ts_lbl
        mock_dur_lbl = MagicMock()
        mock_dur.labels.return_value = mock_dur_lbl

        from app.services.pre_market_scan import run_pre_market_scan

        with pytest.raises(RuntimeError):
            asyncio.run(run_pre_market_scan([], db))

    # duration recorded despite the exception
    mock_dur_lbl.observe.assert_called_once()
    # a failed run must not be marked successful
    mock_ts_lbl.set.assert_not_called()
