"""Unit tests for the liquidity_hunt scanner."""
import pytest
from app.services.liquidity_hunt import _evaluate_criteria, DEFAULT_CONFIG

# Baseline fixture representing a ticker with 20 days of history
BASELINES = {
    "avg_pre_vol_20d": 35_000,
    "avg_post_vol_20d": 30_000,
    "avg_regular_vol_20d": 950_000,
    "avg_total_daily_vol_20d": 1_000_000,
    "avg_regular_range_pct_20d": 0.020,   # 2% average daily range
    "days_available": 20,
}

# Kwargs for a clean "pre" fire — all six criteria satisfied
CLEAN_PRE = dict(
    session="pre",
    session_vol=350_000,    # c1: 350k/35k=10x ≥ 4 ✓  c2: 350k/1M=35% ≥ 30% ✓  c6: >50k ✓
    session_high=12.11,     # c3: (12.11-11.00)/11.00 = 10.09% ≥ 10% ✓
    reference_close=11.00,
    regular_vol=900_000,    # c4: 900k/950k = 0.947 ≤ 1.2 ✓
    regular_high=11.20,
    regular_low=10.90,
    regular_open=11.05,     # c5: (11.20-10.90)/11.05=2.71% → ratio 1.36 ≤ 1.5 ✓
    baselines=BASELINES,
    config=None,
)


def test_pre_variant_fires():
    fires, indicators, criteria = _evaluate_criteria(**CLEAN_PRE)
    assert fires is True
    assert indicators["session"] == "pre"
    assert all(criteria.values()), f"All criteria should be True, got {criteria}"


def test_c2_materiality_fails_when_vol_too_small():
    """200k/1M = 20% < 30% — materiality criterion fails."""
    fires, _, criteria = _evaluate_criteria(
        **{**CLEAN_PRE, "session_vol": 200_000}
    )
    assert fires is False
    assert criteria["volume_materiality"] is False


def test_c3_spike_fails_when_less_than_10_pct():
    """6% spike — does not meet the 10% threshold."""
    fires, _, criteria = _evaluate_criteria(
        **{**CLEAN_PRE, "session_high": 11.66}   # (11.66-11.00)/11.00 = 6%
    )
    assert fires is False
    assert criteria["session_spike"] is False


def test_c4_fails_when_regular_vol_exceeds_threshold():
    """2× regular vol — day was not quiet."""
    fires, _, criteria = _evaluate_criteria(
        **{**CLEAN_PRE, "regular_vol": 2_000_000}  # 2M/950k = 2.1 > 1.2
    )
    assert fires is False
    assert criteria["quiet_regular_vol"] is False


def test_c6_fails_when_below_absolute_floor():
    """40k shares < 50k floor — only c6 fails, all others pass."""
    isolated_baselines = {
        **BASELINES,
        "avg_pre_vol_20d": 1_000,           # 40k/1k = 40x ≥ 4 ✓ (c1 passes)
        "avg_total_daily_vol_20d": 100_000, # 40k/100k = 40% ≥ 30% ✓ (c2 passes)
    }
    fires, _, criteria = _evaluate_criteria(
        **{**CLEAN_PRE, "session_vol": 40_000, "baselines": isolated_baselines}
    )
    assert fires is False
    assert criteria["volume_floor"] is False
    assert criteria["volume_ratio"] is True
    assert criteria["volume_materiality"] is True


def test_c5_fails_when_range_too_wide():
    """Wide intraday range — day was volatile."""
    fires, _, criteria = _evaluate_criteria(
        **{**CLEAN_PRE, "regular_high": 13.50, "regular_low": 8.50}
        # range = (13.50-8.50)/11.05 = 45.2% → ratio = 45.2%/2% = 22.6 > 1.5
    )
    assert fires is False
    assert criteria["quiet_regular_range"] is False


def test_zero_session_baseline_fires_when_floor_and_materiality_pass():
    """avg_pre_vol_20d=0: ratio criterion is trivially satisfied; other checks carry the load."""
    zero_baselines = {
        **BASELINES,
        "avg_pre_vol_20d": 0,
        "avg_total_daily_vol_20d": 200_000,   # 75k/200k = 37.5% ≥ 30%
        "avg_regular_vol_20d": 190_000,
    }
    fires, indicators, criteria = _evaluate_criteria(
        session="pre",
        session_vol=75_000,       # > 50k floor ✓  and 37.5% of daily ✓
        session_high=12.11,
        reference_close=11.00,
        regular_vol=180_000,      # 180k/190k = 0.95 ≤ 1.2 ✓
        regular_high=11.20,
        regular_low=10.90,
        regular_open=11.05,
        baselines=zero_baselines,
        config=None,
    )
    assert fires is True
    assert criteria["volume_ratio"] is True   # trivially satisfied
    assert indicators["session_volume_ratio"] is None  # signals "infinite"


