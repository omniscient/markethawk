"""
StockUniverseTicker SQLAlchemy model.
"""

from datetime import datetime
from sqlalchemy import Column, Integer, String, DateTime, Index
from app.core.database import Base


class StockUniverseTicker(Base):
    """
    Represents a simple list of tickers associated with a universe.
    Used for persistent storage of universe constituents.
    """
    
    __tablename__ = "stock_universe_tickers"
    
    id = Column(Integer, primary_key=True, index=True)
    universe_id = Column(Integer, index=True, nullable=False)
    ticker = Column(String(10), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    # Unique constraint or just index to prevent dupes?
    # Usually a universe shouldn't have the same ticker twice.
    # We can add a UniqueConstraint if needed, but for now simple structure.
    # Let's add an index on (universe_id, ticker)
    __table_args__ = (
        Index('ix_universe_ticker', 'universe_id', 'ticker'),
    )
