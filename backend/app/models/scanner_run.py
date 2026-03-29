"""
ScannerRun SQLAlchemy model.
"""

from datetime import datetime
from sqlalchemy import Column, Integer, String, DateTime, Text, ForeignKey, Uuid as UUID
import uuid

from app.core.database import Base


class ScannerRun(Base):
    """Represents a single execution of a scanner."""
    
    __tablename__ = "scanner_runs"
    
    id = Column(Integer, primary_key=True, index=True)
    uuid = Column(UUID(as_uuid=True), default=uuid.uuid4, unique=True, index=True)
    scanner_type = Column(String(50), nullable=False)
    universe_id = Column(Integer, ForeignKey("stock_universes.id"), nullable=True)
    status = Column(String(20), default="completed") # 'running', 'completed', 'failed'
    stocks_scanned = Column(Integer, default=0)
    events_detected = Column(Integer, default=0)
    execution_time_ms = Column(Integer, default=0)
    error_message = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
