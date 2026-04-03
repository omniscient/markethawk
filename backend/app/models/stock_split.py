"""
StockSplit SQLAlchemy model.
"""

from sqlalchemy import Column, Integer, String, Date, Numeric
from app.core.database import Base

class StockSplit(Base):
    """Represents a stock split execution."""
    
    __tablename__ = "stock_splits"
    
    id = Column(Integer, primary_key=True, index=True)
    ticker = Column(String(10), nullable=False, index=True)
    execution_date = Column(Date, nullable=False, index=True)
    split_from = Column(Numeric, nullable=False)
    split_to = Column(Numeric, nullable=False)
