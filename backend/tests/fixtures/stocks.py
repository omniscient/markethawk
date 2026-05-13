"""
Stocks seed helpers.
Each function inserts rows and flushes; the caller's transaction provides rollback.
"""

from datetime import datetime, timezone, timedelta

from sqlalchemy.orm import Session

from app.models.stock_aggregate import StockAggregate


def seed_stock_aggregates(
    db: Session,
    ticker: str = "AAPL",
    timespan: str = "day",
    multiplier: int = 1,
    count: int = 5,
) -> list[StockAggregate]:
    """
    Insert `count` StockAggregate rows for `ticker`.
    Bars are anchored to (now - count days) so they always fall inside a 30d window.
    Returns the list of created rows.
    """
    base = (datetime.now(timezone.utc) - timedelta(days=count)).replace(tzinfo=None)
    rows = []
    price = 150.0
    for i in range(count):
        open_ = round(price + i * 0.5, 2)
        close = round(open_ + 0.25, 2)
        row = StockAggregate(
            ticker=ticker,
            timestamp=base + timedelta(days=i),
            timespan=timespan,
            multiplier=multiplier,
            open=open_,
            high=round(close + 0.75, 2),
            low=round(open_ - 0.5, 2),
            close=close,
            volume=1_000_000 + i * 50_000,
            vwap=round((open_ + close) / 2, 2),
            transactions=5000 + i * 100,
        )
        db.add(row)
        rows.append(row)
    db.flush()
    return rows
