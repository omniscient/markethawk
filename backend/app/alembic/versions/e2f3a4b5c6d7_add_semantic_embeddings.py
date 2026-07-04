"""add_semantic_embeddings

Revision ID: e2f3a4b5c6d7
Revises: c0d1e2f3a4b5
Create Date: 2026-07-04 09:10:00.000000
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "e2f3a4b5c6d7"
down_revision: Union[str, None] = "c0d1e2f3a4b5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "semantic_embeddings",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("source_type", sa.String(length=50), nullable=False),
        sa.Column("source_id", sa.String(length=120), nullable=False),
        sa.Column("provider", sa.String(length=50), nullable=False),
        sa.Column("model", sa.String(length=100), nullable=False),
        sa.Column("embedding_version", sa.String(length=50), nullable=False),
        sa.Column("vector", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "source_type",
            "source_id",
            "provider",
            "model",
            "embedding_version",
            name="uq_semantic_embedding_source_model",
        ),
    )
    op.create_index(op.f("ix_semantic_embeddings_id"), "semantic_embeddings", ["id"])
    op.create_index(
        op.f("ix_semantic_embeddings_source_id"),
        "semantic_embeddings",
        ["source_id"],
    )
    op.create_index(
        op.f("ix_semantic_embeddings_source_type"),
        "semantic_embeddings",
        ["source_type"],
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_semantic_embeddings_source_type"), table_name="semantic_embeddings")
    op.drop_index(op.f("ix_semantic_embeddings_source_id"), table_name="semantic_embeddings")
    op.drop_index(op.f("ix_semantic_embeddings_id"), table_name="semantic_embeddings")
    op.drop_table("semantic_embeddings")
