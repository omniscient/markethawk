"""add_cached_stats_to_stock_universe

Revision ID: 7cc4463907cd
Revises: d1e2f3a4b5c6
Create Date: 2026-04-12 14:19:08.929748

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "7cc4463907cd"
down_revision: Union[str, None] = "d1e2f3a4b5c6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "stock_universes", sa.Column("cached_ticker_count", sa.Integer(), nullable=True)
    )
    op.add_column(
        "stock_universes",
        sa.Column("cached_aggregate_count", sa.BigInteger(), nullable=True),
    )
    op.add_column(
        "stock_universes", sa.Column("cached_min_date", sa.DateTime(), nullable=True)
    )
    op.add_column(
        "stock_universes", sa.Column("cached_max_date", sa.DateTime(), nullable=True)
    )
    op.add_column(
        "stock_universes", sa.Column("cached_timespans", sa.JSON(), nullable=True)
    )
    op.add_column(
        "stock_universes", sa.Column("stats_refreshed_at", sa.DateTime(), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("stock_universes", "stats_refreshed_at")
    op.drop_column("stock_universes", "cached_timespans")
    op.drop_column("stock_universes", "cached_max_date")
    op.drop_column("stock_universes", "cached_min_date")
    op.drop_column("stock_universes", "cached_aggregate_count")
    op.drop_column("stock_universes", "cached_ticker_count")
