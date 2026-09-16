"""
F-INPUT-02 (#380) — the centralized primitives are applied to the real request
models. These construct the actual schemas (no DB/auth needed) and assert the
hardening holds end-to-end at the Pydantic layer.
"""
from datetime import date

import pytest
from pydantic import ValidationError

from app.routers.universe import (
    DeleteAggregatesRequest,
    ExportAggregatesRequest,
)
from app.schemas.active_watchlist import ActiveWatchlistAdd
from app.schemas.alerts import ChannelConfig
from app.schemas.backtest import BacktestRunRequest
from app.schemas.news_preference import NewsPreferenceCreate
from app.schemas.outcome import BackfillRequest
from app.schemas.scanner import ScannerRangeRequest, ScannerRunRequest
from app.schemas.universe import StockUniverseCreate

# ── ScannerRangeRequest ───────────────────────────────────────────────────────


def test_scanner_range_accepts_valid():
    r = ScannerRangeRequest(
        ticker="aapl",
        scanner_types=["pre_market_volume"],
        start_date=date(2025, 1, 1),
        end_date=date(2025, 6, 1),
    )
    assert r.ticker == "AAPL"


def test_scanner_range_rejects_path_traversal_ticker():
    with pytest.raises(ValidationError):
        ScannerRangeRequest(
            ticker="../etc",
            scanner_types=["pre_market_volume"],
            start_date=date(2025, 1, 1),
            end_date=date(2025, 6, 1),
        )


def test_scanner_range_rejects_oversized_range():
    with pytest.raises(ValidationError):
        ScannerRangeRequest(
            ticker="AAPL",
            scanner_types=["pre_market_volume"],
            start_date=date(2020, 1, 1),
            end_date=date(2026, 1, 1),
        )


def test_scanner_range_rejects_extra_key():
    with pytest.raises(ValidationError):
        ScannerRangeRequest(
            ticker="AAPL",
            scanner_types=["pre_market_volume"],
            start_date=date(2025, 1, 1),
            end_date=date(2025, 6, 1),
            unexpected_key="evil",
        )


def test_scanner_run_rejects_extra_key_and_bad_ticker():
    with pytest.raises(ValidationError):
        ScannerRunRequest(tickers=["../x"])
    with pytest.raises(ValidationError):
        ScannerRunRequest(scanner_type="x", bogus=True)


# ── StockUniverseCreate ───────────────────────────────────────────────────────


def test_universe_create_accepts_valid():
    u = StockUniverseCreate(name="test", criteria={"sector": "tech"})
    assert u.criteria == {"sector": "tech"}


def test_universe_create_rejects_extra_key():
    with pytest.raises(ValidationError):
        StockUniverseCreate(name="test", criteria={"sector": "tech"}, evil="x")


def test_universe_create_rejects_oversized_criteria():
    with pytest.raises(ValidationError):
        StockUniverseCreate(name="test", criteria={"k": "x" * (64 * 1024 + 1)})


# ── Backtest / Backfill batch range ───────────────────────────────────────────


def test_backtest_accepts_five_year_range():
    r = BacktestRunRequest(
        scanner_type="pre_market_volume",
        strategy_id=1,
        universe_id=1,
        start_date=date(2021, 1, 1),
        end_date=date(2025, 1, 1),
    )
    assert r.end_date == date(2025, 1, 1)


def test_backtest_rejects_over_five_year_range():
    with pytest.raises(ValidationError):
        BacktestRunRequest(
            scanner_type="pre_market_volume",
            strategy_id=1,
            universe_id=1,
            start_date=date(2018, 1, 1),
            end_date=date(2026, 1, 1),
        )


def test_backfill_rejects_over_five_year_range():
    with pytest.raises(ValidationError):
        BackfillRequest(
            scanner_type="pre_market_volume",
            start_date=date(2018, 1, 1),
            end_date=date(2026, 1, 1),
        )


# ── ActiveWatchlistAdd dispatch ───────────────────────────────────────────────


def test_watchlist_stk_accepts_equity_ticker():
    w = ActiveWatchlistAdd(symbol="brk.b", security_type="STK")
    assert w.symbol == "BRK.B"
    assert w.exchange == "SMART"


def test_watchlist_fut_accepts_root_symbol():
    w = ActiveWatchlistAdd(symbol="es", security_type="FUT")
    assert w.symbol == "ES"
    assert w.exchange == "CME"


def test_watchlist_fut_rejects_dotted_suffix():
    with pytest.raises(ValidationError):
        ActiveWatchlistAdd(symbol="ES.U", security_type="FUT")


def test_watchlist_rejects_extra_key():
    with pytest.raises(ValidationError):
        ActiveWatchlistAdd(symbol="AAPL", evil="x")


# ── ChannelConfig https-only ──────────────────────────────────────────────────


def test_channel_config_accepts_https_webhook():
    c = ChannelConfig(webhook_url="https://hooks.example.com/x")
    assert str(c.webhook_url).startswith("https://")


def test_channel_config_rejects_http_webhook():
    with pytest.raises(ValidationError):
        ChannelConfig(webhook_url="http://hooks.example.com/x")


# ── inline universe-router request models ─────────────────────────────────────


def test_export_aggregates_rejects_bad_ticker():
    with pytest.raises(ValidationError):
        ExportAggregatesRequest(tickers=["../etc"])


def test_delete_aggregates_uppercases_ticker():
    r = DeleteAggregatesRequest(ticker="aapl", asset_class="stocks")
    assert r.ticker == "AAPL"


# ── NewsPreference tickers ────────────────────────────────────────────────────


def test_news_preference_rejects_bad_ticker():
    with pytest.raises(ValidationError):
        NewsPreferenceCreate(tracked_tickers=["../etc"])


def test_news_preference_uppercases_tickers():
    p = NewsPreferenceCreate(tracked_tickers=["aapl", "msft"])
    assert p.tracked_tickers == ["AAPL", "MSFT"]
