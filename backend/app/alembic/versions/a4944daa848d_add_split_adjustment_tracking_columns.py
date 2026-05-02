"""add_split_adjustment_tracking_columns

Revision ID: a4944daa848d
Revises: e9bd09ec24b0
Create Date: 2026-05-02 13:38:23.318853

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'a4944daa848d'
down_revision: Union[str, None] = 'e9bd09ec24b0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()
    conn.execute(sa.text("""
        DELETE FROM stock_splits
        WHERE id NOT IN (
            SELECT MIN(id) FROM stock_splits GROUP BY ticker, execution_date
        )
    """))

    op.add_column('stock_splits', sa.Column('source', sa.String(length=20), nullable=False, server_default='polygon'))
    op.add_column('stock_splits', sa.Column('detected_at', sa.DateTime(), nullable=True))
    op.add_column('stock_splits', sa.Column('adjustments_applied_at', sa.DateTime(), nullable=True))
    op.create_unique_constraint('uq_split_ticker_date', 'stock_splits', ['ticker', 'execution_date'])


def downgrade() -> None:
    op.drop_constraint('uq_split_ticker_date', 'stock_splits', type_='unique')
    op.drop_column('stock_splits', 'adjustments_applied_at')
    op.drop_column('stock_splits', 'detected_at')
    op.drop_column('stock_splits', 'source')
