"""
Cached scanner event narrative model.
"""

from sqlalchemy import (
    Column,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB

from app.core.database import Base
from app.utils.time import utc_now


class ScannerEventNarrative(Base):
    """Cached generated narrative for one scanner event and LLM config."""

    __tablename__ = "scanner_event_narratives"

    id = Column(Integer, primary_key=True, index=True)
    scanner_event_id = Column(
        Integer,
        ForeignKey("scanner_events.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    feature_area = Column(String(50), nullable=False, default="scanner_narrative")
    narrative_text = Column(Text, nullable=False)
    provider = Column(String(50), nullable=False)
    model = Column(String(100), nullable=False)
    prompt_version = Column(String(50), nullable=False)
    brief_schema_version = Column(String(50), nullable=False)
    brief_fingerprint = Column(String(64), nullable=False, index=True)
    input_payload = Column(JSONB, nullable=False, default=dict)
    created_at = Column(DateTime, default=utc_now)
    updated_at = Column(DateTime, default=utc_now, onupdate=utc_now)

    __table_args__ = (
        UniqueConstraint(
            "scanner_event_id",
            "feature_area",
            "provider",
            "model",
            "prompt_version",
            name="uq_scanner_event_narrative_cache",
        ),
    )
