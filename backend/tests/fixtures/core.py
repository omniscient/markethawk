"""
Core seed helpers — universes, tickers, scanner configs, monitored stocks.
Each function inserts rows and flushes (no commit); the caller's transaction
provides isolation and rollback.
"""

from datetime import date

from sqlalchemy.orm import Session

from app.models import MonitoredStock, ScannerConfig, StockUniverse, StockUniverseTicker


def seed_universes(db: Session) -> list[StockUniverse]:
    universes = [
        StockUniverse(
            name="Tech Stocks",
            description="Technology sector",
            criteria={"sector": "tech"},
            is_active=True,
        ),
        StockUniverse(
            name="Biotech",
            description="Biotech sector",
            criteria={"sector": "biotech"},
            is_active=True,
        ),
        StockUniverse(
            name="Inactive Universe",
            description="Not active",
            criteria={},
            is_active=False,
        ),
    ]
    for u in universes:
        db.add(u)
    db.flush()
    return universes


def seed_tickers(
    db: Session, universes: list[StockUniverse]
) -> list[StockUniverseTicker]:
    rows = [
        (universes[0], "AAPL"),
        (universes[0], "MSFT"),
        (universes[0], "NVDA"),
        (universes[1], "MRNA"),
        (universes[1], "BNTX"),
        (universes[1], "AAPL"),  # overlap across universes
    ]
    tickers = []
    for universe, ticker in rows:
        t = StockUniverseTicker(universe_id=universe.id, ticker=ticker)
        db.add(t)
        tickers.append(t)
    db.flush()
    return tickers


def seed_monitored_stocks(
    db: Session, universes: list[StockUniverse]
) -> list[MonitoredStock]:
    rows = [
        (universes[0], "AAPL"),
        (universes[0], "MSFT"),
        (universes[0], "NVDA"),
        (universes[1], "MRNA"),
        (universes[1], "BNTX"),
        (universes[1], "AAPL"),  # overlap across universes
    ]
    stocks = []
    for universe, ticker in rows:
        m = MonitoredStock(
            ticker=ticker,
            universe_id=universe.id,
            added_date=date.today(),
            is_active=True,
        )
        db.add(m)
        stocks.append(m)
    db.flush()
    return stocks


def seed_scanner_configs(db: Session, universe_id: int | None = None) -> list[ScannerConfig]:
    if universe_id is None:
        u = StockUniverse(
            name="Test Universe",
            description="Seed universe for scanner config tests",
            criteria={},
            is_active=True,
        )
        db.add(u)
        db.flush()
        universe_id = u.id

    configs = [
        ScannerConfig(
            name="Pre-Market Volume Spike",
            scanner_type="pre_market_volume_spike",
            parameters={"min_volume": 100000, "spike_ratio": 4.0},
            criteria=[{"field": "volume_ratio", "op": ">=", "value": 4.0}],
            is_active=True,
            universe_id=universe_id,
        ),
        ScannerConfig(
            name="Liquidity Hunt",
            scanner_type="liquidity_hunt",
            parameters={"threshold": 1000},
            criteria=[{"field": "liquidity_score", "op": ">=", "value": 1000}],
            is_active=True,
            universe_id=universe_id,
        ),
        ScannerConfig(
            name="Inactive Config",
            scanner_type="oversold_bounce",
            parameters={},
            criteria=[],
            is_active=False,
            universe_id=universe_id,
        ),
    ]
    for c in configs:
        db.add(c)
    db.flush()
    return configs
