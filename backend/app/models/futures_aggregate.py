"""
FuturesAggregate SQLAlchemy model.

Stores per-contract OHLCV bars for futures instruments.  Kept separate from
StockAggregate so we can track contract_month and source without polluting
the stock table schema.
"""

from sqlalchemy import (
    BigInteger,
    Column,
    DateTime,
    Index,
    Integer,
    Numeric,
    String,
)

from app.core.database import Base
from app.utils.time import utc_now


class FuturesAggregate(Base):
    """One OHLCV bar for a specific futures contract month."""

    __tablename__ = "futures_aggregates"

    id = Column(Integer, primary_key=True, index=True)
    symbol = Column(String(20), nullable=False, index=True)  # e.g. "ES"
    contract_month = Column(String(8), nullable=False, index=True)  # "YYYYMMDD"
    exchange = Column(String(20), nullable=False)  # e.g. "CME"
    timestamp = Column(
        DateTime, nullable=False, index=True
    )  # bar open time (UTC, naive)
    timespan = Column(String(20), nullable=False, default="day")
    multiplier = Column(Integer, nullable=False, default=1)

    open = Column(Numeric, nullable=False)
    high = Column(Numeric, nullable=False)
    low = Column(Numeric, nullable=False)
    close = Column(Numeric, nullable=False)
    volume = Column(BigInteger, nullable=False)
    vwap = Column(Numeric)
    transactions = Column(Integer)

    source = Column(String(20), default="ibkr")  # which provider supplied this bar
    created_at = Column(DateTime, default=utc_now)

    __table_args__ = (
        # Fast lookup when assembling a continuous series
        Index("idx_fa_symbol_ts", "symbol", "timestamp"),
        # Efficient per-contract queries
        Index("idx_fa_symbol_contract", "symbol", "contract_month"),
        # Query bars for a specific contract within a time range
        Index("idx_fa_contract_ts", "symbol", "contract_month", "timestamp"),
        # Optimized for continuous series assembly (fully covers the WHERE clause)
        Index(
            "idx_fa_continuous_series",
            "symbol",
            "contract_month",
            "timespan",
            "multiplier",
            "timestamp",
        ),
    )
