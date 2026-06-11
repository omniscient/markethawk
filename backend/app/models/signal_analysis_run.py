from sqlalchemy import Column, DateTime, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB

from app.core.database import Base
from app.utils.time import utc_now


class SignalAnalysisRun(Base):
    """Anchor table for each statistical analysis execution."""

    __tablename__ = "signal_analysis_runs"

    id = Column(Integer, primary_key=True, index=True)
    scanner_type = Column(String(50), nullable=True, index=True)
    status = Column(String(20), nullable=False, default="pending", index=True)
    event_count = Column(Integer, nullable=True)
    correlation_matrix = Column(JSONB, nullable=True)
    feature_weights = Column(JSONB, nullable=True)
    celery_task_id = Column(String(255), nullable=True)
    error_message = Column(Text, nullable=True)
    created_at = Column(
        DateTime,
        default=utc_now,
        index=True,
    )
    completed_at = Column(DateTime, nullable=True)
