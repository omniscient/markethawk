"""
StockSplit SQLAlchemy model.
"""

from datetime import datetime, timezone

from sqlalchemy import (
    Column,
    Date,
    DateTime,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
)

from app.core.database import Base


class StockSplit(Base):
    """Represents a stock split execution."""

    __tablename__ = "stock_splits"

    id = Column(Integer, primary_key=True, index=True)
    ticker = Column(String(10), nullable=False, index=True)
    execution_date = Column(Date, nullable=False, index=True)
    split_from = Column(Numeric, nullable=False)
    split_to = Column(Numeric, nullable=False)
    source = Column(String(20), nullable=False, default="polygon")
    detected_at = Column(
        DateTime, default=lambda: datetime.now(timezone.utc).replace(tzinfo=None)
    )
    adjustments_applied_at = Column(DateTime, nullable=True)

    __table_args__ = (
        UniqueConstraint("ticker", "execution_date", name="uq_split_ticker_date"),
    )
