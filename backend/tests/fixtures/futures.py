"""
Futures seed helpers.
Each function inserts rows and flushes; the caller's transaction provides rollback.
"""

from datetime import datetime, timezone, timedelta, date

from sqlalchemy.orm import Session

from app.models.futures_aggregate import FuturesAggregate
from app.models.futures_contract import FuturesContract
from app.models.futures_rollover import FuturesRollover


def seed_futures_contracts(
    db: Session,
    symbol: str = "ES",
    exchange: str = "CME",
    count: int = 2,
) -> list[FuturesContract]:
    """Insert `count` FuturesContract rows for `symbol`."""
    rows = []
    base_year = 2025
    months = ["0321", "0620", "0919", "1219"]
    for i in range(count):
        contract_month = f"{base_year}{months[i % len(months)]}"
        row = FuturesContract(
            symbol=symbol,
            exchange=exchange,
            contract_month=contract_month,
            expiry_date=date(base_year, int(months[i % len(months)][:2]), int(months[i % len(months)][2:])),
            is_expired=(i < count - 1),
            data_downloaded=True,
        )
        db.add(row)
        rows.append(row)
    db.flush()
    return rows


def seed_futures_aggregates(
    db: Session,
    symbol: str = "ES",
    contract_month: str = "20250321",
    exchange: str = "CME",
    timespan: str = "day",
    multiplier: int = 1,
    count: int = 5,
) -> list[FuturesAggregate]:
    """Insert `count` FuturesAggregate bars for `symbol`/`contract_month`."""
    base = (datetime.now(timezone.utc) - timedelta(days=count)).replace(tzinfo=None)
    rows = []
    price = 5000.0
    for i in range(count):
        open_ = round(price + i * 10.0, 2)
        close = round(open_ + 5.0, 2)
        row = FuturesAggregate(
            symbol=symbol,
            contract_month=contract_month,
            exchange=exchange,
            timestamp=base + timedelta(days=i),
            timespan=timespan,
            multiplier=multiplier,
            open=open_,
            high=round(close + 15.0, 2),
            low=round(open_ - 10.0, 2),
            close=close,
            volume=100_000 + i * 5_000,
            vwap=round((open_ + close) / 2, 2),
            transactions=10_000 + i * 500,
            source="ibkr",
        )
        db.add(row)
        rows.append(row)
    db.flush()
    return rows


def seed_futures_rollover(
    db: Session,
    symbol: str = "ES",
    exchange: str = "CME",
    from_contract: str = "20250321",
    to_contract: str = "20250620",
    roll_date: date | None = None,
) -> FuturesRollover:
    """Insert a single FuturesRollover row."""
    if roll_date is None:
        roll_date = date(2025, 3, 10)
    row = FuturesRollover(
        symbol=symbol,
        exchange=exchange,
        from_contract=from_contract,
        to_contract=to_contract,
        roll_date=roll_date,
        detection_method="volume",
    )
    db.add(row)
    db.flush()
    return row
