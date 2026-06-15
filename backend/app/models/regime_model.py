"""
RegimeModel — persists fitted HMM artifacts for market regime detection.
"""

from sqlalchemy import Column, Date, DateTime, Float, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB

from app.core.database import Base
from app.utils.time import utc_now


class RegimeModel(Base):
    __tablename__ = "regime_models"

    id = Column(Integer, primary_key=True, index=True)
    version = Column(Integer, nullable=False, index=True)
    status = Column(String(20), nullable=False, default="active")  # active | archived
    n_states = Column(Integer, nullable=False)
    model_b64 = Column(Text, nullable=False)  # base64-encoded pickle of GaussianHMM
    feature_set = Column(JSONB, nullable=False)  # ["daily_return", ...]
    state_label_mapping = Column(JSONB, nullable=False)  # {"0": "risk_on", ...}
    data_start_date = Column(Date, nullable=False)
    data_end_date = Column(Date, nullable=False)
    bic_score = Column(Float, nullable=True)
    trained_at = Column(DateTime, nullable=False)
    created_at = Column(DateTime, default=utc_now)

    __table_args__ = (Index("ix_regime_models_status_version", "status", "version"),)
