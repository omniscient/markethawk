"""expand_column_lengths

Revision ID: fa2957d31876
Revises: 39cb3da5ccb4
Create Date: 2026-04-06 14:49:40.109142

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "fa2957d31876"
down_revision: Union[str, None] = "39cb3da5ccb4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # --- Drop dependent views ---
    op.execute("DROP VIEW IF EXISTS active_monitored_stocks")

    # --- monitored_stocks ---
    op.alter_column(
        "monitored_stocks",
        "ticker",
        existing_type=sa.VARCHAR(length=10),
        type_=sa.String(length=50),
        existing_nullable=False,
    )
    op.alter_column(
        "monitored_stocks",
        "company_name",
        existing_type=sa.VARCHAR(length=200),
        type_=sa.String(length=1000),
        existing_nullable=True,
    )
    op.alter_column(
        "monitored_stocks",
        "sector",
        existing_type=sa.VARCHAR(length=100),
        type_=sa.String(length=255),
        existing_nullable=True,
    )
    op.alter_column(
        "monitored_stocks",
        "industry",
        existing_type=sa.VARCHAR(length=100),
        type_=sa.String(length=255),
        existing_nullable=True,
    )

    # --- stock_universe_tickers ---
    op.alter_column(
        "stock_universe_tickers",
        "ticker",
        existing_type=sa.VARCHAR(length=10),
        type_=sa.String(length=50),
        existing_nullable=False,
    )

    # --- Re-create dependent views ---
    op.execute(
        "CREATE VIEW active_monitored_stocks AS SELECT * FROM monitored_stocks WHERE is_active = true"
    )


def downgrade() -> None:
    # --- Drop dependent views ---
    op.execute("DROP VIEW IF EXISTS active_monitored_stocks")

    # --- stock_universe_tickers ---
    op.alter_column(
        "stock_universe_tickers",
        "ticker",
        existing_type=sa.String(length=50),
        type_=sa.VARCHAR(length=10),
        existing_nullable=False,
    )

    # --- monitored_stocks ---
    op.alter_column(
        "monitored_stocks",
        "industry",
        existing_type=sa.String(length=255),
        type_=sa.VARCHAR(length=100),
        existing_nullable=True,
    )
    op.alter_column(
        "monitored_stocks",
        "sector",
        existing_type=sa.String(length=255),
        type_=sa.VARCHAR(length=100),
        existing_nullable=True,
    )
    op.alter_column(
        "monitored_stocks",
        "company_name",
        existing_type=sa.String(length=1000),
        type_=sa.VARCHAR(length=200),
        existing_nullable=True,
    )
    op.alter_column(
        "monitored_stocks",
        "ticker",
        existing_type=sa.String(length=50),
        type_=sa.VARCHAR(length=10),
        existing_nullable=False,
    )

    # --- Re-create dependent views ---
    op.execute(
        "CREATE VIEW active_monitored_stocks AS SELECT * FROM monitored_stocks WHERE is_active = true"
    )
