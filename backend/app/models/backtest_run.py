"""
BacktestRun — persisted record of a single backtest execution.

One row per (scanner_type × strategy × universe × date_range) invocation.
Stores summary stats plus anti-bias metadata as required by issue #301.
"""

import uuid

from sqlalchemy import (
    Boolean,
    Column,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
)
from sqlalchemy import Uuid as UUID
from sqlalchemy.dialects.postgresql import JSONB

from app.core.database import Base
from app.utils.time import utc_now


class BacktestRun(Base):
    """Anchor table for one backtest execution."""

    __tablename__ = "backtest_runs"

    id = Column(Integer, primary_key=True, index=True)
    uuid = Column(UUID(as_uuid=True), default=uuid.uuid4, unique=True, index=True)

    # ── Inputs ───────────────────────────────────────────────────────────────
    scanner_type = Column(String(50), nullable=False)
    strategy_id = Column(Integer, ForeignKey("trading_strategies.id"), nullable=False)
    universe_id = Column(Integer, ForeignKey("stock_universes.id"), nullable=False)
    start_date = Column(Date, nullable=False)
    end_date = Column(Date, nullable=False)
    # Per-run parameter; default 10 sessions (not stored on TradingStrategy)
    max_hold_sessions = Column(Integer, nullable=False, default=10)
    # Optional scanner config parameters (JSONB; passed to scanner if re-generating signals)
    scanner_config_params = Column(JSONB, nullable=True)
    # Snapshot of strategy fields at run time for determinism (spec req #9, #11)
    strategy_snapshot = Column(JSONB, nullable=True)

    # ── Execution state ───────────────────────────────────────────────────────
    # queued → running → completed | failed
    status = Column(String(20), nullable=False, default="queued")
    celery_task_id = Column(String(64), nullable=True, index=True)
    error_message = Column(Text, nullable=True)

    # ── Summary statistics ────────────────────────────────────────────────────
    total_signals = Column(Integer, nullable=True)
    total_trades = Column(Integer, nullable=True)
    wins = Column(Integer, nullable=True)
    losses = Column(Integer, nullable=True)
    win_rate = Column(Float, nullable=True)
    profit_factor = Column(Float, nullable=True)
    expectancy_r = Column(Float, nullable=True)  # expectancy in R-multiples
    max_drawdown_r = Column(Float, nullable=True)
    avg_hold_sessions = Column(Float, nullable=True)
    median_hold_sessions = Column(Float, nullable=True)

    # ── Anti-bias / data-quality metadata (required by survivorship-bias addendum) ──
    signals_skipped_no_data = Column(Integer, nullable=True, default=0)
    trades_exited_on_data_end = Column(Integer, nullable=True, default=0)
    # ISO date string — the constituent list is today's membership, not point-in-time
    universe_as_of = Column(String(10), nullable=True)
    # e.g. "polygon_adjusted"
    bars_source = Column(String(50), nullable=True)
    # Reserved for issue #387 (data-quality degraded_input flag); nullable in v1
    degraded_input = Column(Boolean, nullable=True)

    created_at = Column(DateTime, default=utc_now)
    completed_at = Column(DateTime, nullable=True)
