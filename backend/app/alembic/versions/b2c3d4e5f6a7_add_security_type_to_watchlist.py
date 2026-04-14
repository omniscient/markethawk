"""add_security_type_to_watchlist

Revision ID: b2c3d4e5f6a7
Revises: 4ceeeb83c67a
Create Date: 2026-04-13 14:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'b2c3d4e5f6a7'
down_revision: Union[str, None] = '4ceeeb83c67a'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('active_watchlist',
        sa.Column('security_type', sa.String(length=10), nullable=False, server_default='STK')
    )
    op.add_column('active_watchlist',
        sa.Column('exchange', sa.String(length=20), nullable=True)
    )


def downgrade() -> None:
    op.drop_column('active_watchlist', 'exchange')
    op.drop_column('active_watchlist', 'security_type')
