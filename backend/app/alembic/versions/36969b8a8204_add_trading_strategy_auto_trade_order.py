"""add_trading_strategy_auto_trade_order

Revision ID: 36969b8a8204
Revises: b2c3d4e5f6a7
Create Date: 2026-04-14 12:33:34.339824

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '36969b8a8204'
down_revision: Union[str, None] = 'b2c3d4e5f6a7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── Create trading_strategies ────────────────────────────────────────
    op.create_table(
        'trading_strategies',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(length=200), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('is_active', sa.Boolean(), nullable=False),
        sa.Column('paper_mode', sa.Boolean(), nullable=False),
        sa.Column('requires_approval', sa.Boolean(), nullable=False),
        sa.Column('risk_per_trade_pct', sa.Numeric(), nullable=False),
        sa.Column('max_position_usd', sa.Numeric(), nullable=True),
        sa.Column('max_trades_per_day', sa.Integer(), nullable=False),
        sa.Column('max_concurrent_positions', sa.Integer(), nullable=False),
        sa.Column('entry_type', sa.String(length=20), nullable=False),
        sa.Column('limit_offset_pct', sa.Numeric(), nullable=False),
        sa.Column('stop_pct', sa.Numeric(), nullable=False),
        sa.Column('risk_reward_ratio', sa.Numeric(), nullable=False),
        sa.Column('max_slippage_pct', sa.Numeric(), nullable=False),
        sa.Column('allowed_sessions', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('direction', sa.String(length=20), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('name'),
    )
    op.create_index(op.f('ix_trading_strategies_id'), 'trading_strategies', ['id'], unique=False)

    # ── Create auto_trade_orders ─────────────────────────────────────────
    op.create_table(
        'auto_trade_orders',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('alert_rule_id', sa.Integer(), nullable=True),
        sa.Column('scanner_event_id', sa.Integer(), nullable=True),
        sa.Column('trading_strategy_id', sa.Integer(), nullable=True),
        sa.Column('symbol', sa.String(length=10), nullable=False),
        sa.Column('side', sa.String(length=10), nullable=False),
        sa.Column('event_date', sa.Date(), nullable=False),
        sa.Column('status', sa.String(length=30), nullable=False),
        sa.Column('rejection_reason', sa.Text(), nullable=True),
        sa.Column('trigger_price', sa.Numeric(), nullable=True),
        sa.Column('entry_price_target', sa.Numeric(), nullable=True),
        sa.Column('calculated_stop', sa.Numeric(), nullable=True),
        sa.Column('calculated_target', sa.Numeric(), nullable=True),
        sa.Column('quantity', sa.Integer(), nullable=True),
        sa.Column('risk_amount_usd', sa.Numeric(), nullable=True),
        sa.Column('is_paper', sa.Boolean(), nullable=False),
        sa.Column('broker_order_id', sa.String(length=50), nullable=True),
        sa.Column('broker_stop_id', sa.String(length=50), nullable=True),
        sa.Column('broker_target_id', sa.String(length=50), nullable=True),
        sa.Column('fill_price', sa.Numeric(), nullable=True),
        sa.Column('filled_at', sa.DateTime(), nullable=True),
        sa.Column('exit_price', sa.Numeric(), nullable=True),
        sa.Column('exited_at', sa.DateTime(), nullable=True),
        sa.Column('exit_reason', sa.String(length=30), nullable=True),
        sa.Column('trade_id', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['alert_rule_id'], ['alert_rules.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['scanner_event_id'], ['scanner_events.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['trade_id'], ['trades.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['trading_strategy_id'], ['trading_strategies.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('symbol', 'trading_strategy_id', 'event_date', name='uq_auto_trade_symbol_strategy_date'),
    )
    op.create_index(op.f('ix_auto_trade_orders_alert_rule_id'), 'auto_trade_orders', ['alert_rule_id'], unique=False)
    op.create_index(op.f('ix_auto_trade_orders_event_date'), 'auto_trade_orders', ['event_date'], unique=False)
    op.create_index(op.f('ix_auto_trade_orders_id'), 'auto_trade_orders', ['id'], unique=False)
    op.create_index(op.f('ix_auto_trade_orders_scanner_event_id'), 'auto_trade_orders', ['scanner_event_id'], unique=False)
    op.create_index(op.f('ix_auto_trade_orders_status'), 'auto_trade_orders', ['status'], unique=False)
    op.create_index(op.f('ix_auto_trade_orders_symbol'), 'auto_trade_orders', ['symbol'], unique=False)
    op.create_index(op.f('ix_auto_trade_orders_trade_id'), 'auto_trade_orders', ['trade_id'], unique=False)
    op.create_index(op.f('ix_auto_trade_orders_trading_strategy_id'), 'auto_trade_orders', ['trading_strategy_id'], unique=False)

    # ── Alter alert_rules ────────────────────────────────────────────────
    # Add auto_trade with server_default=false so existing rows are handled
    op.add_column('alert_rules', sa.Column('auto_trade', sa.Boolean(), nullable=False, server_default='false'))
    op.add_column('alert_rules', sa.Column('trading_strategy_id', sa.Integer(), nullable=True))
    op.create_index(op.f('ix_alert_rules_trading_strategy_id'), 'alert_rules', ['trading_strategy_id'], unique=False)
    op.create_foreign_key(
        'fk_alert_rules_trading_strategy_id',
        'alert_rules', 'trading_strategies',
        ['trading_strategy_id'], ['id'],
        ondelete='SET NULL',
    )


def downgrade() -> None:
    op.drop_constraint('fk_alert_rules_trading_strategy_id', 'alert_rules', type_='foreignkey')
    op.drop_index(op.f('ix_alert_rules_trading_strategy_id'), table_name='alert_rules')
    op.drop_column('alert_rules', 'trading_strategy_id')
    op.drop_column('alert_rules', 'auto_trade')

    op.drop_index(op.f('ix_auto_trade_orders_trading_strategy_id'), table_name='auto_trade_orders')
    op.drop_index(op.f('ix_auto_trade_orders_trade_id'), table_name='auto_trade_orders')
    op.drop_index(op.f('ix_auto_trade_orders_symbol'), table_name='auto_trade_orders')
    op.drop_index(op.f('ix_auto_trade_orders_status'), table_name='auto_trade_orders')
    op.drop_index(op.f('ix_auto_trade_orders_scanner_event_id'), table_name='auto_trade_orders')
    op.drop_index(op.f('ix_auto_trade_orders_id'), table_name='auto_trade_orders')
    op.drop_index(op.f('ix_auto_trade_orders_event_date'), table_name='auto_trade_orders')
    op.drop_index(op.f('ix_auto_trade_orders_alert_rule_id'), table_name='auto_trade_orders')
    op.drop_table('auto_trade_orders')

    op.drop_index(op.f('ix_trading_strategies_id'), table_name='trading_strategies')
    op.drop_table('trading_strategies')
