"""add_scanner_event_narratives

Revision ID: b6c7d8e9f0a1
Revises: a2b3c4d5e6f7
Create Date: 2026-07-04 00:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "b6c7d8e9f0a1"
down_revision: Union[str, None] = "a2b3c4d5e6f7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "scanner_event_narratives",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("scanner_event_id", sa.Integer(), nullable=False),
        sa.Column(
            "feature_area",
            sa.String(length=50),
            nullable=False,
            server_default="scanner_narrative",
        ),
        sa.Column("narrative_text", sa.Text(), nullable=False),
        sa.Column("provider", sa.String(length=50), nullable=False),
        sa.Column("model", sa.String(length=100), nullable=False),
        sa.Column("prompt_version", sa.String(length=50), nullable=False),
        sa.Column("brief_schema_version", sa.String(length=50), nullable=False),
        sa.Column("brief_fingerprint", sa.String(length=64), nullable=False),
        sa.Column(
            "input_payload",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default="{}",
        ),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(
            ["scanner_event_id"], ["scanner_events.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "scanner_event_id",
            "feature_area",
            "provider",
            "model",
            "prompt_version",
            name="uq_scanner_event_narrative_cache",
        ),
    )
    op.create_index(
        op.f("ix_scanner_event_narratives_id"),
        "scanner_event_narratives",
        ["id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_scanner_event_narratives_scanner_event_id"),
        "scanner_event_narratives",
        ["scanner_event_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_scanner_event_narratives_brief_fingerprint"),
        "scanner_event_narratives",
        ["brief_fingerprint"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_scanner_event_narratives_brief_fingerprint"),
        table_name="scanner_event_narratives",
    )
    op.drop_index(
        op.f("ix_scanner_event_narratives_scanner_event_id"),
        table_name="scanner_event_narratives",
    )
    op.drop_index(
        op.f("ix_scanner_event_narratives_id"),
        table_name="scanner_event_narratives",
    )
    op.drop_table("scanner_event_narratives")
