"""
FuturesRollover SQLAlchemy model.

Records the date on which trading volume migrated from one contract month to
the next.  These records are the backbone of the continuous-series assembly
logic: when reading a continuous price series we select the "active" contract
for each date based on these rollover events.
"""

from datetime import datetime
from sqlalchemy import Column, Integer, String, DateTime, Date, Index

from app.core.database import Base


class FuturesRollover(Base):
    """
    A detected rollover event — the date volume crossed over from one
    contract to the next.
    """

    __tablename__ = "futures_rollovers"

    id            = Column(Integer, primary_key=True, index=True)
    symbol        = Column(String(20), nullable=False, index=True)   # e.g. "ES"
    exchange      = Column(String(20), nullable=False)               # e.g. "CME"
    from_contract = Column(String(8),  nullable=False)               # YYYYMMDD
    to_contract   = Column(String(8),  nullable=False)               # YYYYMMDD

    # The date on which we start using to_contract data in the continuous series
    roll_date = Column(Date, nullable=False, index=True)

    # How the rollover was determined
    # "volume"   – to_contract volume exceeded from_contract on this date
    # "calendar" – fallback: fixed N days before from_contract expiry
    # "manual"   – user-overridden
    detection_method = Column(String(20), nullable=False, default="volume")

    created_at   = Column(DateTime, default=datetime.utcnow)
    updated_at   = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (
        # Unique constraint: only one rollover record per (symbol, from_contract)
        Index("idx_fr_symbol_from", "symbol", "from_contract", unique=True),
        Index("idx_fr_symbol_date",  "symbol", "roll_date"),
    )
