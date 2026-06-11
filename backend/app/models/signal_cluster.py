from sqlalchemy import Column, DateTime, ForeignKey, Integer, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.schema import Index

from app.core.database import Base
from app.utils.time import utc_now


class SignalCluster(Base):
    """One row per cluster archetype produced by a single analysis run."""

    __tablename__ = "signal_clusters"

    id = Column(Integer, primary_key=True, index=True)
    analysis_run_id = Column(
        Integer, ForeignKey("signal_analysis_runs.id"), nullable=False
    )
    cluster_index = Column(Integer, nullable=False)
    label = Column(String(200), nullable=False)
    centroid = Column(JSONB, nullable=False, default=dict)
    return_profile = Column(JSONB, nullable=False, default=dict)
    event_count = Column(Integer, nullable=False, default=0)
    created_at = Column(DateTime, default=utc_now)

    __table_args__ = (Index("ix_signal_clusters_analysis_run_id", "analysis_run_id"),)