def test_post_variant_fires():
    """After-market variant routes to avg_post_vol_20d (not avg_pre_vol_20d)."""
    # session_vol=130k: 130k/30k=4.33x passes post threshold but 130k/35k=3.71x fails pre
    post_baselines = {
        **BASELINES,
        "avg_total_daily_vol_20d": 400_000,  # 130k/400k=32.5% ≥ 30% ✓
    }
    fires, indicators, criteria = _evaluate_criteria(
        session="post",
        session_vol=130_000,
        session_high=12.11,
        reference_close=11.00,
        regular_vol=900_000,
        regular_high=11.20,
        regular_low=10.90,
        regular_open=11.05,
        baselines=post_baselines,
        config=None,
    )
    assert fires is True
    assert indicators["session"] == "post"
    assert all(criteria.values())


def test_c1_fails_for_post_when_after_market_vol_too_low():
    """Post variant: 60k / 30k = 2x < 4x threshold."""
    fires, _, criteria = _evaluate_criteria(
        session="post",
        session_vol=60_000,       # 60k/30k = 2x < 4 ✗  (also: 60k/1M = 6% < 30%)
        session_high=12.11,
        reference_close=11.00,
        regular_vol=900_000,
        regular_high=11.20,
        regular_low=10.90,
        regular_open=11.05,
        baselines=BASELINES,
        config=None,
    )
    assert fires is False
    assert criteria["volume_ratio"] is False
    assert criteria["volume_materiality"] is False


# ─── DB helper tests ───────────────────────────────────────────────────────

from datetime import date as _date, datetime as _datetime, timezone as _tz
from datetime import timedelta
from unittest.mock import MagicMock
from app.models.stock_aggregate import StockAggregate
from app.services.liquidity_hunt import (
    _get_session_metrics,
    _get_prior_day_close,
    _get_event_date_regular_close,
)


def _make_minute_bar(ticker, ts_utc, open_, high, low, close, volume,
                     is_pre=False, is_after=False):
    b = StockAggregate()
    b.ticker = ticker
    b.timestamp = ts_utc
    b.timespan = "minute"
    b.multiplier = 1
    b.open, b.high, b.low, b.close = open_, high, low, close
    b.volume = volume
    b.is_pre_market = is_pre
    b.is_after_market = is_after
    return b


def _make_day_bar(ticker, ts_utc, close, volume):
    b = StockAggregate()
    b.ticker = ticker
    b.timestamp = ts_utc
    b.timespan = "day"
    b.multiplier = 1
    b.open = b.high = b.low = b.close = close
    b.volume = volume
    b.is_pre_market = False
    b.is_after_market = False
    return b


def _make_db_returning(rows):
    """Return a mock Session whose .query().filter().order_by().all() returns rows."""
    db = MagicMock()
    mock_q = MagicMock()
    mock_q.filter.return_value = mock_q
    mock_q.order_by.return_value = mock_q
    mock_q.limit.return_value = mock_q
    mock_q.all.return_value = rows
    mock_q.first.return_value = rows[0] if rows else None
    db.query.return_value = mock_q
    return db


EVENT_DATE = _date(2025, 6, 10)
# 2025-06-10 09:00 ET = 13:00 UTC
_PRE_TS = _datetime(2025, 6, 10, 8, 0, tzinfo=_tz.utc).replace(tzinfo=None)    # 4 AM ET
_REG_TS = _datetime(2025, 6, 10, 14, 0, tzinfo=_tz.utc).replace(tzinfo=None)   # 10 AM ET
_POST_TS = _datetime(2025, 6, 10, 21, 0, tzinfo=_tz.utc).replace(tzinfo=None)  # 5 PM ET


