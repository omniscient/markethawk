"""ReplayRun model for reproducible signal replay executions."""

import uuid

from sqlalchemy import Column, Date, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy import Uuid as UUID
from sqlalchemy.dialects.postgresql import JSONB

from app.core.database import Base
from app.utils.time import utc_now


class ReplayRun(Base):
    """Anchor table for one canonical signal replay run."""

    __tablename__ = "replay_runs"

    id = Column(Integer, primary_key=True, index=True)
    uuid = Column(UUID(as_uuid=True), default=uuid.uuid4, unique=True, index=True)

    status = Column(String(20), nullable=False, default="queued")
    celery_task_id = Column(String(64), nullable=True, index=True)

    scanner_type = Column(String(50), nullable=False)
    scanner_config_snapshot = Column(JSONB, nullable=False)
    trading_strategy_id = Column(
        Integer, ForeignKey("trading_strategies.id"), nullable=True
    )
    strategy_snapshot = Column(JSONB, nullable=True)
    universe_id = Column(Integer, ForeignKey("stock_universes.id"), nullable=False)
    universe_snapshot = Column(JSONB, nullable=False)

    start_date = Column(Date, nullable=False)
    end_date = Column(Date, nullable=False)
    max_hold_days = Column(Integer, nullable=False, default=10)
    exit_fidelity = Column(String(20), nullable=False, default="intraday")
    benchmark_symbol = Column(String(10), nullable=True, default="SPY")

    data_hash = Column(String(64), nullable=True)
    metrics = Column(JSONB, nullable=True)
    skipped_count = Column(Integer, nullable=True, default=0)
    error_message = Column(Text, nullable=True)
    signal_source = Column(String(20), nullable=True)

    total_trades = Column(Integer, nullable=True)
    hit_rate = Column(Float, nullable=True)
    expectancy_r = Column(Float, nullable=True)
    profit_factor = Column(Float, nullable=True)
    max_drawdown_r = Column(Float, nullable=True)
    avg_bars_held = Column(Float, nullable=True)
    median_bars_held = Column(Float, nullable=True)
    avg_mfe_pct = Column(Float, nullable=True)
    avg_mae_pct = Column(Float, nullable=True)
    mfe_mae_ratio = Column(Float, nullable=True)

    created_at = Column(DateTime, default=utc_now)
    completed_at = Column(DateTime, nullable=True)
