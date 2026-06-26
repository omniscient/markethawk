"""
Unit tests for quality_gate_evidence — generate_missing_bars_issues and
generate_insufficient_lookback_issues.

Uses MagicMock for the DB session (service-layer unit tests, not full-pipeline
regression tests). Each test exercises one scenario from AC-6.
"""
from unittest.mock import MagicMock

import pytest

from app.services.quality_gate_evidence import (
    GateIssue,
    generate_insufficient_lookback_issues,
    generate_missing_bars_issues,
)


# --- helpers ----------------------------------------------------------------


def _cfg(timespans: list) -> MagicMock:
    cfg = MagicMock()
    cfg.data_requirements = {"timespans": timespans}
    return cfg


def _flat_cfg() -> MagicMock:
    """Flat data_requirements shape — no timespans key."""
    cfg = MagicMock()
    cfg.data_requirements = {"timespan": "day", "min_bars": 260}
    return cfg


def _db_with_report(report_data, ticker_rows=None, scalar_side_effect=None) -> MagicMock:
    """Build a MagicMock db that returns a cached report and optional bar counts."""
    report_mock = MagicMock()
    report_mock.report_data = report_data

    filter_mock = MagicMock()
    filter_mock.first.return_value = report_mock
    if ticker_rows is not None:
        filter_mock.all.return_value = ticker_rows
    if scalar_side_effect is not None:
        filter_mock.scalar.side_effect = scalar_side_effect
    else:
        filter_mock.scalar.return_value = 0

    db = MagicMock()
    db.query.return_value.filter.return_value = filter_mock
    return db


# --- GateIssue dataclass ----------------------------------------------------


def test_gate_issue_fields_are_populated():
    issue = GateIssue(
        issue_code="missing_bars",
        ticker="AAPL",
        timespan="minute",
        multiplier=1,
        observed=100,
        required=500,
    )
    assert issue.issue_code == "missing_bars"
    assert issue.ticker == "AAPL"
    assert issue.observed == 100
    assert issue.required == 500


# --- generate_missing_bars_issues -------------------------------------------


def test_missing_bars_flat_shape_returns_empty():
    """Flat data_requirements (no timespans key) -> [] with no DB calls."""
    db = MagicMock()
    issues = generate_missing_bars_issues(db, 1, _flat_cfg(), ticker="AAPL")
    assert issues == []


def test_missing_bars_per_ticker_uses_report_cache():
    """Per-ticker mode: uses report_data cache, emits issue when actual < expected."""
    report_data = {
        "tickers": [
            {
                "ticker": "AAPL",
                "timespan": "minute",
                "multiplier": 1,
                "actual_bars": 200,
                "expected_bars": 500,
            }
        ]
    }
    cfg = _cfg([{"timespan": "minute", "multiplier": 1, "lookback_days": 10}])
    db = _db_with_report(report_data)

    issues = generate_missing_bars_issues(db, 1, cfg, ticker="AAPL")

    assert len(issues) == 1
    assert issues[0].issue_code == "missing_bars"
    assert issues[0].ticker == "AAPL"
    assert issues[0].observed == 200
    assert issues[0].required == 500


def test_missing_bars_no_issue_when_actual_meets_expected():
    """No issue when actual_bars >= expected_bars in cache."""
    report_data = {
        "tickers": [
            {
                "ticker": "AAPL",
                "timespan": "minute",
                "multiplier": 1,
                "actual_bars": 600,
                "expected_bars": 500,
            }
        ]
    }
    cfg = _cfg([{"timespan": "minute", "multiplier": 1, "lookback_days": 10}])
    db = _db_with_report(report_data)

    issues = generate_missing_bars_issues(db, 1, cfg, ticker="AAPL")
    assert issues == []


def test_missing_bars_universe_wide_partial_coverage():
    """Universe-wide (ticker=None): emits issue only for AAPL (below threshold), not MSFT."""
    report_data = {
        "tickers": [
            {
                "ticker": "AAPL",
                "timespan": "minute",
                "multiplier": 1,
                "actual_bars": 200,
                "expected_bars": 500,
            },
            {
                "ticker": "MSFT",
                "timespan": "minute",
                "multiplier": 1,
                "actual_bars": 600,
                "expected_bars": 500,
            },
        ]
    }
    cfg = _cfg([{"timespan": "minute", "multiplier": 1, "lookback_days": 10}])
    ticker_rows = [MagicMock(ticker="AAPL"), MagicMock(ticker="MSFT")]
    db = _db_with_report(report_data, ticker_rows=ticker_rows)

    issues = generate_missing_bars_issues(db, 1, cfg, ticker=None)

    assert len(issues) == 1
    assert issues[0].ticker == "AAPL"


def test_missing_bars_fallback_direct_db_when_no_report():
    """When report_data is absent, falls back to direct SELECT count(*) for actual_bars."""
    cfg = _cfg([{"timespan": "day", "multiplier": 1, "lookback_days": 90}])
    db = _db_with_report(report_data=None, scalar_side_effect=[10])

    issues = generate_missing_bars_issues(db, 1, cfg, ticker="AAPL")

    # expected_bars = 90 * 1 bar/day = 90; actual = 10 -> issue emitted
    assert len(issues) == 1
    assert issues[0].observed == 10
    assert issues[0].required == 90


# --- generate_insufficient_lookback_issues ----------------------------------


def test_insufficient_lookback_flat_shape_returns_empty():
    """Flat data_requirements (no timespans key) -> []."""
    db = MagicMock()
    assert generate_insufficient_lookback_issues(db, 1, _flat_cfg(), ticker="AAPL") == []


def test_insufficient_lookback_no_min_bars_returns_empty():
    """Timespan with no min_bars field -> no issue emitted, regardless of bar count."""
    cfg = _cfg([{"timespan": "minute", "multiplier": 1, "lookback_days": 10}])
    db = MagicMock()
    db.query.return_value.filter.return_value.scalar.return_value = 0

    issues = generate_insufficient_lookback_issues(db, 1, cfg, ticker="AAPL")
    assert issues == []


def test_insufficient_lookback_per_ticker_emits_when_below_min_bars():
    """Per-ticker: emits issue when actual bar count < min_bars."""
    cfg = _cfg([{"timespan": "day", "multiplier": 1, "lookback_days": 90, "min_bars": 260}])
    db = MagicMock()
    db.query.return_value.filter.return_value.scalar.return_value = 50  # actual bars

    issues = generate_insufficient_lookback_issues(db, 1, cfg, ticker="AAPL")

    assert len(issues) == 1
    assert issues[0].issue_code == "insufficient_lookback"
    assert issues[0].ticker == "AAPL"
    assert issues[0].observed == 50
    assert issues[0].required == 260


def test_insufficient_lookback_universe_wide_partial_coverage():
    """Universe-wide (ticker=None): AAPL fails (50 < 260), MSFT passes (300 >= 260)."""
    cfg = _cfg([{"timespan": "day", "multiplier": 1, "lookback_days": 90, "min_bars": 260}])
    ticker_rows = [MagicMock(ticker="AAPL"), MagicMock(ticker="MSFT")]

    filter_mock = MagicMock()
    filter_mock.all.return_value = ticker_rows
    filter_mock.scalar.side_effect = [50, 300]  # AAPL -> 50, MSFT -> 300

    db = MagicMock()
    db.query.return_value.filter.return_value = filter_mock

    issues = generate_insufficient_lookback_issues(db, 1, cfg, ticker=None)

    assert len(issues) == 1
    assert issues[0].ticker == "AAPL"
    assert issues[0].observed == 50
    assert issues[0].required == 260
