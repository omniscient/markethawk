"""Seed TimesFM system_config rows

Revision ID: b5e6f7a8b9c0
Revises: a4944daa848d
Create Date: 2026-05-13 10:00:00.000000

"""

from typing import Sequence, Union

from alembic import op

revision: str = "b5e6f7a8b9c0"
down_revision: Union[str, None] = "a4944daa848d"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_ROWS = [
    ("timesfm_enabled", "false"),
    ("timesfm_anomaly_threshold", "2.0"),
    ("timesfm_min_history_bars", "30"),
    ("timesfm_fallback_multiplier", "4.0"),
]


def upgrade() -> None:
    for key, value in _ROWS:
        op.execute(
            f"INSERT INTO system_config (key, value, updated_at) "
            f"VALUES ('{key}', '{value}', NOW()) "
            f"ON CONFLICT (key) DO NOTHING"
        )


def downgrade() -> None:
    for key, _ in _ROWS:
        op.execute(f"DELETE FROM system_config WHERE key = '{key}'")
