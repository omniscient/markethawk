from datetime import datetime, timedelta
from decimal import Decimal
from unittest.mock import MagicMock, patch

import numpy as np
import pandas as pd

from app.services.stock_data import StockDataService


# ── helpers ────────────────────────────────────────────────────────────────

def _mock_db_futures_lookup(is_futures: bool):
    db = MagicMock()
    mock_q = MagicMock()
    mock_q.filter.return_value = mock_q
    mock_q.first.return_value = MagicMock() if is_futures else None
    db.query.return_value = mock_q
    return db


def _make_df(rows=10):
    base = datetime(2026, 1, 1)
    ts = [base + timedelta(days=i) for i in range(rows)]
    return pd.DataFrame(
        {
            "Open": np.ones(rows) * 100.0,
            "High": np.ones(rows) * 110.0,
            "Low": np.ones(rows) * 90.0,
            "Close": np.ones(rows) * 105.0,
            "Volume": np.ones(rows, dtype=int) * 10000,
            "vwap": np.ones(rows) * 102.0,
            "transactions": np.ones(rows, dtype=int) * 500,
        },
        index=pd.DatetimeIndex(ts, name="Date"),
    )


# ── is_futures_ticker ──────────────────────────────────────────────────────

def test_is_futures_ticker_true():
    assert StockDataService.is_futures_ticker(_mock_db_futures_lookup(True), "ES") is True


def test_is_futures_ticker_false():
    assert StockDataService.is_futures_ticker(_mock_db_futures_lookup(False), "AAPL") is False


# ── get_historical_enriched ────────────────────────────────────────────────

def test_enriched_returns_empty_when_no_data():
    db = _mock_db_futures_lookup(False)
    with patch.object(StockDataService, "get_historical_from_db", return_value=pd.DataFrame()):
        result = StockDataService.get_historical_enriched(db, "AAPL", "30d", "day", 1)
    assert result.empty


def test_enriched_coerces_decimal_to_float():
    db = _mock_db_futures_lookup(False)
    df = _make_df(5)
    df["Close"] = df["Close"].map(lambda x: Decimal(str(round(float(x), 2))))
    with patch.object(StockDataService, "get_historical_from_db", return_value=df):
        result = StockDataService.get_historical_enriched(db, "AAPL", "30d", "day", 1)
    assert result["Close"].dtype == float


def test_enriched_no_indicators_for_day_timespan():
    db = _mock_db_futures_lookup(False)
    df = _make_df(10)
    with patch.object(StockDataService, "get_historical_from_db", return_value=df), \
         patch("app.services.stock_data.ChartIndicatorsService") as mock_ci:
        StockDataService.get_historical_enriched(db, "AAPL", "30d", "day", 1)
    mock_ci.add_indicators.assert_not_called()


def test_enriched_adds_indicators_for_minute_under_limit():
    db = _mock_db_futures_lookup(False)
    df = _make_df(100)
    with patch.object(StockDataService, "get_historical_from_db", return_value=df), \
         patch("app.services.stock_data.ChartIndicatorsService") as mock_ci:
        mock_ci.add_indicators.return_value = df
        StockDataService.get_historical_enriched(db, "AAPL", "30d", "minute", 1)
    mock_ci.add_indicators.assert_called_once_with(df, is_intraday=True)


def test_enriched_no_indicators_for_minute_over_limit():
    db = _mock_db_futures_lookup(False)
    df = _make_df(3001)  # INDICATOR_ROW_LIMIT = 3000
    with patch.object(StockDataService, "get_historical_from_db", return_value=df), \
         patch("app.services.stock_data.ChartIndicatorsService") as mock_ci:
        StockDataService.get_historical_enriched(db, "AAPL", "30d", "minute", 1)
    mock_ci.add_indicators.assert_not_called()


def test_enriched_truncates_at_max_datapoints():
    db = _mock_db_futures_lookup(False)
    # Use minute-level timestamps to avoid pandas nanosecond overflow on 500k+ daily rows
    base = datetime(2020, 1, 1)
    n = 500_001
    ts = [base + timedelta(minutes=i) for i in range(n)]
    df = pd.DataFrame(
        {
            "Open": np.ones(n) * 100.0,
            "Close": np.ones(n) * 105.0,
            "Volume": np.ones(n, dtype=int) * 1000,
        },
        index=pd.DatetimeIndex(ts, name="Date"),
    )
    with patch.object(StockDataService, "get_historical_from_db", return_value=df):
        result = StockDataService.get_historical_enriched(db, "AAPL", "all", "day", 1)
    assert len(result) == 500_000


def test_enriched_dispatches_to_futures_path():
    db = _mock_db_futures_lookup(True)
    df = _make_df(5)
    with patch.object(StockDataService, "get_futures_historical_from_db", return_value=df) as mock_fut, \
         patch.object(StockDataService, "get_historical_from_db") as mock_stock:
        StockDataService.get_historical_enriched(db, "ES", "30d", "day", 1)
    mock_fut.assert_called_once()
    mock_stock.assert_not_called()
