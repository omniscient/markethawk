"""drop_orphaned_regime_schema

Revision ID: b5c6d7e8f9a0
Revises: 395c7409c8e9
Create Date: 2026-06-13 06:15:00.000000

PR #106 landed in a preview build and ran against the prod DB but was never
merged to main. The regime_models table and scanner_events.regime column are
orphaned — no SQLAlchemy model references them. This migration drops them so
the schema matches the codebase.

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "b5c6d7e8f9a0"
down_revision: Union[str, None] = "395c7409c8e9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_index("ix_scanner_events_regime", table_name="scanner_events")
    op.drop_column("scanner_events", "regime")

    op.drop_index(op.f("ix_regime_models_id"), table_name="regime_models")
    op.drop_index("ix_regime_models_status_version", table_name="regime_models")
    op.drop_index(op.f("ix_regime_models_version"), table_name="regime_models")
    op.drop_table("regime_models")


def downgrade() -> None:
    op.create_table(
        "regime_models",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column(
            "state_label_mapping",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column("n_states", sa.Integer(), nullable=False),
        sa.Column("bic_score", sa.Float(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("model_b64", sa.Text(), nullable=False),
        sa.Column("feature_set", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("data_start_date", sa.Date(), nullable=False),
        sa.Column("data_end_date", sa.Date(), nullable=False),
        sa.Column("trained_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_regime_models_id"), "regime_models", ["id"], unique=False
    )
    op.create_index(
        "ix_regime_models_status_version",
        "regime_models",
        ["status", "version"],
        unique=False,
    )
    op.create_index(
        op.f("ix_regime_models_version"), "regime_models", ["version"], unique=False
    )

    op.add_column(
        "scanner_events",
        sa.Column("regime", sa.String(length=30), nullable=True),
    )
    op.create_index(
        "ix_scanner_events_regime", "scanner_events", ["regime"], unique=False
    )
