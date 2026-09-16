"""ReplayTrade model for one simulated trade in a replay run."""

from sqlalchemy import Column, Date, DateTime, ForeignKey, Integer, Numeric, String

from app.core.database import Base
from app.utils.time import utc_now


class ReplayTrade(Base):
    """Per-signal ledger row produced by the replay engine."""

    __tablename__ = "replay_trades"

    id = Column(Integer, primary_key=True, index=True)
    replay_run_id = Column(
        Integer,
        ForeignKey("replay_runs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    scanner_event_id = Column(
        Integer,
        ForeignKey("scanner_events.id", ondelete="SET NULL"),
        nullable=True,
    )

    ticker = Column(String(10), nullable=False, index=True)
    signal_date = Column(Date, nullable=False)
    entry_date = Column(Date, nullable=True)
    entry_price = Column(Numeric, nullable=True)
    direction = Column(String(10), nullable=True)
    stop_price = Column(Numeric, nullable=True)
    target_price = Column(Numeric, nullable=True)

    exit_date = Column(Date, nullable=True)
    exit_price = Column(Numeric, nullable=True)
    exit_reason = Column(String(30), nullable=True)
    return_pct = Column(Numeric, nullable=True)
    return_r = Column(Numeric, nullable=True)
    mfe_pct = Column(Numeric, nullable=True)
    mae_pct = Column(Numeric, nullable=True)
    bars_held = Column(Integer, nullable=True)

    regime_trend = Column(String(20), nullable=True)
    regime_vol = Column(String(20), nullable=True)
    fill_source = Column(String(20), nullable=True)

    created_at = Column(DateTime, default=utc_now)
