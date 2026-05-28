"""
ScannerConfig SQLAlchemy model.
"""

import uuid
from datetime import datetime, timezone

from sqlalchemy import JSON, Boolean, Column, DateTime, Integer, String, Text
from sqlalchemy import Uuid as UUID
from sqlalchemy.dialects.postgresql import JSONB

from app.core.database import Base


class ScannerConfig(Base):
    """Represents a scanner configuration with criteria and scheduling."""

    __tablename__ = "scanner_configs"

    id = Column(Integer, primary_key=True, index=True)
    uuid = Column(UUID(as_uuid=True), default=uuid.uuid4, unique=True, index=True)
    name = Column(String(100), nullable=False)
    description = Column(Text)
    scanner_type = Column(String(50), nullable=False)
    parameters = Column(JSON, nullable=False)
    criteria = Column(JSON, nullable=False)
    is_active = Column(Boolean, default=True)
    run_frequency = Column(String(20))
    last_run = Column(DateTime)
    next_run = Column(DateTime)
    outcome_config = Column(JSONB, nullable=True)
    data_requirements = Column(JSONB, nullable=True)

    created_at = Column(
        DateTime, default=lambda: datetime.now(timezone.utc).replace(tzinfo=None)
    )
    updated_at = Column(
        DateTime,
        default=lambda: datetime.now(timezone.utc).replace(tzinfo=None),
        onupdate=lambda: datetime.now(timezone.utc).replace(tzinfo=None),
    )