def test_get_session_metrics_returns_correct_buckets():
    pre_bar = _make_minute_bar("TEST", _PRE_TS, 10.0, 12.0, 9.9, 11.8, 200_000, is_pre=True)
    reg_bar = _make_minute_bar("TEST", _REG_TS, 11.8, 12.1, 11.5, 11.9, 900_000)
    post_bar = _make_minute_bar("TEST", _POST_TS, 11.9, 13.0, 11.8, 12.5, 150_000, is_after=True)

    db = _make_db_returning([pre_bar, reg_bar, post_bar])
    metrics = _get_session_metrics(db, "TEST", EVENT_DATE)

    assert metrics is not None
    assert metrics["pre_vol"] == 200_000
    assert metrics["pre_high"] == 12.0
    assert metrics["regular_vol"] == 900_000
    assert metrics["regular_high"] == 12.1
    assert metrics["regular_low"] == 11.5
    assert metrics["regular_open"] == 11.8
    assert metrics["regular_close"] == 11.9
    assert metrics["post_vol"] == 150_000
    assert metrics["post_high"] == 13.0


def test_get_session_metrics_returns_none_when_no_regular_bars():
    pre_bar = _make_minute_bar("TEST", _PRE_TS, 10.0, 12.0, 9.9, 11.8, 200_000, is_pre=True)
    db = _make_db_returning([pre_bar])
    assert _get_session_metrics(db, "TEST", EVENT_DATE) is None


def test_get_prior_day_close_uses_daily_bar():
    db = MagicMock()
    mock_q = MagicMock()
    mock_q.filter.return_value = mock_q
    mock_q.order_by.return_value = mock_q
    mock_q.limit.return_value = mock_q
    mock_q.first.return_value = (10.50,)
    db.query.return_value = mock_q

    result = _get_prior_day_close(db, "TEST", EVENT_DATE)
    assert result == 10.50


def test_get_prior_day_close_returns_none_when_no_history():
    db = MagicMock()
    mock_q = MagicMock()
    mock_q.filter.return_value = mock_q
    mock_q.order_by.return_value = mock_q
    mock_q.limit.return_value = mock_q
    mock_q.first.return_value = None
    db.query.return_value = mock_q

    assert _get_prior_day_close(db, "TEST", EVENT_DATE) is None


def test_get_prior_day_close_falls_back_to_minute_bar():
    """When no day bar exists, falls back to the last regular minute bar."""
    db = MagicMock()
    mock_q = MagicMock()
    mock_q.filter.return_value = mock_q
    mock_q.order_by.return_value = mock_q
    mock_q.limit.return_value = mock_q
    mock_q.first.side_effect = [None, (10.25,)]   # day query miss, minute query hit
    db.query.return_value = mock_q

    result = _get_prior_day_close(db, "TEST", EVENT_DATE)
    assert result == 10.25


def test_get_event_date_regular_close():
    db = MagicMock()
    mock_q = MagicMock()
    mock_q.filter.return_value = mock_q
    mock_q.order_by.return_value = mock_q
    mock_q.limit.return_value = mock_q
    mock_q.first.return_value = (11.90,)
    db.query.return_value = mock_q

    result = _get_event_date_regular_close(db, "TEST", EVENT_DATE)
    assert result == 11.90


# ─── _get_rolling_baselines tests ─────────────────────────────────────────────

from app.services.liquidity_hunt import _get_rolling_baselines


def _make_history(ticker, event_date, n_days, pre_vol, regular_vol, post_vol,
                  regular_high_pct=0.01):
    """
    Generate n_days of fake minute-bar history before event_date.
    Each day gets one pre bar, one regular bar, one post bar at 08:00/14:00/21:00 UTC.
    regular_high_pct: regular high = regular_open * (1 + regular_high_pct).
    """
    from zoneinfo import ZoneInfo
    _ET2 = ZoneInfo("America/New_York")
    bars = []
    for i in range(1, n_days + 1):
        d = event_date - timedelta(days=i)
        pre_ts = _datetime.combine(d, _datetime.min.time(), tzinfo=_ET2).replace(
            hour=8).astimezone(_tz.utc).replace(tzinfo=None)
        reg_ts = pre_ts.replace(hour=14)
        post_ts = pre_ts.replace(hour=21)

        bars.append(_make_minute_bar(ticker, pre_ts, 10.0, 10.5, 9.8, 10.3, pre_vol, is_pre=True))
        bars.append(_make_minute_bar(ticker, reg_ts, 10.3, 10.3 * (1 + regular_high_pct),
                                     10.3 * (1 - regular_high_pct), 10.2, regular_vol))
        bars.append(_make_minute_bar(ticker, post_ts, 10.2, 10.4, 10.1, 10.3, post_vol, is_after=True))
    return bars


