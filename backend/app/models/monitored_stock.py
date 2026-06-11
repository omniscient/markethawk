"""
MonitoredStock SQLAlchemy model.
"""

from sqlalchemy import JSON, Boolean, Column, Date, DateTime, Integer, Numeric, String

from app.core.database import Base
from app.utils.time import utc_now


class MonitoredStock(Base):
    """Represents a stock being monitored within a universe."""

    __tablename__ = "monitored_stocks"

    id = Column(Integer, primary_key=True, index=True)
    ticker = Column(String(50), nullable=False, index=True)
    company_name = Column(String(1000))
    sector = Column(String(255))
    industry = Column(String(255))
    market_cap = Column(Numeric)
    universe_id = Column(Integer, index=True)
    added_date = Column(Date, nullable=False)
    last_scanned = Column(DateTime)
    scan_count = Column(Integer, default=0)
    is_active = Column(Boolean, default=True, index=True)
    asset_class = Column(String(50), default="stocks", index=True)
    data_source = Column(String(50), default="massive", index=True)
    stock_metadata = Column("metadata", JSON, default=dict)
    created_at = Column(DateTime, default=utc_now)
    updated_at = Column(
        DateTime,
        default=utc_now,
        onupdate=utc_now,
    )
