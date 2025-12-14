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
