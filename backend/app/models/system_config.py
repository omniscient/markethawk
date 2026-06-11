"""
SystemConfig model — key/value store for system-wide settings.
"""

from sqlalchemy import Column, DateTime, String

from app.core.database import Base
from app.utils.time import utc_now


class SystemConfig(Base):
    __tablename__ = "system_config"

    key = Column(String, primary_key=True, index=True)
    value = Column(String, nullable=False)
    updated_at = Column(
        DateTime,
        default=utc_now,
        onupdate=utc_now,
    )
