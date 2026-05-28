"""seed_outcome_config_and_data_requirements

Revision ID: e9bd09ec24b0
Revises: 6541905c6b14
Create Date: 2026-04-30 12:00:00.000000

"""

import json
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "e9bd09ec24b0"
down_revision: Union[str, None] = "5011ed2c15c7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


OUTCOME_CONFIG_DEFAULT = {
    "intervals": ["1h", "4h", "eod", "1d", "2d", "5d"],
    "follow_through_threshold_pct": 2.0,
    "reference_price_source": "opening_price",
    "extra_metrics": [],
}

OUTCOME_CONFIG_GAP = {
    "intervals": ["1h", "4h", "eod", "1d", "2d", "5d"],
    "follow_through_threshold_pct": 2.0,
    "reference_price_source": "opening_price",
    "extra_metrics": ["gap_filled"],
}

DATA_REQS_DEFAULT = {
    "timespans": [
        {"timespan": "minute", "multiplier": 1, "lookback_days": 10},
        {"timespan": "day", "multiplier": 1, "lookback_days": 90},
    ]
}


def upgrade() -> None:
    conn = op.get_bind()
    conn.execute(
        sa.text("""
        UPDATE scanner_configs
        SET outcome_config = :oc, data_requirements = :dr
        WHERE scanner_type IN ('pre_market_volume', 'pre_market_volume_spike')
          AND outcome_config IS NULL
    """),
        {"oc": json.dumps(OUTCOME_CONFIG_GAP), "dr": json.dumps(DATA_REQS_DEFAULT)},
    )

    conn.execute(
        sa.text("""
        UPDATE scanner_configs
        SET outcome_config = :oc, data_requirements = :dr
        WHERE scanner_type = 'liquidity_hunt'
          AND outcome_config IS NULL
    """),
        {"oc": json.dumps(OUTCOME_CONFIG_DEFAULT), "dr": json.dumps(DATA_REQS_DEFAULT)},
    )

    conn.execute(
        sa.text("""
        UPDATE scanner_configs
        SET outcome_config = :oc, data_requirements = :dr
        WHERE scanner_type = 'oversold_bounce'
          AND outcome_config IS NULL
    """),
        {"oc": json.dumps(OUTCOME_CONFIG_DEFAULT), "dr": json.dumps(DATA_REQS_DEFAULT)},
    )


def downgrade() -> None:
    conn = op.get_bind()
    conn.execute(
        sa.text("""
        UPDATE scanner_configs
        SET outcome_config = NULL, data_requirements = NULL
        WHERE scanner_type IN ('pre_market_volume', 'pre_market_volume_spike', 'liquidity_hunt', 'oversold_bounce')
    """)
    )
