"""Add_ticker_fields

Revision ID: dd23e308d7c0
Revises:
Create Date: 2025-12-15 12:07:19.802834

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "dd23e308d7c0"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Several tables predate Alembic on production. Create them here for fresh DBs (CI).
    # All statements use IF NOT EXISTS so they are no-ops on existing production databases.

    op.execute("""
        CREATE TABLE IF NOT EXISTS ticker_references (
            ticker VARCHAR NOT NULL,
            name VARCHAR,
            market_cap FLOAT,
            outstanding_shares FLOAT,
            sector VARCHAR,
            industry VARCHAR,
            last_updated TIMESTAMP,
            description TEXT,
            primary_exchange VARCHAR,
            list_date VARCHAR,
            total_employees FLOAT,
            share_class_shares_outstanding FLOAT,
            weighted_shares_outstanding FLOAT,
            sic_code VARCHAR,
            sic_description VARCHAR,
            homepage_url VARCHAR,
            last_details_update TIMESTAMP,
            PRIMARY KEY (ticker)
        )
    """)

    op.execute("""
        CREATE TABLE IF NOT EXISTS stock_universes (
            id SERIAL PRIMARY KEY,
            uuid UUID DEFAULT gen_random_uuid() UNIQUE,
            name VARCHAR(100) NOT NULL,
            description TEXT,
            criteria JSONB NOT NULL DEFAULT '{}',
            created_at TIMESTAMP DEFAULT now(),
            updated_at TIMESTAMP DEFAULT now(),
            is_active BOOLEAN DEFAULT TRUE,
            created_by VARCHAR(100) DEFAULT 'system'
        )
    """)

    op.execute("""
        CREATE TABLE IF NOT EXISTS monitored_stocks (
            id SERIAL PRIMARY KEY,
            ticker VARCHAR(50) NOT NULL,
            company_name VARCHAR(1000),
            sector VARCHAR(255),
            industry VARCHAR(255),
            market_cap BIGINT,
            universe_id INTEGER REFERENCES stock_universes(id) ON DELETE CASCADE,
            added_date DATE NOT NULL DEFAULT CURRENT_DATE,
            last_scanned TIMESTAMP,
            scan_count INTEGER DEFAULT 0,
            is_active BOOLEAN DEFAULT TRUE,
            metadata JSONB DEFAULT '{}',
            created_at TIMESTAMP DEFAULT now(),
            updated_at TIMESTAMP DEFAULT now()
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS idx_monitored_stocks_ticker ON monitored_stocks (ticker)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_monitored_stocks_universe ON monitored_stocks (universe_id)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_monitored_stocks_active ON monitored_stocks (is_active)")

    op.execute("""
        CREATE TABLE IF NOT EXISTS scanner_configs (
            id SERIAL PRIMARY KEY,
            uuid UUID DEFAULT gen_random_uuid() UNIQUE,
            name VARCHAR(100) NOT NULL,
            description TEXT,
            scanner_type VARCHAR(50) NOT NULL DEFAULT 'volume',
            parameters JSONB NOT NULL DEFAULT '{}',
            criteria JSONB NOT NULL DEFAULT '{}',
            is_active BOOLEAN DEFAULT TRUE,
            run_frequency VARCHAR(20),
            last_run TIMESTAMP,
            next_run TIMESTAMP,
            created_by VARCHAR(100) DEFAULT 'system',
            created_at TIMESTAMP DEFAULT now(),
            updated_at TIMESTAMP DEFAULT now()
        )
    """)

    op.execute("""
        CREATE TABLE IF NOT EXISTS volume_events (
            id SERIAL PRIMARY KEY,
            uuid UUID DEFAULT gen_random_uuid() UNIQUE,
            ticker VARCHAR(10) NOT NULL,
            event_date DATE NOT NULL,
            event_type VARCHAR(50) NOT NULL,
            pre_market_volume BIGINT NOT NULL DEFAULT 0,
            regular_volume BIGINT,
            avg_volume_20d BIGINT NOT NULL DEFAULT 0,
            avg_volume_50d BIGINT,
            relative_volume NUMERIC NOT NULL DEFAULT 0,
            volume_spike_ratio NUMERIC NOT NULL DEFAULT 0,
            previous_close NUMERIC NOT NULL DEFAULT 0,
            pre_market_high NUMERIC,
            pre_market_low NUMERIC,
            opening_price NUMERIC,
            closing_price NUMERIC,
            price_change_pct NUMERIC,
            price_gap_pct NUMERIC,
            criteria_met JSONB NOT NULL DEFAULT '[]',
            news_count INTEGER DEFAULT 0,
            earnings_date DATE,
            market_cap_at_event BIGINT,
            raw_data JSONB DEFAULT '{}',
            created_at TIMESTAMP DEFAULT now(),
            updated_at TIMESTAMP DEFAULT now()
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS idx_volume_events_type ON volume_events (event_type)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_volume_events_ticker ON volume_events (ticker)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_volume_events_relative_vol ON volume_events (relative_volume)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_volume_events_date ON volume_events (event_date)")

    op.execute("""
        CREATE TABLE IF NOT EXISTS futures_aggregates (
            id SERIAL PRIMARY KEY,
            symbol VARCHAR(20) NOT NULL,
            contract_month VARCHAR(8) NOT NULL,
            exchange VARCHAR(20) NOT NULL,
            timestamp TIMESTAMP NOT NULL,
            timespan VARCHAR(20) NOT NULL DEFAULT 'day',
            multiplier INTEGER NOT NULL DEFAULT 1,
            open NUMERIC NOT NULL,
            high NUMERIC NOT NULL,
            low NUMERIC NOT NULL,
            close NUMERIC NOT NULL,
            volume BIGINT NOT NULL,
            vwap NUMERIC,
            transactions INTEGER,
            source VARCHAR(20) DEFAULT 'ibkr',
            created_at TIMESTAMP DEFAULT now()
        )
    """)

    op.execute("""
        CREATE TABLE IF NOT EXISTS trades (
            id SERIAL PRIMARY KEY,
            symbol VARCHAR(10) NOT NULL,
            status VARCHAR(20) DEFAULT 'open',
            side VARCHAR(10),
            open_date TIMESTAMP,
            close_date TIMESTAMP,
            quantity NUMERIC,
            avg_entry_price NUMERIC,
            avg_exit_price NUMERIC,
            gross_pnl NUMERIC,
            net_pnl NUMERIC,
            commissions NUMERIC DEFAULT 0,
            return_pct NUMERIC,
            notes TEXT,
            created_at TIMESTAMP DEFAULT now(),
            updated_at TIMESTAMP DEFAULT now()
        )
    """)

    op.execute("ALTER TABLE ticker_references ADD COLUMN IF NOT EXISTS active BOOLEAN")
    op.execute("ALTER TABLE ticker_references ADD COLUMN IF NOT EXISTS cik VARCHAR")
    op.execute("ALTER TABLE ticker_references ADD COLUMN IF NOT EXISTS composite_figi VARCHAR")
    op.execute("ALTER TABLE ticker_references ADD COLUMN IF NOT EXISTS market VARCHAR")
    op.execute("ALTER TABLE ticker_references ADD COLUMN IF NOT EXISTS type VARCHAR")

    # Sync description type: was TEXT in legacy DB, model declares String (VARCHAR).
    # Only alter if the column is still TEXT to avoid a no-op error on fresh DBs.
    op.execute("""
        DO $$
        BEGIN
            IF (
                SELECT data_type FROM information_schema.columns
                WHERE table_name = 'ticker_references' AND column_name = 'description'
            ) = 'text' THEN
                ALTER TABLE ticker_references
                    ALTER COLUMN description TYPE VARCHAR USING description::VARCHAR;
            END IF;
        END
        $$;
    """)


def downgrade() -> None:
    op.alter_column(
        "ticker_references",
        "description",
        existing_type=sa.String(),
        type_=sa.TEXT(),
        existing_nullable=True,
    )
    op.drop_column("ticker_references", "type")
    op.drop_column("ticker_references", "market")
    op.drop_column("ticker_references", "composite_figi")
    op.drop_column("ticker_references", "cik")
    op.drop_column("ticker_references", "active")
