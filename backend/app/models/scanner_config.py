"""
ScannerConfig SQLAlchemy model.
"""

from datetime import datetime
from sqlalchemy import Column, Integer, String, DateTime, Boolean, JSON, Text
from sqlalchemy.dialects.postgresql import UUID
import uuid

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
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
