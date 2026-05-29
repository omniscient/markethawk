"""Add refresh settings for news

Revision ID: a44499eb41eb
Revises: f3f5fcfd7176
Create Date: 2026-03-23 11:06:03.704801

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "a44499eb41eb"
down_revision: Union[str, None] = "9263d8fa019f"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "news_preferences",
        sa.Column("refresh_interval_minutes", sa.Integer(), nullable=True),
    )
    op.add_column(
        "news_preferences", sa.Column("last_polled_at", sa.DateTime(), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("news_preferences", "last_polled_at")
    op.drop_column("news_preferences", "refresh_interval_minutes")
