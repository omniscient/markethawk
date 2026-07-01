"""add_replay_engine_tables

Revision ID: f1a2b3c4d5e6
Revises: d4e5f6a7b8c9
Create Date: 2026-07-01 00:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "f1a2b3c4d5e6"
down_revision: Union[str, None] = "d4e5f6a7b8c9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "replay_runs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("uuid", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("celery_task_id", sa.String(length=64), nullable=True),
        sa.Column("scanner_type", sa.String(length=50), nullable=False),
        sa.Column(
            "scanner_config_snapshot",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column("trading_strategy_id", sa.Integer(), nullable=True),
        sa.Column(
            "strategy_snapshot",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
        sa.Column("universe_id", sa.Integer(), nullable=False),
        sa.Column(
            "universe_snapshot",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column("start_date", sa.Date(), nullable=False),
        sa.Column("end_date", sa.Date(), nullable=False),
        sa.Column("max_hold_days", sa.Integer(), nullable=False),
        sa.Column("exit_fidelity", sa.String(length=20), nullable=False),
        sa.Column("benchmark_symbol", sa.String(length=10), nullable=True),
        sa.Column("data_hash", sa.String(length=64), nullable=True),
        sa.Column("metrics", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("skipped_count", sa.Integer(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("signal_source", sa.String(length=20), nullable=True),
        sa.Column("total_trades", sa.Integer(), nullable=True),
        sa.Column("hit_rate", sa.Float(), nullable=True),
        sa.Column("expectancy_r", sa.Float(), nullable=True),
        sa.Column("profit_factor", sa.Float(), nullable=True),
        sa.Column("max_drawdown_r", sa.Float(), nullable=True),
        sa.Column("avg_bars_held", sa.Float(), nullable=True),
        sa.Column("median_bars_held", sa.Float(), nullable=True),
        sa.Column("avg_mfe_pct", sa.Float(), nullable=True),
        sa.Column("avg_mae_pct", sa.Float(), nullable=True),
        sa.Column("mfe_mae_ratio", sa.Float(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["trading_strategy_id"], ["trading_strategies.id"]),
        sa.ForeignKeyConstraint(["universe_id"], ["stock_universes.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_replay_runs_id"), "replay_runs", ["id"], unique=False)
    op.create_index(
        op.f("ix_replay_runs_uuid"), "replay_runs", ["uuid"], unique=True
    )
    op.create_index(
        op.f("ix_replay_runs_celery_task_id"),
        "replay_runs",
        ["celery_task_id"],
        unique=False,
    )

    op.create_table(
        "replay_trades",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("replay_run_id", sa.Integer(), nullable=False),
        sa.Column("scanner_event_id", sa.Integer(), nullable=True),
        sa.Column("ticker", sa.String(length=10), nullable=False),
        sa.Column("signal_date", sa.Date(), nullable=False),
        sa.Column("entry_date", sa.Date(), nullable=True),
        sa.Column("entry_price", sa.Numeric(), nullable=True),
        sa.Column("direction", sa.String(length=10), nullable=True),
        sa.Column("stop_price", sa.Numeric(), nullable=True),
        sa.Column("target_price", sa.Numeric(), nullable=True),
        sa.Column("exit_date", sa.Date(), nullable=True),
        sa.Column("exit_price", sa.Numeric(), nullable=True),
        sa.Column("exit_reason", sa.String(length=30), nullable=True),
        sa.Column("return_pct", sa.Numeric(), nullable=True),
        sa.Column("return_r", sa.Numeric(), nullable=True),
        sa.Column("mfe_pct", sa.Numeric(), nullable=True),
        sa.Column("mae_pct", sa.Numeric(), nullable=True),
        sa.Column("bars_held", sa.Integer(), nullable=True),
        sa.Column("regime_trend", sa.String(length=20), nullable=True),
        sa.Column("regime_vol", sa.String(length=20), nullable=True),
        sa.Column("fill_source", sa.String(length=20), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(
            ["replay_run_id"], ["replay_runs.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["scanner_event_id"], ["scanner_events.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_replay_trades_id"), "replay_trades", ["id"], unique=False
    )
    op.create_index(
        op.f("ix_replay_trades_replay_run_id"),
        "replay_trades",
        ["replay_run_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_replay_trades_ticker"), "replay_trades", ["ticker"], unique=False
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_replay_trades_ticker"), table_name="replay_trades")
    op.drop_index(
        op.f("ix_replay_trades_replay_run_id"), table_name="replay_trades"
    )
    op.drop_index(op.f("ix_replay_trades_id"), table_name="replay_trades")
    op.drop_table("replay_trades")
    op.drop_index(op.f("ix_replay_runs_celery_task_id"), table_name="replay_runs")
    op.drop_index(op.f("ix_replay_runs_uuid"), table_name="replay_runs")
    op.drop_index(op.f("ix_replay_runs_id"), table_name="replay_runs")
    op.drop_table("replay_runs")
