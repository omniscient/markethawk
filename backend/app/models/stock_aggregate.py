"""
StockAggregate SQLAlchemy model.
"""

from datetime import datetime, timezone
from sqlalchemy import Column, Integer, String, DateTime, Numeric, BigInteger, Boolean
from sqlalchemy.schema import Index

from app.core.database import Base


class StockAggregate(Base):
    """Represents a stock aggregate (candle)."""
    
    __tablename__ = "stock_aggregates"
    
    id = Column(Integer, primary_key=True, index=True)
    ticker = Column(String(10), nullable=False, index=True)
    timestamp = Column(DateTime, nullable=False, index=True)
    multiplier = Column(Integer, nullable=False, default=1)
    timespan = Column(String(20), nullable=False, default="minute")
    
    open = Column(Numeric, nullable=False)
    high = Column(Numeric, nullable=False)
    low = Column(Numeric, nullable=False)
    close = Column(Numeric, nullable=False)
    volume = Column(BigInteger, nullable=False)
    vwap = Column(Numeric)
    transactions = Column(Integer)
    
    is_pre_market = Column(Boolean, default=False, index=True)
    is_after_market = Column(Boolean, default=False, index=True)

    provider = Column(String(50), default='polygon', nullable=True)  # data source: 'polygon', 'ibkr', etc.

    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc).replace(tzinfo=None))
    
    # Composite index for efficient querying by ticker and time
    __table_args__ = (
        Index('idx_ticker_time', 'ticker', 'timestamp'),
        Index('idx_ticker_time_pre', 'ticker', 'timestamp', 'is_pre_market'),
    )
