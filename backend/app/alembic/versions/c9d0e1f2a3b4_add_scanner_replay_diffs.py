"""add_scanner_replay_diffs

Revision ID: c9d0e1f2a3b4
Revises: b45cf49c1c5a
Create Date: 2026-06-21 04:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "c9d0e1f2a3b4"
down_revision: Union[str, None] = "b45cf49c1c5a"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "scanner_replay_diffs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("scanner_type", sa.String(length=50), nullable=False),
        sa.Column("scan_date", sa.Date(), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("has_drift", sa.Boolean(), nullable=False),
        sa.Column("live_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("replay_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "missing_in_replay_count",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
        sa.Column(
            "new_in_replay_count", sa.Integer(), nullable=False, server_default="0"
        ),
        sa.Column("matched_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "missing_in_replay",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default="[]",
        ),
        sa.Column(
            "new_in_replay",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default="[]",
        ),
        sa.Column(
            "metric_deltas",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default="[]",
        ),
        sa.Column(
            "drift_kinds",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default="[]",
        ),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("scanner_type", "scan_date", name="uq_scanner_replay_diff"),
    )
    op.create_index(
        op.f("ix_scanner_replay_diffs_id"),
        "scanner_replay_diffs",
        ["id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_scanner_replay_diffs_scanner_type"),
        "scanner_replay_diffs",
        ["scanner_type"],
        unique=False,
    )
    op.create_index(
        op.f("ix_scanner_replay_diffs_scan_date"),
        "scanner_replay_diffs",
        ["scan_date"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_scanner_replay_diffs_scan_date"), table_name="scanner_replay_diffs"
    )
    op.drop_index(
        op.f("ix_scanner_replay_diffs_scanner_type"),
        table_name="scanner_replay_diffs",
    )
    op.drop_index(op.f("ix_scanner_replay_diffs_id"), table_name="scanner_replay_diffs")
    op.drop_table("scanner_replay_diffs")
