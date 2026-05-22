"""add_signal_reviews

Revision ID: b3e8f2a1c9d7
Revises: fa2957d31876
Create Date: 2026-05-22 19:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'b3e8f2a1c9d7'
down_revision: Union[str, None] = 'fa2957d31876'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'signal_reviews',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('scanner_event_id', sa.Integer(), nullable=False),
        sa.Column('verdict', sa.String(length=20), nullable=False),
        sa.Column('reject_reason', sa.String(length=50), nullable=True),
        sa.Column('notes', sa.String(length=1000), nullable=True),
        sa.Column('enhance_suggestion', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('reviewed_at', sa.DateTime(), nullable=False),
        sa.Column('reviewed_by', sa.String(length=100), nullable=True),
        sa.ForeignKeyConstraint(['scanner_event_id'], ['scanner_events.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_signal_reviews_id'), 'signal_reviews', ['id'], unique=False)
    op.create_index(op.f('ix_signal_reviews_scanner_event_id'), 'signal_reviews', ['scanner_event_id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_signal_reviews_scanner_event_id'), table_name='signal_reviews')
    op.drop_index(op.f('ix_signal_reviews_id'), table_name='signal_reviews')
    op.drop_table('signal_reviews')
