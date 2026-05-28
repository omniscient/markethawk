"""
ScannerRun SQLAlchemy model.
"""

import uuid
from datetime import datetime, timezone

from sqlalchemy import Column, Date, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy import Uuid as UUID
from sqlalchemy.dialects.postgresql import JSONB

from app.core.database import Base


class ScannerRun(Base):
    """Represents a single execution of a scanner."""

    __tablename__ = "scanner_runs"

    id = Column(Integer, primary_key=True, index=True)
    uuid = Column(UUID(as_uuid=True), default=uuid.uuid4, unique=True, index=True)
    scanner_type = Column(String(50), nullable=False)
    universe_id = Column(Integer, ForeignKey("stock_universes.id"), nullable=True)
    # 'queued' (Celery enqueued, not yet started), 'running', 'completed', 'failed', 'cancelled'
    status = Column(String(20), default="completed")
    stocks_scanned = Column(Integer, default=0)
    events_detected = Column(Integer, default=0)
    execution_time_ms = Column(Integer, default=0)
    error_message = Column(Text, nullable=True)
    # Per-ticker failures from partial scan runs: [{ticker, error_type, message, retryable}, ...]
    failed_tickers = Column(JSONB, nullable=True)
    created_at = Column(
        DateTime, default=lambda: datetime.now(timezone.utc).replace(tzinfo=None)
    )
    scan_start_date = Column(Date, nullable=True)
    scan_end_date = Column(Date, nullable=True)
    celery_task_id = Column(String(64), nullable=True, index=True)
