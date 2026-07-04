"""
Semantic embedding cache model.
"""

from sqlalchemy import Column, DateTime, Integer, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB

from app.core.database import Base
from app.utils.time import utc_now


class SemanticEmbedding(Base):
    """Stored embedding vector for a typed source object."""

    __tablename__ = "semantic_embeddings"

    id = Column(Integer, primary_key=True, index=True)
    source_type = Column(String(50), nullable=False, index=True)
    source_id = Column(String(120), nullable=False, index=True)
    provider = Column(String(50), nullable=False)
    model = Column(String(100), nullable=False)
    embedding_version = Column(String(50), nullable=False)
    vector = Column(JSONB, nullable=False, default=list)
    metadata_ = Column("metadata", JSONB, nullable=False, default=dict)
    created_at = Column(DateTime, default=utc_now)
    updated_at = Column(DateTime, default=utc_now, onupdate=utc_now)

    __table_args__ = (
        UniqueConstraint(
            "source_type",
            "source_id",
            "provider",
            "model",
            "embedding_version",
            name="uq_semantic_embedding_source_model",
        ),
    )