def test_get_rolling_baselines_returns_correct_averages():
    bars = _make_history("TEST", EVENT_DATE, n_days=20,
                         pre_vol=40_000, regular_vol=800_000, post_vol=25_000)
    db = _make_db_returning(bars)
    result = _get_rolling_baselines(db, "TEST", EVENT_DATE)

    assert result is not None
    assert result["days_available"] == 20
    assert abs(result["avg_pre_vol_20d"] - 40_000) < 100
    assert abs(result["avg_regular_vol_20d"] - 800_000) < 100
    assert abs(result["avg_post_vol_20d"] - 25_000) < 100
    assert result["avg_total_daily_vol_20d"] > 800_000  # pre + regular + post


def test_get_rolling_baselines_returns_none_when_fewer_than_10_days():
    bars = _make_history("TEST", EVENT_DATE, n_days=8,
                         pre_vol=40_000, regular_vol=800_000, post_vol=25_000)
    db = _make_db_returning(bars)
    result = _get_rolling_baselines(db, "TEST", EVENT_DATE)
    assert result is None


def test_get_rolling_baselines_uses_at_most_20_days():
    """Even with 25 days of history, only the most recent 20 are averaged."""
    bars = _make_history("TEST", EVENT_DATE, n_days=25,
                         pre_vol=40_000, regular_vol=800_000, post_vol=25_000)
    db = _make_db_returning(bars)
    result = _get_rolling_baselines(db, "TEST", EVENT_DATE)
    assert result["days_available"] == 20


def test_get_rolling_baselines_lookback_starts_45_days_before_event():
    """Query lower bound is exactly event_date − 45 calendar days, expressed in naive UTC."""
    from datetime import time as _time2
    from zoneinfo import ZoneInfo as _ZI2

    db = MagicMock()
    mock_q = MagicMock()
    mock_q.filter.return_value = mock_q
    mock_q.order_by.return_value = mock_q
    mock_q.all.return_value = []
    db.query.return_value = mock_q

    _get_rolling_baselines(db, "TEST", EVENT_DATE)

    # All four conditions are passed in a single .filter() call.
    # Index 2: StockAggregate.timestamp >= lookback_start_utc
    lookback_expr = mock_q.filter.call_args.args[2]
    lookback_value = lookback_expr.right.value  # BindParameter.value

    expected = (
        _datetime.combine(
            EVENT_DATE - timedelta(days=45),
            _time2.min,
            tzinfo=_ZI2("America/New_York"),
        )
        .astimezone(_tz.utc)
        .replace(tzinfo=None)
    )
    assert lookback_value == expected, f"Expected {expected}, got {lookback_value}"


# ─── run_liquidity_hunt_scan tests ────────────────────────────────────────────

import asyncio
from unittest.mock import patch
from app.services.liquidity_hunt import run_liquidity_hunt_scan


# Shared baselines for scan-loop tests
_SCAN_BASELINES = {
    "avg_pre_vol_20d": 35_000,
    "avg_post_vol_20d": 30_000,
    "avg_regular_vol_20d": 950_000,
    "avg_total_daily_vol_20d": 1_000_000,
    "avg_regular_range_pct_20d": 0.020,
    "days_available": 20,
}

# Metrics for a day where both pre and post qualify
_CLEAN_METRICS = {
    "pre_vol": 350_000, "pre_high": 12.11,
    "regular_vol": 900_000, "regular_high": 11.20,
    "regular_low": 10.90, "regular_open": 11.05, "regular_close": 11.10,
    "post_vol": 350_000, "post_high": 12.25,
}


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


def _mock_enrichment():
    return {
        "market_cap": 500_000_000,
        "outstanding_shares": 50_000_000,
        "recent_split_date": None,
        "catalyst_tags": [],
        "catalyst_summary": None,
    }


def test_scan_fires_liquidity_hunt_pre():
    """Clean pre-market hunt: pre fires."""
    db = MagicMock()
    with patch("app.services.liquidity_hunt._get_session_metrics", return_value=_CLEAN_METRICS), \
         patch("app.services.liquidity_hunt._get_prior_day_close", return_value=11.00), \
         patch("app.services.liquidity_hunt._get_event_date_regular_close", return_value=11.10), \
         patch("app.services.liquidity_hunt._get_rolling_baselines", return_value=_SCAN_BASELINES), \
         patch("app.services.liquidity_hunt._get_enrichment", return_value=_mock_enrichment()), \
         patch("app.services.scanner.ScannerService._save_event", return_value={"id": 1}) as mock_save:

        results = _run(run_liquidity_hunt_scan(
            ["TEST"], db, start_date=EVENT_DATE, end_date=EVENT_DATE
        ))

    saved_types = [c.kwargs["scanner_type"] for c in mock_save.call_args_list]
    assert "liquidity_hunt_pre" in saved_types
    assert len(results) >= 1


