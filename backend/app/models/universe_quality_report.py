"""
UniverseQualityReport SQLAlchemy model.

Stores the latest data-quality analysis result for each universe.
One row per universe; re-running the analysis overwrites the previous result.
"""

from sqlalchemy import Column, DateTime, ForeignKey, Integer, Numeric, String, Text
from sqlalchemy.dialects.postgresql import JSON

from app.core.database import Base
from app.utils.time import utc_now


class UniverseQualityReport(Base):
    __tablename__ = "universe_quality_reports"

    id = Column(Integer, primary_key=True, index=True)
    universe_id = Column(
        Integer,
        ForeignKey("stock_universes.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
        index=True,
    )
    status = Column(
        String(20), default="pending", nullable=False
    )  # pending | running | complete | error
    overall_grade = Column(String(1), nullable=True)  # A B C D F
    overall_score = Column(Numeric, nullable=True)  # 0–100
    ticker_count = Column(Integer, nullable=True)
    started_at = Column(
        DateTime,
        default=utc_now,
        nullable=False,
    )
    generated_at = Column(DateTime, nullable=True)  # set when complete
    report_data = Column(JSON, nullable=True)  # full per-ticker breakdown
    error_message = Column(Text, nullable=True)

    # Normalization tracking (set by normalize_universe_quality task)
    normalization_status = Column(
        String(20), nullable=True
    )  # pending | running | complete | error
    normalization_data = Column(
        JSON, nullable=True
    )  # progress checkpoint (see NormalizationService)
