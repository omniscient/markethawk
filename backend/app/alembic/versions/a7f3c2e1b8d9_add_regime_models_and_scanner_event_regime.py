"""add_regime_models_and_scanner_event_regime

Revision ID: a7f3c2e1b8d9
Revises: d0e1f2a3b4c5
Create Date: 2026-06-14 20:55:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "a7f3c2e1b8d9"
down_revision: Union[str, None] = "d0e1f2a3b4c5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "regime_models",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("n_states", sa.Integer(), nullable=False),
        sa.Column("model_b64", sa.Text(), nullable=False),
        sa.Column(
            "feature_set",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column(
            "state_label_mapping",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column("data_start_date", sa.Date(), nullable=False),
        sa.Column("data_end_date", sa.Date(), nullable=False),
        sa.Column("bic_score", sa.Float(), nullable=True),
        sa.Column("trained_at", sa.DateTime(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_regime_models_id"), "regime_models", ["id"], unique=False)
    op.create_index(
        op.f("ix_regime_models_version"), "regime_models", ["version"], unique=False
    )
    op.create_index(
        "ix_regime_models_status_version",
        "regime_models",
        ["status", "version"],
        unique=False,
    )

    op.add_column(
        "scanner_events",
        sa.Column("regime", sa.String(length=30), nullable=True),
    )
    op.create_index(
        "ix_scanner_events_regime", "scanner_events", ["regime"], unique=False
    )


def downgrade() -> None:
    op.drop_index("ix_scanner_events_regime", table_name="scanner_events")
    op.drop_column("scanner_events", "regime")

    op.drop_index("ix_regime_models_status_version", table_name="regime_models")
    op.drop_index(op.f("ix_regime_models_version"), table_name="regime_models")
    op.drop_index(op.f("ix_regime_models_id"), table_name="regime_models")
    op.drop_table("regime_models")
