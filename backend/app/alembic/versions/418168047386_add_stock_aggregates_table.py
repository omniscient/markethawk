"""add stock aggregates table

Revision ID: 418168047386
Revises: dd23e308d7c0
Create Date: 2025-12-15 22:00:51.021787

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '418168047386'
down_revision: Union[str, None] = 'dd23e308d7c0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('stock_aggregates',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('ticker', sa.String(length=10), nullable=False),
    sa.Column('timestamp', sa.DateTime(), nullable=False),
    sa.Column('multiplier', sa.Integer(), nullable=False),
    sa.Column('timespan', sa.String(length=20), nullable=False),
    sa.Column('open', sa.Numeric(), nullable=False),
    sa.Column('high', sa.Numeric(), nullable=False),
    sa.Column('low', sa.Numeric(), nullable=False),
    sa.Column('close', sa.Numeric(), nullable=False),
    sa.Column('volume', sa.BigInteger(), nullable=False),
    sa.Column('vwap', sa.Numeric(), nullable=True),
    sa.Column('transactions', sa.Integer(), nullable=True),
    sa.Column('is_pre_market', sa.Boolean(), nullable=True),
    sa.Column('created_at', sa.DateTime(), nullable=True),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_stock_aggregates_id'), 'stock_aggregates', ['id'], unique=False)
    op.create_index(op.f('ix_stock_aggregates_is_pre_market'), 'stock_aggregates', ['is_pre_market'], unique=False)
    op.create_index(op.f('ix_stock_aggregates_ticker'), 'stock_aggregates', ['ticker'], unique=False)
    op.create_index(op.f('ix_stock_aggregates_timestamp'), 'stock_aggregates', ['timestamp'], unique=False)
    op.create_index('idx_ticker_time', 'stock_aggregates', ['ticker', 'timestamp'], unique=False)
    op.create_index('idx_ticker_time_pre', 'stock_aggregates', ['ticker', 'timestamp', 'is_pre_market'], unique=False)


def downgrade() -> None:
    op.drop_index('idx_ticker_time_pre', table_name='stock_aggregates')
    op.drop_index('idx_ticker_time', table_name='stock_aggregates')
    op.drop_index(op.f('ix_stock_aggregates_timestamp'), table_name='stock_aggregates')
    op.drop_index(op.f('ix_stock_aggregates_ticker'), table_name='stock_aggregates')
    op.drop_index(op.f('ix_stock_aggregates_is_pre_market'), table_name='stock_aggregates')
    op.drop_index(op.f('ix_stock_aggregates_id'), table_name='stock_aggregates')
    op.drop_table('stock_aggregates')
