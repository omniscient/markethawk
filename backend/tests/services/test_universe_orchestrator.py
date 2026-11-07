"""discover_and_refresh: static (roster-mirror) vs screened (DiscoveryService) (#904)."""

from datetime import date
from unittest.mock import patch

from sqlalchemy.orm import Session

from app.models import LtEtf, MonitoredStock, StockUniverse, StockUniverseTicker
from app.services.universe_orchestrator import discover_and_refresh


def _roster(db: Session) -> None:
    db.add_all(
        [
            LtEtf(
                ticker="SPY",
                name="SPDR S&P 500 ETF Trust",
                segment="Broad market",
                country="US",
                currency="USD",
                exchange="NYSEARCA",
                data_source="massive",
                is_benchmark=True,
            ),
            LtEtf(
                ticker="XIU.TO",
                name="iShares S&P/TSX 60 Index ETF",
                segment="Broad market",
                country="CA",
                currency="CAD",
                exchange="TSX",
                data_source="yfinance",
            ),
            LtEtf(
                ticker="ARKK",
                name="ARK Innovation ETF",
                segment="Tech themes",
                country="US",
                currency="USD",
                exchange="NYSEARCA",
                data_source="massive",
                is_active=False,
            ),
        ]
    )
    db.flush()


def _universe(db: Session, kind: str, criteria: dict | None = None) -> StockUniverse:
    u = StockUniverse(
        name=f"{kind} test", criteria=criteria or {}, kind=kind, is_active=True
    )
    db.add(u)
    db.flush()
    return u


def test_static_refresh_mirrors_active_roster_without_screener(db: Session):
    u = _universe(db, "static")
    _roster(db)

    with patch("app.services.discovery_service.DiscoveryService") as ds:
        result = discover_and_refresh(u.id, db)

    ds.assert_not_called()
    assert result["status"] == "completed"
    assert result["added"] == 2

    ms = {
        m.ticker: m
        for m in db.query(MonitoredStock).filter(MonitoredStock.universe_id == u.id)
    }
    assert set(ms) == {"SPY", "XIU.TO"}
    assert ms["XIU.TO"].company_name == "iShares S&P/TSX 60 Index ETF"
    assert ms["XIU.TO"].data_source == "yfinance"
    assert ms["SPY"].data_source == "massive"
    assert all(m.asset_class == "stocks" and m.is_active for m in ms.values())
    assert all(m.sector is None and m.market_cap is None for m in ms.values())

    sut = {
        t.ticker: t.data_source
        for t in db.query(StockUniverseTicker).filter(
            StockUniverseTicker.universe_id == u.id
        )
    }
    assert sut == {"SPY": "massive", "XIU.TO": "yfinance"}

    db.refresh(u)
    assert u.cached_ticker_count == 2
    assert u.stats_refreshed_at is not None


def test_static_refresh_replaces_stale_membership(db: Session):
    u = _universe(db, "static")
    _roster(db)
    db.add(
        MonitoredStock(
            ticker="OLD", universe_id=u.id, added_date=date(2026, 1, 2), is_active=True
        )
    )
    db.add(StockUniverseTicker(universe_id=u.id, ticker="OLD"))
    db.flush()

    discover_and_refresh(u.id, db)

    assert {
        m.ticker
        for m in db.query(MonitoredStock).filter(MonitoredStock.universe_id == u.id)
    } == {"SPY", "XIU.TO"}
    assert {
        t.ticker
        for t in db.query(StockUniverseTicker).filter(
            StockUniverseTicker.universe_id == u.id
        )
    } == {"SPY", "XIU.TO"}


def test_screened_refresh_still_runs_screener(db: Session):
    u = _universe(db, "screened", {"min_price": 5})
    _roster(db)  # roster rows must be ignored for screened universes
    screen = [
        {
            "ticker": "AAPL",
            "name": "Apple Inc.",
            "sector": "Technology",
            "market_cap": 3_000_000_000_000,
            "close_price": 200.0,
            "volume": 1_000_000,
        }
    ]

    with patch("app.services.discovery_service.DiscoveryService") as ds:
        ds.return_value.run_screen.return_value = screen
        result = discover_and_refresh(u.id, db)

    ds.return_value.run_screen.assert_called_once_with({"min_price": 5})
    assert result["added"] == 1
    assert result["message"].endswith("from Discovery Engine.")

    ms = db.query(MonitoredStock).filter(MonitoredStock.universe_id == u.id).one()
    assert ms.ticker == "AAPL"
    assert ms.company_name == "Apple Inc."
    assert ms.sector == "Technology"
    assert ms.stock_metadata["source"] == "discovery_engine"
    assert ms.stock_metadata["close_price"] == 200.0
