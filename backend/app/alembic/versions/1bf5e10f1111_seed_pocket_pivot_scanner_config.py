"""seed_pocket_pivot_scanner_config

Revision ID: 1bf5e10f1111
Revises: 0b4b1c3739b4
Create Date: 2026-06-02 01:10:34.594394

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = '1bf5e10f1111'
down_revision: Union[str, None] = '0b4b1c3739b4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    import json
    conn = op.get_bind()
    existing = conn.execute(
        sa.text(
            "SELECT id FROM scanner_configs WHERE scanner_type = 'pocket_pivot' LIMIT 1"
        )
    ).fetchone()
    if existing:
        return

    conn.execute(
        sa.text("""
            INSERT INTO scanner_configs
                (name, description, scanner_type, parameters, criteria, is_active, run_frequency)
            VALUES
                (
                    'Pocket Pivot (Evening)',
                    'Detects up-days where session volume exceeds the highest down-day volume in the prior 10 trading days (classic Morales/Kacher pocket pivot).',
                    'pocket_pivot',
                    :params,
                    :criteria,
                    false,
                    'evening'
                )
        """),
        {
            "params": json.dumps(
                {
                    "lookback_days": 10,
                    "min_lookback_days": 5,
                    "price_floor": 5.00,
                    "volume_floor": 100000,
                }
            ),
            "criteria": json.dumps({}),
        },
    )


def downgrade() -> None:
    op.execute(
        sa.text(
            "DELETE FROM scanner_configs WHERE scanner_type = 'pocket_pivot' AND name = 'Pocket Pivot (Evening)'"
        )
    )
