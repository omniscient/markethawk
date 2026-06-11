"""
FuturesContract SQLAlchemy model.

A catalog of known futures contract months for each root symbol.
Populated by querying IBKR's reqContractDetails() and cached here so
subsequent downloads don't need to re-query IBKR for the contract list.
"""

from sqlalchemy import Boolean, Column, Date, DateTime, Index, Integer, String

from app.core.database import Base
from app.utils.time import utc_now


class FuturesContract(Base):
    """Metadata for a single futures contract month."""

    __tablename__ = "futures_contracts"

    id = Column(Integer, primary_key=True, index=True)
    symbol = Column(String(20), nullable=False, index=True)  # root, e.g. "ES"
    exchange = Column(String(20), nullable=False)  # e.g. "CME"
    contract_month = Column(String(8), nullable=False)  # YYYYMMDD
    expiry_date = Column(Date)  # Parsed from contract_month

    # IBKR internal contract ID — allows direct requests without re-lookup
    con_id = Column(Integer)

    is_expired = Column(Boolean, default=False)
    data_downloaded = Column(Boolean, default=False)  # Has OHLCV data been fetched?

    last_bar_date = Column(
        DateTime
    )  # Most recent bar timestamp in DB for this contract
    first_bar_date = Column(DateTime)  # Oldest bar timestamp in DB for this contract

    created_at = Column(DateTime, default=utc_now)
    last_updated = Column(
        DateTime,
        default=utc_now,
        onupdate=utc_now,
    )

    __table_args__ = (
        # Primary lookup: symbol + contract month must be unique
        Index("idx_fc_symbol_month", "symbol", "contract_month", unique=True),
        # Find all contracts for a symbol quickly
        Index("idx_fc_symbol_exchange", "symbol", "exchange"),
    )
