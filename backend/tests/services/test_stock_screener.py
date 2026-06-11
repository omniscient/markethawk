"""
Unit tests for StockScreener adapter.

Seeds TickerReference and StockMetric rows directly into the test DB
and asserts exact output from StockScreener.screen().
"""

import datetime

from sqlalchemy.orm import Session

from app.models.stock_metric import StockMetric
from app.models.ticker_reference import TickerReference


def _make_ticker(
    ticker: str,
    name: str = "Test Corp",
    market_cap: float = 1_000_000.0,
    sector: str = "Technology",
    primary_exchange: str = "XNAS",
    sic_code: str = "7372",
    description: str = "A software company",
    total_employees: float = 500.0,
    share_class_shares_outstanding: float = 10_000_000.0,
) -> TickerReference:
    return TickerReference(
        ticker=ticker,
        name=name,
        market_cap=market_cap,
        sector=sector,
        primary_exchange=primary_exchange,
        sic_code=sic_code,
        description=description,
        total_employees=total_employees,
        share_class_shares_outstanding=share_class_shares_outstanding,
    )


def _make_metric(
    ticker: str,
    volume: float = 1_000_000.0,
    close_price: float = 50.0,
    dt: datetime.date = None,
) -> StockMetric:
    return StockMetric(
        ticker=ticker,
        date=dt or datetime.date(2026, 1, 15),
        volume=volume,
        close_price=close_price,
    )


# ── StockScreener.screen — no filters ─────────────────────────────────────


def test_stock_screener_returns_all_with_empty_criteria(db: Session):
    """No criteria returns all tickers."""
    from app.services.stock_screener import StockScreener

    db.add(_make_ticker("AAPL"))
    db.add(_make_ticker("MSFT"))
    db.flush()

    results = StockScreener.screen(db, {"asset_classes": ["stocks"]})
    tickers = {r["ticker"] for r in results}
    assert "AAPL" in tickers
    assert "MSFT" in tickers


# ── StockScreener.screen — output shape ───────────────────────────────────


def test_stock_screener_output_shape(db: Session):
    """Each result dict has required keys with correct values."""
    from app.services.stock_screener import StockScreener

    db.add(_make_ticker("TSLA", name="Tesla Inc", market_cap=500_000.0, sector="Auto"))
    db.flush()

    results = StockScreener.screen(db, {"asset_classes": ["stocks"]})
    r = next(x for x in results if x["ticker"] == "TSLA")

    assert r["name"] == "Tesla Inc"
    assert r["market_cap"] == 500_000.0
    assert r["sector"] == "Auto"
    assert r["asset_class"] == "stocks"
    assert r["close_price"] is None
    assert r["volume"] is None


# ── StockScreener.screen — min_volume filter ──────────────────────────────


def test_stock_screener_min_volume_join(db: Session):
    """min_volume triggers JOIN with stock_metrics and filters correctly."""
    from app.services.stock_screener import StockScreener

    db.add(_make_ticker("HIGHVOL"))
    db.add(_make_ticker("LOWVOL"))
    db.flush()
    db.add(_make_metric("HIGHVOL", volume=5_000_000.0))
    db.add(_make_metric("LOWVOL", volume=100_000.0))
    db.flush()

    results = StockScreener.screen(
        db, {"min_volume": 1_000_000, "asset_classes": ["stocks"]}
    )
    tickers = {r["ticker"] for r in results}
    assert "HIGHVOL" in tickers
    assert "LOWVOL" not in tickers


def test_stock_screener_min_volume_includes_close_price(db: Session):
    """When min_volume filter is active, close_price is populated from StockMetric."""
    from app.services.stock_screener import StockScreener

    db.add(_make_ticker("META"))
    db.flush()
    db.add(_make_metric("META", volume=2_000_000.0, close_price=350.0))
    db.flush()

    results = StockScreener.screen(
        db, {"min_volume": 1_000_000, "asset_classes": ["stocks"]}
    )
    r = next(x for x in results if x["ticker"] == "META")
    assert r["close_price"] == 350.0
    assert r["volume"] == 2_000_000.0


# ── StockScreener.screen — min_market_cap filter ──────────────────────────


def test_stock_screener_min_market_cap_filter(db: Session):
    """min_market_cap filters out tickers below threshold."""
    from app.services.stock_screener import StockScreener

    db.add(_make_ticker("SMALL", market_cap=500_000.0))
    db.add(_make_ticker("LARGE", market_cap=10_000_000.0))
    db.flush()

    results = StockScreener.screen(
        db, {"min_market_cap": 1_000_000, "asset_classes": ["stocks"]}
    )
    tickers = {r["ticker"] for r in results}
    assert "LARGE" in tickers
    assert "SMALL" not in tickers


# ── StockScreener.screen — sector filter ──────────────────────────────────


def test_stock_screener_sector_filter_single_value(db: Session):
    """sector filter with a single string value."""
    from app.services.stock_screener import StockScreener

    db.add(_make_ticker("TECH1", sector="Technology"))
    db.add(_make_ticker("HEAL1", sector="Healthcare"))
    db.flush()

    results = StockScreener.screen(
        db, {"sector": "Technology", "asset_classes": ["stocks"]}
    )
    tickers = {r["ticker"] for r in results}
    assert "TECH1" in tickers
    assert "HEAL1" not in tickers


def test_stock_screener_sector_filter_list(db: Session):
    """sector filter with a list of values."""
    from app.services.stock_screener import StockScreener

    db.add(_make_ticker("TECH2", sector="Technology"))
    db.add(_make_ticker("FIN1", sector="Finance"))
    db.add(_make_ticker("ENRG1", sector="Energy"))
    db.flush()

    results = StockScreener.screen(
        db, {"sector": ["Technology", "Finance"], "asset_classes": ["stocks"]}
    )
    tickers = {r["ticker"] for r in results}
    assert "TECH2" in tickers
    assert "FIN1" in tickers
    assert "ENRG1" not in tickers


# ── StockScreener.screen — description_contains filter ────────────────────


def test_stock_screener_description_contains_filter(db: Session):
    """description_contains does case-insensitive substring match."""
    from app.services.stock_screener import StockScreener

    db.add(_make_ticker("SRCH1", description="Cloud computing platform"))
    db.add(_make_ticker("SRCH2", description="Retail clothing brand"))
    db.flush()

    results = StockScreener.screen(
        db, {"description_contains": "cloud", "asset_classes": ["stocks"]}
    )
    tickers = {r["ticker"] for r in results}
    assert "SRCH1" in tickers
    assert "SRCH2" not in tickers


# ── StockScreener self-registers ──────────────────────────────────────────


def test_stock_screener_self_registers():
    """Importing stock_screener registers 'stocks' in the discovery registry."""
    import app.services.stock_screener  # noqa: F401
    from app.services.discovery_service import _SCREENER_REGISTRY

    assert "stocks" in _SCREENER_REGISTRY
