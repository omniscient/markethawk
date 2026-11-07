"""
LtEtf SQLAlchemy model.

Long-term ETF roster — the source of truth for the "Long-Term ETFs" static
universe (StockUniverse.kind == "static"). The universe's StockUniverseTicker /
MonitoredStock rows are a mirror rebuilt from active roster rows by /refresh.

data_source values
──────────────────
  massive   — US listings (Polygon/Massive path)
  yfinance  — TSX listings (".TO" suffix); routed by LT-1b, unread in LT-1a
"""

from sqlalchemy import JSON, Boolean, Column, Date, DateTime, Integer, String, text
from sqlalchemy.dialects.postgresql import JSONB

from app.core.database import Base
from app.utils.time import utc_now


class LtEtf(Base):
    __tablename__ = "lt_etf"

    id = Column(Integer, primary_key=True, index=True)
    ticker = Column(String(20), nullable=False, unique=True, index=True)
    name = Column(String(255), nullable=False)
    segment = Column(String(50), nullable=False)
    country = Column(String(2), nullable=False)  # "US" | "CA"
    currency = Column(String(3), nullable=False)  # "USD" | "CAD"
    exchange = Column(String(20), nullable=True)
    data_source = Column(
        String(50), nullable=False, default="massive", server_default="massive"
    )
    inception_date = Column(Date, nullable=True)
    is_active = Column(
        Boolean, nullable=False, default=True, server_default=text("true")
    )
    is_benchmark = Column(
        Boolean, nullable=False, default=False, server_default=text("false")
    )
    tags = Column(JSON().with_variant(JSONB, "postgresql"), default=list)
    created_at = Column(DateTime, default=utc_now)

    def __repr__(self) -> str:
        return f"<LtEtf {self.ticker} {self.segment}>"
