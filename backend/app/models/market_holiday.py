"""
MarketHoliday model.

Tracks exchange-specific holiday and abbreviated-session events so that
the data-quality coverage scorer can distinguish genuine data gaps from
legitimately short trading sessions.

event_type values
─────────────────
  full_close   — market did not trade at all (e.g. Christmas Day)
  early_close  — session ended before the normal close (e.g. Christmas Eve)
  late_open    — session started after the normal open (rare for CME)
"""

from sqlalchemy import Column, Date, Integer, String, UniqueConstraint

from app.core.database import Base


class MarketHoliday(Base):
    __tablename__ = "market_holidays"

    id = Column(Integer, primary_key=True, index=True)
    exchange = Column(String(20), nullable=False, index=True)
    date = Column(Date, nullable=False, index=True)
    event_type = Column(String(20), nullable=False)   # full_close | early_close | late_open
    description = Column(String(200), nullable=True)

    __table_args__ = (
        UniqueConstraint("exchange", "date", name="uq_market_holiday_exchange_date"),
    )

    def __repr__(self) -> str:
        return f"<MarketHoliday {self.exchange} {self.date} {self.event_type}>"
