from sqlalchemy import Column, String, Float, DateTime
from datetime import datetime
from app.core.database import Base

class TickerReference(Base):
    __tablename__ = "ticker_references"

    ticker = Column(String, primary_key=True, index=True)
    name = Column(String)
    market_cap = Column(Float)
    outstanding_shares = Column(Float)
    sector = Column(String)
    industry = Column(String)
    last_updated = Column(DateTime, default=datetime.utcnow)
    
    # New fields for detailed info
    description = Column(String, nullable=True)
    primary_exchange = Column(String, nullable=True)
    list_date = Column(String, nullable=True) # Kept as string for simplicity 'YYYY-MM-DD'
    total_employees = Column(Float, nullable=True) # Float because sometimes API returns weird numbers
    share_class_shares_outstanding = Column(Float, nullable=True)
    weighted_shares_outstanding = Column(Float, nullable=True)
    sic_code = Column(String, nullable=True)
    sic_description = Column(String, nullable=True)
    homepage_url = Column(String, nullable=True)
    last_details_update = Column(DateTime, nullable=True)
