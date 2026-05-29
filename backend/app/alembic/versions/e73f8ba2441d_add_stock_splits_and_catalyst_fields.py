"""Add stock splits and catalyst fields

Revision ID: e73f8ba2441d
Revises: f652e7838258
Create Date: 2026-03-30 20:04:11.580516

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "e73f8ba2441d"
down_revision: Union[str, None] = "f652e7838258"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "stock_splits",
        sa.Column("id", sa.Integer(), primary_key=True, index=True),
        sa.Column("ticker", sa.String(length=10), nullable=False, index=True),
        sa.Column("execution_date", sa.Date(), nullable=False, index=True),
        sa.Column("split_from", sa.Numeric(), nullable=False),
        sa.Column("split_to", sa.Numeric(), nullable=False),
    )

    op.add_column(
        "volume_events", sa.Column("outstanding_shares", sa.Numeric(), nullable=True)
    )
    op.add_column(
        "volume_events", sa.Column("float_rotation_pct", sa.Numeric(), nullable=True)
    )
    op.add_column("volume_events", sa.Column("catalyst_tags", sa.JSON(), nullable=True))
    op.add_column(
        "volume_events", sa.Column("catalyst_summary", sa.String(), nullable=True)
    )
    op.add_column(
        "volume_events", sa.Column("recent_split_date", sa.Date(), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("volume_events", "recent_split_date")
    op.drop_column("volume_events", "catalyst_summary")
    op.drop_column("volume_events", "catalyst_tags")
    op.drop_column("volume_events", "float_rotation_pct")
    op.drop_column("volume_events", "outstanding_shares")
    op.drop_table("stock_splits")
