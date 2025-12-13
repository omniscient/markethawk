"""
MonitoredStock SQLAlchemy model.
"""

from datetime import datetime
from sqlalchemy import Column, Integer, String, DateTime, Date, Boolean, JSON, Numeric
from app.core.database import Base


class MonitoredStock(Base):
    """Represents a stock being monitored within a universe."""
    
    __tablename__ = "monitored_stocks"
    
    id = Column(Integer, primary_key=True, index=True)
    ticker = Column(String(10), nullable=False, index=True)
    company_name = Column(String(200))
    sector = Column(String(100))
    industry = Column(String(100))
    market_cap = Column(Numeric)
    universe_id = Column(Integer, index=True)
    added_date = Column(Date, nullable=False)
    last_scanned = Column(DateTime)
    scan_count = Column(Integer, default=0)
    is_active = Column(Boolean, default=True, index=True)
    stock_metadata = Column(JSON, default=dict)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
