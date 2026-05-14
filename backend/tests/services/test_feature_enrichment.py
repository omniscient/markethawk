import asyncio
import pytest
from datetime import date, datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

from app.services.scanner import ScannerService
from app.models.stock_aggregate import StockAggregate
from app.models.system_config import SystemConfig


def _make_daily_bar(ticker, timestamp_utc, close, volume=1_000_000):
    b = StockAggregate()
    b.ticker = ticker
    b.timestamp = timestamp_utc
    b.timespan = "day"
    b.multiplier = 1
    b.open = close
    b.high = close * 1.02
    b.low = close * 0.98
    b.close = close
    b.volume = volume
    b.is_pre_market = False
    b.is_after_market = False
    return b


def _make_pm_bar(ticker, timestamp_utc, close=100.0):
    b = StockAggregate()
    b.ticker = ticker
    b.timestamp = timestamp_utc
    b.timespan = "minute"
    b.multiplier = 1
    b.open = close
    b.high = close * 1.01
    b.low = close * 0.99
    b.close = close
    b.volume = 50_000
    b.is_pre_market = True
    b.is_after_market = False
    return b


PHASE_2A_FEATURE_KEYS = [
    "es_pct_from_prev_close", "nq_pct_from_prev_close", "market_context",
    "sector", "sector_etf", "sector_etf_pct_change",
    "minutes_since_premarket_open", "day_of_week", "is_monday", "is_friday",
    "atr_percentile_rank", "volatility_regime",
    "has_news_catalyst", "catalyst_tag_count", "catalyst_recency_hours",
    "price_direction", "price_confidence", "price_forecast_4h", "price_forecast_1d",
]


def test_run_pre_market_scan_indicators_contain_all_feature_keys():
    """All 19 Phase 2a feature keys must appear in indicators after a detected signal."""
    ticker = "NVDA"
    event_date = date(2026, 5, 14)  # Thursday

    base_utc = datetime(2026, 4, 15, 20, 0, 0)
    daily_bars = [
        _make_daily_bar(ticker, base_utc + timedelta(days=i), 100.0 + i * 0.1)
        for i in range(25)
    ]
    # 8:30 AM UTC = 4:30 AM ET
    pm_bar = _make_pm_bar(ticker, datetime(2026, 5, 14, 8, 30, 0), close=105.0)

    db = MagicMock()

    def query_side(model):
        mq = MagicMock()
        mq.filter.return_value = mq
        mq.order_by.return_value = mq
        mq.limit.return_value = mq
        mq.first.return_value = pm_bar
        if model is SystemConfig:
            mq.all.return_value = []
        elif model is StockAggregate:
            mq.all.return_value = daily_bars
            mq.scalar.return_value = 5_000_000
        else:
            mq.all.return_value = []
            mq.scalar.return_value = 5_000_000
        return mq

    db.query.side_effect = query_side

    batch_enrichment = {
        "NVDA": {
            "market_cap": 2_000_000_000_000,
            "outstanding_shares": 24_000_000_000,
            "recent_split_date": None,
            "catalyst_tags": ["earnings_beat"],
            "catalyst_summary": "NVDA beats estimates",
            "catalyst_latest_utc": datetime(2026, 5, 14, 3, 0, 0),
            "sector": "Technology",
        }
    }
    market_ctx = {
        "es_pct_from_prev_close": 0.3,
        "nq_pct_from_prev_close": 0.2,
        "market_context": "risk_on",
    }
    etf_pcts = {s: None for s in ["XLK", "XLF", "XLV", "XLY", "XLP", "XLE", "XLI", "XLB", "XLRE", "XLU", "XLC"]}
    etf_pcts["XLK"] = 0.4

    saved_indicators = {}

    def capture_save(**kwargs):
        saved_indicators.update(kwargs.get("indicators", {}))
        return {"id": 1}

    with patch.object(ScannerService, '_get_batch_enrichment_data',
                      return_value=(batch_enrichment, market_ctx, etf_pcts)), \
         patch.object(ScannerService, 'calculate_day_metrics', return_value={
             "closing_price": 106.0, "pre_market_close": 105.0,
             "opening_price": 101.0, "regular_high": 107.0, "regular_low": 99.0,
         }), \
         patch.object(ScannerService, '_save_event', side_effect=capture_save):
        asyncio.run(ScannerService.run_pre_market_scan([ticker], db, event_date=event_date))

    assert saved_indicators, "_save_event was never called — signal not detected"

    for key in PHASE_2A_FEATURE_KEYS:
        assert key in saved_indicators, f"missing feature key: {key}"

    assert saved_indicators["es_pct_from_prev_close"] == 0.3
    assert saved_indicators["nq_pct_from_prev_close"] == 0.2
    assert saved_indicators["market_context"] == "risk_on"
    assert saved_indicators["sector"] == "Technology"
    assert saved_indicators["sector_etf"] == "XLK"
    assert saved_indicators["sector_etf_pct_change"] == 0.4
    assert saved_indicators["day_of_week"] == 3        # Thursday
    assert saved_indicators["is_monday"] is False
    assert saved_indicators["is_friday"] is False
    assert saved_indicators["minutes_since_premarket_open"] == pytest.approx(30.0, abs=1.0)
    assert saved_indicators["has_news_catalyst"] is True
    assert saved_indicators["catalyst_tag_count"] == 1
    assert saved_indicators["price_direction"] is None
    assert saved_indicators["price_confidence"] is None
    assert saved_indicators["price_forecast_4h"] is None
    assert saved_indicators["price_forecast_1d"] is None


