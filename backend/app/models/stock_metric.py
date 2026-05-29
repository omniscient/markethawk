from sqlalchemy import Column, Date, Float, ForeignKey, String
from sqlalchemy.orm import relationship

from app.core.database import Base


class StockMetric(Base):
    __tablename__ = "stock_metrics"

    ticker = Column(
        String, ForeignKey("ticker_references.ticker"), primary_key=True, index=True
    )
    date = Column(Date, primary_key=True, index=True)

    close_price = Column(Float)
    volume = Column(
        Float
    )  # Changed to Float to handle large numbers safely or match API types
    avg_volume_30d = Column(Float)
    sma_50 = Column(Float)
    sma_200 = Column(Float)
    high_52w = Column(Float)
    low_52w = Column(Float)
    atr_14 = Column(Float)

    # Relationship to reference
    reference = relationship("TickerReference")
