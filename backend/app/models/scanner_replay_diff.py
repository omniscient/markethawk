"""ScannerReplayDiff model — stores nightly replay-diff results per scanner per day."""

from sqlalchemy import (
    Boolean,
    Column,
    Date,
    DateTime,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB

from app.core.database import Base
from app.utils.time import utc_now


class ScannerReplayDiff(Base):
    """One replay-diff record per (scanner_type, scan_date).

    status:
      "clean"            — replay and live agree, no drift
      "drift"            — mismatch above threshold
      "insufficient_data"— not enough stored bars to replay
      "no_live_events"   — no live ScannerEvent rows for that scanner+day
    """

    __tablename__ = "scanner_replay_diffs"

    id = Column(Integer, primary_key=True, index=True)
    scanner_type = Column(String(50), nullable=False, index=True)
    scan_date = Column(Date, nullable=False, index=True)
    status = Column(String(30), nullable=False)
    has_drift = Column(Boolean, nullable=False, default=False)

    # Signal counts
    live_count = Column(Integer, nullable=False, default=0)
    replay_count = Column(Integer, nullable=False, default=0)
    missing_in_replay_count = Column(Integer, nullable=False, default=0)
    new_in_replay_count = Column(Integer, nullable=False, default=0)
    matched_count = Column(Integer, nullable=False, default=0)

    # Variable-length payload
    missing_in_replay = Column(JSONB, nullable=False, default=list)
    new_in_replay = Column(JSONB, nullable=False, default=list)
    metric_deltas = Column(JSONB, nullable=False, default=list)
    drift_kinds = Column(JSONB, nullable=False, default=list)

    created_at = Column(DateTime, default=utc_now)
    updated_at = Column(DateTime, default=utc_now, onupdate=utc_now)

    __table_args__ = (
        UniqueConstraint("scanner_type", "scan_date", name="uq_scanner_replay_diff"),
    )
