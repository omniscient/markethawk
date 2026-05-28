"""
Tests for ChartIndicatorsService.add_indicators — pure DataFrame transformation,
no DB or external calls required.
"""

import numpy as np
import pandas as pd
import pytest

from app.services.chart_indicators import ChartIndicatorsService


def _make_df(n=30, start="2024-01-15 09:30", freq="1min"):
    """Synthetic OHLCV DataFrame with UTC DatetimeIndex."""
    idx = pd.date_range(start=start, periods=n, freq=freq, tz="UTC")
    rng = np.random.default_rng(42)
    close = 100.0 + rng.normal(0, 0.5, n).cumsum()
    high = close + rng.uniform(0.1, 0.5, n)
    low = close - rng.uniform(0.1, 0.5, n)
    volume = rng.integers(10_000, 50_000, n).astype(float)
    return pd.DataFrame(
        {"Open": close, "High": high, "Low": low, "Close": close, "Volume": volume},
        index=idx,
    )


def test_returns_dataframe_with_same_length():
    df = _make_df(30)
    result = ChartIndicatorsService.add_indicators(df)
    assert len(result) == len(df)


def test_empty_dataframe_returned_unchanged():
    empty = pd.DataFrame(columns=["Open", "High", "Low", "Close", "Volume"])
    result = ChartIndicatorsService.add_indicators(empty)
    assert result.empty


def test_vwap_intraday_column_present():
    df = _make_df(30)
    result = ChartIndicatorsService.add_indicators(df)
    assert "vwap_intraday" in result.columns


def test_vwap_first_bar_equals_close_times_volume_over_volume():
    df = _make_df(30)
    result = ChartIndicatorsService.add_indicators(df)
    # First bar VWAP = Close[0] * Volume[0] / Volume[0] = Close[0]
    assert (
        pytest.approx(result["vwap_intraday"].iloc[0], rel=1e-4) == df["Close"].iloc[0]
    )


def test_marker_type_column_present():
    df = _make_df(30)
    result = ChartIndicatorsService.add_indicators(df)
    assert "marker_type" in result.columns


def test_marker_type_values_are_valid():
    df = _make_df(60)
    result = ChartIndicatorsService.add_indicators(df)
    valid = {None, "swipe", "flush", "high_vol"}
    for val in result["marker_type"]:
        assert val in valid, f"Unexpected marker_type value: {val!r}"


def test_intermediate_columns_dropped():
    df = _make_df(30)
    result = ChartIndicatorsService.add_indicators(df)
    dropped = [
        "cum_C_V",
        "TodayVolume",
        "Vol_MA_5",
        "fastVolumeAverage",
        "ATR_1",
        "swipe",
        "flush",
    ]
    for col in dropped:
        assert col not in result.columns, f"Column {col!r} should have been dropped"


def test_index_converted_back_to_utc():
    df = _make_df(30)
    result = ChartIndicatorsService.add_indicators(df)
    assert str(result.index.tz) == "UTC"


def test_does_not_mutate_input():
    df = _make_df(30)
    original_cols = set(df.columns)
    ChartIndicatorsService.add_indicators(df)
    assert set(df.columns) == original_cols
