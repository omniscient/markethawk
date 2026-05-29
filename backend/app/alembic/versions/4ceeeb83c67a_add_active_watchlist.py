"""add_active_watchlist

Revision ID: 4ceeeb83c67a
Revises: f33989688da3
Create Date: 2026-04-13 13:01:44.929671

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "4ceeeb83c67a"
down_revision: Union[str, None] = "f33989688da3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "active_watchlist",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("symbol", sa.String(length=20), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("added_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_active_watchlist_id"), "active_watchlist", ["id"], unique=False
    )
    op.create_index(
        op.f("ix_active_watchlist_symbol"), "active_watchlist", ["symbol"], unique=True
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_active_watchlist_symbol"), table_name="active_watchlist")
    op.drop_index(op.f("ix_active_watchlist_id"), table_name="active_watchlist")
    op.drop_table("active_watchlist")


def _downgrade_stale_tables() -> None:
    # Kept for reference only — these tables exist in the DB from an older schema
    # but are not managed by this project's models. Do not run.
    op.create_table(
        "user_preferences",
        sa.Column("id", sa.INTEGER(), autoincrement=True, nullable=False),
        sa.Column(
            "user_id", sa.VARCHAR(length=100), autoincrement=False, nullable=False
        ),
        sa.Column(
            "dashboard_layout",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            autoincrement=False,
            nullable=True,
        ),
        sa.Column(
            "default_universe_id", sa.INTEGER(), autoincrement=False, nullable=True
        ),
        sa.Column(
            "alert_settings",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            autoincrement=False,
            nullable=True,
        ),
        sa.Column(
            "notification_settings",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            autoincrement=False,
            nullable=True,
        ),
        sa.Column(
            "theme",
            sa.VARCHAR(length=20),
            server_default=sa.text("'light'::character varying"),
            autoincrement=False,
            nullable=True,
        ),
        sa.Column(
            "language",
            sa.VARCHAR(length=10),
            server_default=sa.text("'en'::character varying"),
            autoincrement=False,
            nullable=True,
        ),
        sa.Column(
            "created_at",
            postgresql.TIMESTAMP(),
            server_default=sa.text("now()"),
            autoincrement=False,
            nullable=True,
        ),
        sa.Column(
            "updated_at",
            postgresql.TIMESTAMP(),
            server_default=sa.text("now()"),
            autoincrement=False,
            nullable=True,
        ),
        sa.ForeignKeyConstraint(
            ["default_universe_id"],
            ["stock_universes.id"],
            name=op.f("user_preferences_default_universe_id_fkey"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("user_preferences_pkey")),
    )
    op.create_table(
        "alert_configs",
        sa.Column("id", sa.INTEGER(), autoincrement=True, nullable=False),
        sa.Column(
            "uuid",
            sa.UUID(),
            server_default=sa.text("uuid_generate_v4()"),
            autoincrement=False,
            nullable=True,
        ),
        sa.Column("name", sa.VARCHAR(length=100), autoincrement=False, nullable=False),
        sa.Column("description", sa.TEXT(), autoincrement=False, nullable=True),
        sa.Column(
            "alert_type", sa.VARCHAR(length=50), autoincrement=False, nullable=False
        ),
        sa.Column(
            "conditions",
            postgresql.JSONB(astext_type=sa.Text()),
            autoincrement=False,
            nullable=False,
        ),
        sa.Column(
            "delivery_method",
            sa.VARCHAR(length=50),
            autoincrement=False,
            nullable=False,
        ),
        sa.Column(
            "delivery_config",
            postgresql.JSONB(astext_type=sa.Text()),
            autoincrement=False,
            nullable=False,
        ),
        sa.Column(
            "is_active",
            sa.BOOLEAN(),
            server_default=sa.text("true"),
            autoincrement=False,
            nullable=True,
        ),
        sa.Column(
            "created_at",
            postgresql.TIMESTAMP(),
            server_default=sa.text("now()"),
            autoincrement=False,
            nullable=True,
        ),
        sa.Column(
            "updated_at",
            postgresql.TIMESTAMP(),
            server_default=sa.text("now()"),
            autoincrement=False,
            nullable=True,
        ),
        sa.Column(
            "created_by",
            sa.VARCHAR(length=100),
            server_default=sa.text("'system'::character varying"),
            autoincrement=False,
            nullable=True,
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("alert_configs_pkey")),
        sa.UniqueConstraint(
            "uuid",
            name=op.f("alert_configs_uuid_key"),
            postgresql_include=[],
            postgresql_nulls_not_distinct=False,
        ),
    )
    op.create_table(
        "market_data_cache",
        sa.Column("id", sa.INTEGER(), autoincrement=True, nullable=False),
        sa.Column("ticker", sa.VARCHAR(length=10), autoincrement=False, nullable=False),
        sa.Column(
            "data_type", sa.VARCHAR(length=50), autoincrement=False, nullable=False
        ),
        sa.Column(
            "data",
            postgresql.JSONB(astext_type=sa.Text()),
            autoincrement=False,
            nullable=False,
        ),
        sa.Column(
            "data_hash", sa.VARCHAR(length=64), autoincrement=False, nullable=False
        ),
        sa.Column(
            "expires_at", postgresql.TIMESTAMP(), autoincrement=False, nullable=False
        ),
        sa.Column(
            "last_accessed",
            postgresql.TIMESTAMP(),
            server_default=sa.text("now()"),
            autoincrement=False,
            nullable=True,
        ),
        sa.Column(
            "access_count",
            sa.INTEGER(),
            server_default=sa.text("0"),
            autoincrement=False,
            nullable=True,
        ),
        sa.Column(
            "created_at",
            postgresql.TIMESTAMP(),
            server_default=sa.text("now()"),
            autoincrement=False,
            nullable=True,
        ),
        sa.Column(
            "updated_at",
            postgresql.TIMESTAMP(),
            server_default=sa.text("now()"),
            autoincrement=False,
            nullable=True,
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("market_data_cache_pkey")),
    )
    op.create_index(
        op.f("idx_market_data_cache_type"),
        "market_data_cache",
        ["data_type"],
        unique=False,
    )
    op.create_index(
        op.f("idx_market_data_cache_ticker"),
        "market_data_cache",
        ["ticker"],
        unique=False,
    )
    op.create_index(
        op.f("idx_market_data_cache_expires"),
        "market_data_cache",
        ["expires_at"],
        unique=False,
    )
    op.create_table(
        "alert_history",
        sa.Column("id", sa.INTEGER(), autoincrement=True, nullable=False),
        sa.Column(
            "uuid",
            sa.UUID(),
            server_default=sa.text("uuid_generate_v4()"),
            autoincrement=False,
            nullable=True,
        ),
        sa.Column("alert_config_id", sa.INTEGER(), autoincrement=False, nullable=True),
        sa.Column("volume_event_id", sa.INTEGER(), autoincrement=False, nullable=True),
        sa.Column(
            "alert_type", sa.VARCHAR(length=50), autoincrement=False, nullable=False
        ),
        sa.Column("ticker", sa.VARCHAR(length=10), autoincrement=False, nullable=False),
        sa.Column(
            "alert_date", postgresql.TIMESTAMP(), autoincrement=False, nullable=False
        ),
        sa.Column(
            "delivery_status",
            sa.VARCHAR(length=20),
            autoincrement=False,
            nullable=False,
        ),
        sa.Column(
            "delivery_attempts",
            sa.INTEGER(),
            server_default=sa.text("0"),
            autoincrement=False,
            nullable=True,
        ),
        sa.Column(
            "last_attempt", postgresql.TIMESTAMP(), autoincrement=False, nullable=True
        ),
        sa.Column(
            "response_data",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            autoincrement=False,
            nullable=True,
        ),
        sa.Column("error_message", sa.TEXT(), autoincrement=False, nullable=True),
        sa.Column(
            "created_at",
            postgresql.TIMESTAMP(),
            server_default=sa.text("now()"),
            autoincrement=False,
            nullable=True,
        ),
        sa.ForeignKeyConstraint(
            ["alert_config_id"],
            ["alert_configs.id"],
            name=op.f("alert_history_alert_config_id_fkey"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("alert_history_pkey")),
        sa.UniqueConstraint(
            "uuid",
            name=op.f("alert_history_uuid_key"),
            postgresql_include=[],
            postgresql_nulls_not_distinct=False,
        ),
    )
    op.create_table(
        "scanner_execution_log",
        sa.Column("id", sa.INTEGER(), autoincrement=True, nullable=False),
        sa.Column(
            "uuid",
            sa.UUID(),
            server_default=sa.text("uuid_generate_v4()"),
            autoincrement=False,
            nullable=True,
        ),
        sa.Column(
            "scanner_config_id", sa.INTEGER(), autoincrement=False, nullable=True
        ),
        sa.Column(
            "execution_type", sa.VARCHAR(length=20), autoincrement=False, nullable=False
        ),
        sa.Column(
            "start_time", postgresql.TIMESTAMP(), autoincrement=False, nullable=False
        ),
        sa.Column(
            "end_time", postgresql.TIMESTAMP(), autoincrement=False, nullable=True
        ),
        sa.Column(
            "stocks_scanned",
            sa.INTEGER(),
            server_default=sa.text("0"),
            autoincrement=False,
            nullable=True,
        ),
        sa.Column(
            "events_detected",
            sa.INTEGER(),
            server_default=sa.text("0"),
            autoincrement=False,
            nullable=True,
        ),
        sa.Column(
            "errors_encountered",
            sa.INTEGER(),
            server_default=sa.text("0"),
            autoincrement=False,
            nullable=True,
        ),
        sa.Column(
            "execution_duration_ms", sa.INTEGER(), autoincrement=False, nullable=True
        ),
        sa.Column("memory_usage_mb", sa.NUMERIC(), autoincrement=False, nullable=True),
        sa.Column("status", sa.VARCHAR(length=20), autoincrement=False, nullable=False),
        sa.Column("error_log", sa.TEXT(), autoincrement=False, nullable=True),
        sa.Column(
            "created_at",
            postgresql.TIMESTAMP(),
            server_default=sa.text("now()"),
            autoincrement=False,
            nullable=True,
        ),
        sa.ForeignKeyConstraint(
            ["scanner_config_id"],
            ["scanner_configs.id"],
            name=op.f("scanner_execution_log_scanner_config_id_fkey"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("scanner_execution_log_pkey")),
        sa.UniqueConstraint(
            "uuid",
            name=op.f("scanner_execution_log_uuid_key"),
            postgresql_include=[],
            postgresql_nulls_not_distinct=False,
        ),
    )
    op.create_index(
        op.f("idx_scanner_execution_log_status"),
        "scanner_execution_log",
        ["status"],
        unique=False,
    )
    op.create_index(
        op.f("idx_scanner_execution_log_start_time"),
        "scanner_execution_log",
        ["start_time"],
        unique=False,
    )
    op.drop_index(op.f("ix_active_watchlist_symbol"), table_name="active_watchlist")
    op.drop_index(op.f("ix_active_watchlist_id"), table_name="active_watchlist")
    op.drop_table("active_watchlist")
    # ### end Alembic commands ###
