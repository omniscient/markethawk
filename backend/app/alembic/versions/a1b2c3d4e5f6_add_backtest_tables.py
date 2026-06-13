"""add_backtest_tables

Revision ID: a1b2c3d4e5f6
Revises: fa2957d31876
Create Date: 2026-06-13 00:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "a1b2c3d4e5f6"
down_revision: Union[str, None] = "fa2957d31876"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "backtest_runs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("uuid", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("scanner_type", sa.String(length=50), nullable=False),
        sa.Column("strategy_id", sa.Integer(), nullable=False),
        sa.Column("universe_id", sa.Integer(), nullable=False),
        sa.Column("start_date", sa.Date(), nullable=False),
        sa.Column("end_date", sa.Date(), nullable=False),
        sa.Column("max_hold_sessions", sa.Integer(), nullable=False),
        sa.Column(
            "scanner_config_params",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("celery_task_id", sa.String(length=64), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("total_signals", sa.Integer(), nullable=True),
        sa.Column("total_trades", sa.Integer(), nullable=True),
        sa.Column("wins", sa.Integer(), nullable=True),
        sa.Column("losses", sa.Integer(), nullable=True),
        sa.Column("win_rate", sa.Float(), nullable=True),
        sa.Column("profit_factor", sa.Float(), nullable=True),
        sa.Column("expectancy_r", sa.Float(), nullable=True),
        sa.Column("max_drawdown_r", sa.Float(), nullable=True),
        sa.Column("avg_hold_sessions", sa.Float(), nullable=True),
        sa.Column("median_hold_sessions", sa.Float(), nullable=True),
        sa.Column("signals_skipped_no_data", sa.Integer(), nullable=True),
        sa.Column("trades_exited_on_data_end", sa.Integer(), nullable=True),
        sa.Column("universe_as_of", sa.String(length=10), nullable=True),
        sa.Column("bars_source", sa.String(length=50), nullable=True),
        sa.Column("degraded_input", sa.Boolean(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["strategy_id"], ["trading_strategies.id"]),
        sa.ForeignKeyConstraint(["universe_id"], ["stock_universes.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_backtest_runs_id"), "backtest_runs", ["id"], unique=False)
    op.create_index(
        op.f("ix_backtest_runs_uuid"), "backtest_runs", ["uuid"], unique=True
    )
    op.create_index(
        op.f("ix_backtest_runs_celery_task_id"),
        "backtest_runs",
        ["celery_task_id"],
        unique=False,
    )

    op.create_table(
        "backtest_trades",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("run_id", sa.Integer(), nullable=False),
        sa.Column("ticker", sa.String(length=10), nullable=False),
        sa.Column("signal_date", sa.Date(), nullable=False),
        sa.Column("source_event_id", sa.Integer(), nullable=True),
        sa.Column(
            "signal_indicators", postgresql.JSONB(astext_type=sa.Text()), nullable=True
        ),
        sa.Column("entry_date", sa.Date(), nullable=True),
        sa.Column("entry_price", sa.Numeric(), nullable=True),
        sa.Column("exit_date", sa.Date(), nullable=True),
        sa.Column("exit_price", sa.Numeric(), nullable=True),
        sa.Column("exit_reason", sa.String(length=30), nullable=True),
        sa.Column("hold_sessions", sa.Integer(), nullable=True),
        sa.Column("result_r", sa.Float(), nullable=True),
        sa.Column("stop_price", sa.Numeric(), nullable=True),
        sa.Column("target_price", sa.Numeric(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["run_id"], ["backtest_runs.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["source_event_id"], ["scanner_events.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_backtest_trades_id"), "backtest_trades", ["id"], unique=False
    )
    op.create_index(
        op.f("ix_backtest_trades_run_id"), "backtest_trades", ["run_id"], unique=False
    )
    op.create_index(
        op.f("ix_backtest_trades_ticker"), "backtest_trades", ["ticker"], unique=False
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_backtest_trades_ticker"), table_name="backtest_trades")
    op.drop_index(op.f("ix_backtest_trades_run_id"), table_name="backtest_trades")
    op.drop_index(op.f("ix_backtest_trades_id"), table_name="backtest_trades")
    op.drop_table("backtest_trades")
    op.drop_index(op.f("ix_backtest_runs_celery_task_id"), table_name="backtest_runs")
    op.drop_index(op.f("ix_backtest_runs_uuid"), table_name="backtest_runs")
    op.drop_index(op.f("ix_backtest_runs_id"), table_name="backtest_runs")
    op.drop_table("backtest_runs")
