"""add universe_id to scanner_configs

Revision ID: c7d8e9f0a1b2
Revises: c7e2a9f4b1d3
Create Date: 2026-06-03 00:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c7d8e9f0a1b2"
down_revision: Union[str, None] = "c7e2a9f4b1d3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Step 1: Add the column as nullable so existing rows are not rejected.
    op.add_column(
        "scanner_configs",
        sa.Column(
            "universe_id",
            sa.Integer(),
            sa.ForeignKey("stock_universes.id"),
            nullable=True,
        ),
    )

    # Step 2: Backfill all existing rows with universe_id = 1 (the system
    # default universe, confirmed by the scanner.default_universe = 1 seed).
    op.execute(
        sa.text("UPDATE scanner_configs SET universe_id = 1 WHERE universe_id IS NULL")
    )

    # Step 3: Enforce NOT NULL now that all rows have a value.
    op.alter_column("scanner_configs", "universe_id", nullable=False)


def downgrade() -> None:
    op.drop_column("scanner_configs", "universe_id")
