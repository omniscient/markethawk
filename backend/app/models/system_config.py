"""
SystemConfig model — key/value store for system-wide settings.
"""

from datetime import datetime, timezone
from sqlalchemy import Column, String, DateTime

from app.core.database import Base


class SystemConfig(Base):
    __tablename__ = "system_config"

    key = Column(String, primary_key=True, index=True)
    value = Column(String, nullable=False)
    updated_at = Column(
        DateTime,
        default=lambda: datetime.now(timezone.utc).replace(tzinfo=None),
        onupdate=lambda: datetime.now(timezone.utc).replace(tzinfo=None),
    )
