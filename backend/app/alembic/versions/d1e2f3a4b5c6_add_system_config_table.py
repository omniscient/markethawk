"""Add system_config table

Revision ID: d1e2f3a4b5c6
Revises: ccfae364a978
Create Date: 2026-04-12 10:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "d1e2f3a4b5c6"
down_revision: Union[str, None] = "ccfae364a978"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "system_config",
        sa.Column("key", sa.String(), nullable=False),
        sa.Column("value", sa.String(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("key"),
    )
    op.create_index("ix_system_config_key", "system_config", ["key"])

    # Seed default: free-tier Polygon delay
    op.execute(
        "INSERT INTO system_config (key, value, updated_at) "
        "VALUES ('polygon_crawl_delay', '15.0', NOW())"
    )


def downgrade() -> None:
    op.drop_index("ix_system_config_key", table_name="system_config")
    op.drop_table("system_config")
