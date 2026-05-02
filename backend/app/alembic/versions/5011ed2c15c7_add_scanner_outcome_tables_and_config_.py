"""add_scanner_outcome_tables_and_config_columns

Revision ID: 5011ed2c15c7
Revises: 6541905c6b14
Create Date: 2026-04-30 17:20:17.932338

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '5011ed2c15c7'
down_revision: Union[str, None] = '6541905c6b14'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('scanner_outcome_snapshots',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('scanner_event_id', sa.Integer(), nullable=False),
    sa.Column('interval_key', sa.String(length=10), nullable=False),
    sa.Column('reference_price', sa.Numeric(), nullable=False),
    sa.Column('snapshot_price', sa.Numeric(), nullable=True),
    sa.Column('pct_change', sa.Numeric(), nullable=True),
    sa.Column('high_since_signal', sa.Numeric(), nullable=True),
    sa.Column('low_since_signal', sa.Numeric(), nullable=True),
    sa.Column('volume_since_signal', sa.BigInteger(), nullable=True),
    sa.Column('captured_at', sa.DateTime(), nullable=True),
    sa.Column('status', sa.String(length=20), nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=True),
    sa.ForeignKeyConstraint(['scanner_event_id'], ['scanner_events.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('scanner_event_id', 'interval_key', name='uq_outcome_snapshot_event_interval')
    )
    op.create_index(op.f('ix_scanner_outcome_snapshots_id'), 'scanner_outcome_snapshots', ['id'], unique=False)
    op.create_index(op.f('ix_scanner_outcome_snapshots_scanner_event_id'), 'scanner_outcome_snapshots', ['scanner_event_id'], unique=False)
    op.create_index(op.f('ix_scanner_outcome_snapshots_status'), 'scanner_outcome_snapshots', ['status'], unique=False)
    op.create_table('scanner_outcome_summaries',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('scanner_event_id', sa.Integer(), nullable=False),
    sa.Column('reference_price', sa.Numeric(), nullable=False),
    sa.Column('mfe_pct', sa.Numeric(), nullable=True),
    sa.Column('mfe_time_minutes', sa.Integer(), nullable=True),
    sa.Column('mae_pct', sa.Numeric(), nullable=True),
    sa.Column('mae_time_minutes', sa.Integer(), nullable=True),
    sa.Column('mfe_mae_ratio', sa.Numeric(), nullable=True),
    sa.Column('r_multiple', sa.Numeric(), nullable=True),
    sa.Column('eod_pct_change', sa.Numeric(), nullable=True),
    sa.Column('follow_through', sa.Boolean(), nullable=True),
    sa.Column('gap_filled', sa.Boolean(), nullable=True),
    sa.Column('is_complete', sa.Boolean(), nullable=True),
    sa.Column('completed_at', sa.DateTime(), nullable=True),
    sa.Column('created_at', sa.DateTime(), nullable=True),
    sa.Column('updated_at', sa.DateTime(), nullable=True),
    sa.ForeignKeyConstraint(['scanner_event_id'], ['scanner_events.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_scanner_outcome_summaries_id'), 'scanner_outcome_summaries', ['id'], unique=False)
    op.create_index(op.f('ix_scanner_outcome_summaries_is_complete'), 'scanner_outcome_summaries', ['is_complete'], unique=False)
    op.create_index(op.f('ix_scanner_outcome_summaries_scanner_event_id'), 'scanner_outcome_summaries', ['scanner_event_id'], unique=True)
    op.add_column('scanner_configs', sa.Column('outcome_config', postgresql.JSONB(astext_type=sa.Text()), nullable=True))
    op.add_column('scanner_configs', sa.Column('data_requirements', postgresql.JSONB(astext_type=sa.Text()), nullable=True))


def downgrade() -> None:
    op.drop_column('scanner_configs', 'data_requirements')
    op.drop_column('scanner_configs', 'outcome_config')
    op.drop_index(op.f('ix_scanner_outcome_summaries_scanner_event_id'), table_name='scanner_outcome_summaries')
    op.drop_index(op.f('ix_scanner_outcome_summaries_is_complete'), table_name='scanner_outcome_summaries')
    op.drop_index(op.f('ix_scanner_outcome_summaries_id'), table_name='scanner_outcome_summaries')
    op.drop_table('scanner_outcome_summaries')
    op.drop_index(op.f('ix_scanner_outcome_snapshots_status'), table_name='scanner_outcome_snapshots')
    op.drop_index(op.f('ix_scanner_outcome_snapshots_scanner_event_id'), table_name='scanner_outcome_snapshots')
    op.drop_index(op.f('ix_scanner_outcome_snapshots_id'), table_name='scanner_outcome_snapshots')
    op.drop_table('scanner_outcome_snapshots')
