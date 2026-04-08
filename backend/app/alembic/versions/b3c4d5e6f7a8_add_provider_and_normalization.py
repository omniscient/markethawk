"""add provider to stock_aggregates and normalization fields to quality reports

Revision ID: b3c4d5e6f7a8
Revises: a1b2c3d4e5f6
Create Date: 2026-04-07 22:00:00.000000

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = 'b3c4d5e6f7a8'
down_revision: Union[str, tuple] = 'a1b2c3d4e5f6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── stock_aggregates: add provider column ────────────────────────────────
    op.execute("""
        ALTER TABLE stock_aggregates
        ADD COLUMN IF NOT EXISTS provider VARCHAR(50) DEFAULT 'polygon'
    """)

    # ── universe_quality_reports: add normalization tracking columns ─────────
    op.execute("""
        ALTER TABLE universe_quality_reports
        ADD COLUMN IF NOT EXISTS normalization_status VARCHAR(20)
    """)
    op.execute("""
        ALTER TABLE universe_quality_reports
        ADD COLUMN IF NOT EXISTS normalization_data JSON
    """)


def downgrade() -> None:
    op.execute("ALTER TABLE universe_quality_reports DROP COLUMN IF EXISTS normalization_data")
    op.execute("ALTER TABLE universe_quality_reports DROP COLUMN IF EXISTS normalization_status")
    op.execute("ALTER TABLE stock_aggregates DROP COLUMN IF EXISTS provider")
