"""
BacktestTrade — one row per simulated trade in a backtest run.

Each row records the full lifecycle of one simulated position:
signal → entry attempt → exit with reason.
"""

from sqlalchemy import (
    Column,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    Numeric,
    String,
)
from sqlalchemy.dialects.postgresql import JSONB

from app.core.database import Base
from app.utils.time import utc_now


class BacktestTrade(Base):
    """One simulated trade within a BacktestRun."""

    __tablename__ = "backtest_trades"

    id = Column(Integer, primary_key=True, index=True)
    run_id = Column(
        Integer,
        ForeignKey("backtest_runs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # ── Signal context ────────────────────────────────────────────────────────
    ticker = Column(String(10), nullable=False, index=True)
    signal_date = Column(Date, nullable=False)
    # FK to existing ScannerEvent when sourced from DB; NULL when generated in-memory
    source_event_id = Column(
        Integer, ForeignKey("scanner_events.id", ondelete="SET NULL"), nullable=True
    )
    # Snapshot of signal indicators at signal time (JSONB for traceability)
    signal_indicators = Column(JSONB, nullable=True)

    # ── Entry ─────────────────────────────────────────────────────────────────
    entry_date = Column(Date, nullable=True)
    entry_price = Column(Numeric, nullable=True)

    # ── Exit ──────────────────────────────────────────────────────────────────
    exit_date = Column(Date, nullable=True)
    exit_price = Column(Numeric, nullable=True)
    # stop | target | time_stop | delisted_or_data_end | no_entry_bar
    exit_reason = Column(String(30), nullable=True)
    hold_sessions = Column(Integer, nullable=True)

    # ── P&L ──────────────────────────────────────────────────────────────────
    # Result in R-multiples (e.g. +2.0 = hit target at 2:1, -1.0 = stopped out)
    result_r = Column(Float, nullable=True)

    # Computed stop and target levels (absolute prices)
    stop_price = Column(Numeric, nullable=True)
    target_price = Column(Numeric, nullable=True)

    created_at = Column(DateTime, default=utc_now)
