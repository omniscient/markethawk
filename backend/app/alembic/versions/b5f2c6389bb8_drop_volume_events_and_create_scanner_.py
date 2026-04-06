"""drop volume_events and create scanner_events

Revision ID: b5f2c6389bb8
Revises: e73f8ba2441d
Create Date: 2026-04-03 12:22:51.288860

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'b5f2c6389bb8'
down_revision: Union[str, None] = 'e73f8ba2441d'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Create scanner_events table
    op.create_table('scanner_events',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('uuid', sa.Uuid(), nullable=True),
        sa.Column('ticker', sa.String(length=10), nullable=False),
        sa.Column('event_date', sa.Date(), nullable=False),
        sa.Column('scanner_type', sa.String(length=50), nullable=False),
        sa.Column('summary', sa.String(length=500), nullable=True),
        sa.Column('severity', sa.String(length=10), nullable=True),
        sa.Column('previous_close', sa.Numeric(), nullable=True),
        sa.Column('opening_price', sa.Numeric(), nullable=True),
        sa.Column('closing_price', sa.Numeric(), nullable=True),
        sa.Column('indicators', sa.JSON(), nullable=False),
        sa.Column('criteria_met', sa.JSON(), nullable=False),
        sa.Column('metadata', sa.JSON(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('ticker', 'event_date', 'scanner_type', name='uq_scanner_event')
    )
    op.create_index(op.f('ix_scanner_events_event_date'), 'scanner_events', ['event_date'], unique=False)
    op.create_index(op.f('ix_scanner_events_id'), 'scanner_events', ['id'], unique=False)
    op.create_index(op.f('ix_scanner_events_scanner_type'), 'scanner_events', ['scanner_type'], unique=False)
    op.create_index(op.f('ix_scanner_events_ticker'), 'scanner_events', ['ticker'], unique=False)
    op.create_index(op.f('ix_scanner_events_uuid'), 'scanner_events', ['uuid'], unique=True)
    
    # 2. Drop volume_events table and all its dependents (views like recent_volume_events, fk in alert_history)
    op.execute("DROP TABLE volume_events CASCADE")


def downgrade() -> None:
    # Downgrade is approximate as it won't restoreCASCADE dropped objects unless explicitly defined
    # But since we're in "Big-bang" mode, full restore is difficult without the cascade list.
    
    # Recreate scanner_events table for safety in rollback
    op.drop_table('scanner_events')

    # Recreate volume_events table
    op.create_table('volume_events',
        sa.Column('id', sa.INTEGER(), autoincrement=True, nullable=False),
        sa.Column('uuid', sa.UUID(), server_default=sa.text('uuid_generate_v4()'), autoincrement=False, nullable=True),
        sa.Column('ticker', sa.VARCHAR(length=10), autoincrement=False, nullable=False),
        sa.Column('event_date', sa.DATE(), autoincrement=False, nullable=False),
        sa.Column('event_type', sa.VARCHAR(length=50), autoincrement=False, nullable=False),
        sa.Column('pre_market_volume', sa.BIGINT(), autoincrement=False, nullable=False),
        sa.Column('regular_volume', sa.BIGINT(), autoincrement=False, nullable=True),
        sa.Column('avg_volume_20d', sa.BIGINT(), autoincrement=False, nullable=False),
        sa.Column('avg_volume_50d', sa.BIGINT(), autoincrement=False, nullable=True),
        sa.Column('relative_volume', sa.NUMERIC(), autoincrement=False, nullable=False),
        sa.Column('volume_spike_ratio', sa.NUMERIC(), autoincrement=False, nullable=False),
        sa.Column('previous_close', sa.NUMERIC(), autoincrement=False, nullable=False),
        sa.Column('pre_market_high', sa.NUMERIC(), autoincrement=False, nullable=True),
        sa.Column('pre_market_low', sa.NUMERIC(), autoincrement=False, nullable=True),
        sa.Column('opening_price', sa.NUMERIC(), autoincrement=False, nullable=True),
        sa.Column('closing_price', sa.NUMERIC(), autoincrement=False, nullable=True),
        sa.Column('price_change_pct', sa.NUMERIC(), autoincrement=False, nullable=True),
        sa.Column('price_gap_pct', sa.NUMERIC(), autoincrement=False, nullable=True),
        sa.Column('criteria_met', postgresql.JSONB(astext_type=sa.Text()), autoincrement=False, nullable=False),
        sa.Column('news_count', sa.INTEGER(), server_default=sa.text('0'), autoincrement=False, nullable=True),
        sa.Column('earnings_date', sa.DATE(), autoincrement=False, nullable=True),
        sa.Column('market_cap_at_event', sa.BIGINT(), autoincrement=False, nullable=True),
        sa.Column('raw_data', postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), autoincrement=False, nullable=True),
        sa.Column('created_at', postgresql.TIMESTAMP(), server_default=sa.text('now()'), autoincrement=False, nullable=True),
        sa.Column('updated_at', postgresql.TIMESTAMP(), server_default=sa.text('now()'), autoincrement=False, nullable=True),
        sa.Column('regular_high', sa.NUMERIC(), autoincrement=False, nullable=True),
        sa.Column('regular_low', sa.NUMERIC(), autoincrement=False, nullable=True),
        sa.Column('post_market_high', sa.NUMERIC(), autoincrement=False, nullable=True),
        sa.Column('post_market_low', sa.NUMERIC(), autoincrement=False, nullable=True),
        sa.Column('total_day_high', sa.NUMERIC(), autoincrement=False, nullable=True),
        sa.Column('total_day_low', sa.NUMERIC(), autoincrement=False, nullable=True),
        sa.Column('fade_from_high_pct', sa.NUMERIC(), autoincrement=False, nullable=True),
        sa.Column('day_range_pct', sa.NUMERIC(), autoincrement=False, nullable=True),
        sa.Column('gap_pct', sa.NUMERIC(), autoincrement=False, nullable=True),
        sa.Column('outstanding_shares', sa.NUMERIC(), autoincrement=False, nullable=True),
        sa.Column('float_rotation_pct', sa.NUMERIC(), autoincrement=False, nullable=True),
        sa.Column('catalyst_tags', postgresql.JSON(astext_type=sa.Text()), autoincrement=False, nullable=True),
        sa.Column('catalyst_summary', sa.VARCHAR(), autoincrement=False, nullable=True),
        sa.Column('recent_split_date', sa.DATE(), autoincrement=False, nullable=True),
        sa.PrimaryKeyConstraint('id', name='volume_events_pkey'),
        sa.UniqueConstraint('uuid', name='volume_events_uuid_key')
    )
    op.create_index('idx_volume_events_type', 'volume_events', ['event_type'], unique=False)
    op.create_index('idx_volume_events_ticker', 'volume_events', ['ticker'], unique=False)
    op.create_index('idx_volume_events_relative_vol', 'volume_events', ['relative_volume'], unique=False)
    op.create_index('idx_volume_events_date', 'volume_events', ['event_date'], unique=False)