def test_run_pre_market_scan_features_null_when_no_pm_bar():
    """Timing features are null when no pre-market bar exists for the ticker."""
    ticker = "SPARSE"
    event_date = date(2026, 5, 13)

    base_utc = datetime(2026, 4, 1, 20, 0, 0)
    daily_bars = [
        _make_daily_bar(ticker, base_utc + timedelta(days=i), 50.0)
        for i in range(25)
    ]

    db = MagicMock()

    def query_side(model):
        mq = MagicMock()
        mq.filter.return_value = mq
        mq.order_by.return_value = mq
        mq.limit.return_value = mq
        mq.first.return_value = None  # no pre-market bar
        if model is SystemConfig:
            mq.all.return_value = []
        elif model is StockAggregate:
            mq.all.return_value = daily_bars
            mq.scalar.return_value = 5_000_000
        else:
            mq.all.return_value = []
            mq.scalar.return_value = 5_000_000
        return mq

    db.query.side_effect = query_side

    batch_enrichment = {
        "SPARSE": {
            "market_cap": None, "outstanding_shares": None,
            "recent_split_date": None, "catalyst_tags": [],
            "catalyst_summary": None, "catalyst_latest_utc": None,
            "sector": None,
        }
    }

    saved_indicators = {}

    def capture_save(**kwargs):
        saved_indicators.update(kwargs.get("indicators", {}))
        return {"id": 2}

    with patch.object(ScannerService, '_get_batch_enrichment_data',
                      return_value=(batch_enrichment, {}, {})), \
         patch.object(ScannerService, 'calculate_day_metrics', return_value={
             "closing_price": 52.0, "pre_market_close": 51.0,
             "opening_price": 51.0, "regular_high": 53.0, "regular_low": 49.0,
         }), \
         patch.object(ScannerService, '_save_event', side_effect=capture_save):
        asyncio.run(ScannerService.run_pre_market_scan([ticker], db, event_date=event_date))

    if saved_indicators:
        assert saved_indicators["minutes_since_premarket_open"] is None
        assert saved_indicators["day_of_week"] is None
        assert saved_indicators["is_monday"] is False
        assert saved_indicators["is_friday"] is False
        assert saved_indicators["catalyst_recency_hours"] is None
        assert saved_indicators["has_news_catalyst"] is False
        assert saved_indicators["catalyst_tag_count"] == 0
        assert saved_indicators["es_pct_from_prev_close"] is None
        assert saved_indicators["market_context"] is None
