"""seed_liquidity_hunt_scanner_config

Revision ID: ed1162e42f12
Revises: 36969b8a8204
Create Date: 2026-04-26 13:56:45.027331

"""
import json
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'ed1162e42f12'
down_revision: Union[str, None] = '36969b8a8204'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()
    existing = conn.execute(
        sa.text("SELECT id FROM scanner_configs WHERE scanner_type = 'liquidity_hunt' LIMIT 1")
    ).fetchone()
    if existing:
        return

    conn.execute(
        sa.text("""
            INSERT INTO scanner_configs
                (name, description, scanner_type, parameters, criteria, is_active, run_frequency)
            VALUES
                (
                    'Liquidity Hunt (Evening)',
                    'Detects pre/post-market volume anomalies with a quiet regular session.',
                    'liquidity_hunt',
                    :params,
                    :criteria,
                    true,
                    'evening'
                )
        """),
        {
            "params": json.dumps({
                "volume_ratio_min": 4.0,
                "volume_pct_of_daily_min": 0.30,
                "spike_pct_min": 0.10,
                "regular_vol_ratio_max": 1.20,
                "regular_range_ratio_max": 1.50,
                "session_volume_floor": 50000
            }),
            "criteria": json.dumps({}),
        }
    )


def downgrade() -> None:
    op.execute(
        sa.text("DELETE FROM scanner_configs WHERE scanner_type = 'liquidity_hunt' AND name = 'Liquidity Hunt (Evening)'")
    )
