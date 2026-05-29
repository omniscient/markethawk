"""add stock universe tickers table

Revision ID: 529368159157
Revises: 418168047386
Create Date: 2025-12-17 07:45:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "529368159157"
down_revision: Union[str, None] = "418168047386"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "stock_universe_tickers",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("universe_id", sa.Integer(), nullable=False),
        sa.Column("ticker", sa.String(length=10), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_stock_universe_tickers_id"),
        "stock_universe_tickers",
        ["id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_stock_universe_tickers_universe_id"),
        "stock_universe_tickers",
        ["universe_id"],
        unique=False,
    )
    op.create_index(
        "ix_universe_ticker",
        "stock_universe_tickers",
        ["universe_id", "ticker"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_universe_ticker", table_name="stock_universe_tickers")
    op.drop_index(
        op.f("ix_stock_universe_tickers_universe_id"),
        table_name="stock_universe_tickers",
    )
    op.drop_index(
        op.f("ix_stock_universe_tickers_id"), table_name="stock_universe_tickers"
    )
    op.drop_table("stock_universe_tickers")