def test_scan_fires_both_variants():
    """Both pre and post qualify on the same day — two separate events."""
    db = MagicMock()
    with patch("app.services.liquidity_hunt._get_session_metrics", return_value=_CLEAN_METRICS), \
         patch("app.services.liquidity_hunt._get_prior_day_close", return_value=11.00), \
         patch("app.services.liquidity_hunt._get_event_date_regular_close", return_value=11.10), \
         patch("app.services.liquidity_hunt._get_rolling_baselines", return_value=_SCAN_BASELINES), \
         patch("app.services.liquidity_hunt._get_enrichment", return_value=_mock_enrichment()), \
         patch("app.services.scanner.ScannerService._save_event", return_value={"id": 1}) as mock_save:

        _run(run_liquidity_hunt_scan(
            ["TEST"], db, start_date=EVENT_DATE, end_date=EVENT_DATE
        ))

    saved_types = [c.kwargs["scanner_type"] for c in mock_save.call_args_list]
    assert "liquidity_hunt_pre" in saved_types
    assert "liquidity_hunt_post" in saved_types


def test_scan_skips_ticker_when_sparse_history():
    """No events emitted when _get_rolling_baselines returns None."""
    db = MagicMock()
    with patch("app.services.liquidity_hunt._get_session_metrics", return_value=_CLEAN_METRICS), \
         patch("app.services.liquidity_hunt._get_prior_day_close", return_value=11.00), \
         patch("app.services.liquidity_hunt._get_event_date_regular_close", return_value=11.10), \
         patch("app.services.liquidity_hunt._get_rolling_baselines", return_value=None), \
         patch("app.services.liquidity_hunt._get_enrichment", return_value=_mock_enrichment()), \
         patch("app.services.scanner.ScannerService._save_event") as mock_save:

        results = _run(run_liquidity_hunt_scan(
            ["TEST"], db, start_date=EVENT_DATE, end_date=EVENT_DATE
        ))

    mock_save.assert_not_called()
    assert results == []


def test_scan_skips_ticker_when_no_prior_close():
    """No events when prior_day_close is unavailable."""
    db = MagicMock()
    with patch("app.services.liquidity_hunt._get_session_metrics", return_value=_CLEAN_METRICS), \
         patch("app.services.liquidity_hunt._get_prior_day_close", return_value=None), \
         patch("app.services.liquidity_hunt._get_event_date_regular_close", return_value=11.10), \
         patch("app.services.liquidity_hunt._get_rolling_baselines", return_value=_SCAN_BASELINES), \
         patch("app.services.liquidity_hunt._get_enrichment", return_value=_mock_enrichment()), \
         patch("app.services.scanner.ScannerService._save_event") as mock_save:

        results = _run(run_liquidity_hunt_scan(
            ["TEST"], db, start_date=EVENT_DATE, end_date=EVENT_DATE
        ))

    mock_save.assert_not_called()
    assert results == []


def test_split_in_lookback_flag():
    """Recent split within 28 days sets split_in_lookback=True in indicators."""
    split_date = EVENT_DATE - timedelta(days=10)
    enrichment_with_split = {**_mock_enrichment(), "recent_split_date": split_date.isoformat()}
    db = MagicMock()
    with patch("app.services.liquidity_hunt._get_session_metrics", return_value=_CLEAN_METRICS), \
         patch("app.services.liquidity_hunt._get_prior_day_close", return_value=11.00), \
         patch("app.services.liquidity_hunt._get_event_date_regular_close", return_value=11.10), \
         patch("app.services.liquidity_hunt._get_rolling_baselines", return_value=_SCAN_BASELINES), \
         patch("app.services.liquidity_hunt._get_enrichment", return_value=enrichment_with_split), \
         patch("app.services.scanner.ScannerService._save_event", return_value={"id": 1}) as mock_save:

        _run(run_liquidity_hunt_scan(
            ["TEST"], db, start_date=EVENT_DATE, end_date=EVENT_DATE
        ))

    indicators_list = [c.kwargs["indicators"] for c in mock_save.call_args_list]
    assert any(ind.get("split_in_lookback") is True for ind in indicators_list)
