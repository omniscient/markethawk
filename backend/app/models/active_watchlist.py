"""
ActiveWatchlist model — manually curated list of symbols under live observation.

Symbols are added and removed by the user. A soft limit of 50 is enforced at
the API layer. There is no automatic expiry; entries persist until removed.
"""

from datetime import datetime, timezone
from sqlalchemy import Column, Integer, String, DateTime, Text

from app.core.database import Base

WATCHLIST_SOFT_LIMIT = 50


class ActiveWatchlist(Base):
    __tablename__ = "active_watchlist"

    id = Column(Integer, primary_key=True, index=True)
    symbol = Column(String(20), nullable=False, unique=True, index=True)
    # "STK" (stock/ETF) or "FUT" (continuous futures contract)
    security_type = Column(String(10), nullable=False, server_default="STK")
    # Exchange for routing — e.g. "SMART" for stocks, "CME" / "COMEX" for futures
    exchange = Column(String(20), nullable=True)
    notes = Column(Text, nullable=True)
    added_at = Column(
        DateTime,
        nullable=False,
        default=lambda: datetime.now(timezone.utc).replace(tzinfo=None),
    )
