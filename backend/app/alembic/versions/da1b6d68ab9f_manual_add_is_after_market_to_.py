"""Manual add is_after_market to StockAggregate

Revision ID: da1b6d68ab9f
Revises: b55610fc52fc
Create Date: 2026-03-28 10:59:26.669100

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'da1b6d68ab9f'
down_revision: Union[str, None] = 'b55610fc52fc'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('stock_aggregates', sa.Column('is_after_market', sa.Boolean(), nullable=True, server_default='false'))
    op.create_index(op.f('ix_stock_aggregates_is_after_market'), 'stock_aggregates', ['is_after_market'], unique=False)

def downgrade() -> None:
    op.drop_index(op.f('ix_stock_aggregates_is_after_market'), table_name='stock_aggregates')
    op.drop_column('stock_aggregates', 'is_after_market')
