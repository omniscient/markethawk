"""seed_trend_pullback_scanner_config

Insert the scanner_configs row for the trend_pullback daily scanner.
is_active=true so the scanner appears in the UI dropdown immediately.
criteria='[]'::json (not '{}') — matches the pattern from c7e2a9f4b1d3.
universe_id=1 (default universe, NOT NULL column).

Revision ID: f7e8d9c0b1a2
Revises: c7d8e9f0a1b2
Create Date: 2026-06-11

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "f7e8d9c0b1a2"
down_revision: Union[str, None] = "c7d8e9f0a1b2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    import json

    conn = op.get_bind()
    existing = conn.execute(
        sa.text(
            "SELECT id FROM scanner_configs WHERE scanner_type = 'trend_pullback' LIMIT 1"
        )
    ).fetchone()
    if existing:
        return

    conn.execute(
        sa.text("""
            INSERT INTO scanner_configs
                (name, description, scanner_type, parameters, criteria, is_active,
                 run_frequency, universe_id, outcome_config, data_requirements)
            VALUES
                (
                    'Trend Pullback (Evening)',
                    'Detects stocks in confirmed uptrends pulling back in an orderly way to '
                    'their rising 20-day SMA. RSI(5) < 40 confirms the reset.',
                    'trend_pullback',
                    :params,
                    '[]'::json,
                    true,
                    'evening',
                    1,
                    :outcome_config,
                    :data_requirements
                )
        """),
        {
            "params": json.dumps(
                {
                    "trend_sma_fast": 50,
                    "trend_sma_slow": 200,
                    "sma_rising_lookback": 20,
                    "max_pct_off_high": 15,
                    "pullback_sma": 20,
                    "pullback_sma_tolerance_pct": 1,
                    "min_days_above_sma": 5,
                    "pullback_min_pct": 3,
                    "pullback_max_pct": 12,
                    "rsi_period": 5,
                    "rsi_max": 40,
                    "min_dollar_vol": 5000000,
                    "min_price": 5.0,
                }
            ),
            "outcome_config": json.dumps(
                {
                    "intervals": ["1d", "2d", "5d", "10d"],
                    "follow_through_threshold_pct": 2.0,
                    "reference_price_source": "opening_price",
                    "extra_metrics": [],
                }
            ),
            "data_requirements": json.dumps(
                {
                    "timespan": "day",
                    "min_bars": 260,
                }
            ),
        },
    )


def downgrade() -> None:
    op.execute(
        sa.text(
            "DELETE FROM scanner_configs "
            "WHERE scanner_type = 'trend_pullback' AND name = 'Trend Pullback (Evening)'"
        )
    )
