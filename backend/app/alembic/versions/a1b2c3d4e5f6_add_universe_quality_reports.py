"""add universe_quality_reports table

Revision ID: a1b2c3d4e5f6
Revises: 39cb3da5ccb4
Create Date: 2026-04-07 20:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "a1b2c3d4e5f6"
down_revision: Union[str, tuple] = ("39cb3da5ccb4", "fa2957d31876")
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Use raw SQL so we can guard with IF NOT EXISTS
    op.execute("""
        CREATE TABLE IF NOT EXISTS universe_quality_reports (
            id SERIAL NOT NULL,
            universe_id INTEGER NOT NULL,
            status VARCHAR(20) NOT NULL DEFAULT 'pending',
            overall_grade VARCHAR(1),
            overall_score NUMERIC,
            ticker_count INTEGER,
            started_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT now(),
            generated_at TIMESTAMP WITHOUT TIME ZONE,
            report_data JSON,
            error_message TEXT,
            PRIMARY KEY (id),
            UNIQUE (universe_id),
            FOREIGN KEY (universe_id) REFERENCES stock_universes (id) ON DELETE CASCADE
        )
    """)
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_universe_quality_reports_id ON universe_quality_reports (id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_universe_quality_reports_universe_id ON universe_quality_reports (universe_id)"
    )
    return  # skip the original create_table below
    op.create_table(
        "universe_quality_reports",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("universe_id", sa.Integer(), nullable=False),
        sa.Column(
            "status", sa.String(length=20), nullable=False, server_default="pending"
        ),
        sa.Column("overall_grade", sa.String(length=1), nullable=True),
        sa.Column("overall_score", sa.Numeric(), nullable=True),
        sa.Column("ticker_count", sa.Integer(), nullable=True),
        sa.Column(
            "started_at", sa.DateTime(), nullable=False, server_default=sa.text("now()")
        ),
        sa.Column("generated_at", sa.DateTime(), nullable=True),
        sa.Column("report_data", postgresql.JSON(astext_type=sa.Text()), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(
            ["universe_id"], ["stock_universes.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("universe_id"),
    )
    op.create_index(
        "ix_universe_quality_reports_id", "universe_quality_reports", ["id"]
    )
    op.create_index(
        "ix_universe_quality_reports_universe_id",
        "universe_quality_reports",
        ["universe_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_universe_quality_reports_universe_id", table_name="universe_quality_reports"
    )
    op.drop_index(
        "ix_universe_quality_reports_id", table_name="universe_quality_reports"
    )
    op.drop_table("universe_quality_reports")
