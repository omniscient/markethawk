"""add_signal_quality_score

Revision ID: e8f40cc8abf7
Revises: 7ba47256a679
Create Date: 2026-05-21 20:52:37.262430

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e8f40cc8abf7'
down_revision: Union[str, None] = '7ba47256a679'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('scanner_events',
        sa.Column('signal_quality_score', sa.Float(), nullable=True))
    # Raw SQL for DESC NULLS LAST — Alembic's postgresql_ops is for operator classes only
    op.execute(
        "CREATE INDEX idx_scanner_events_score ON scanner_events (signal_quality_score DESC NULLS LAST)"
    )
    op.execute("""
        INSERT INTO system_config (key, value, updated_at)
        VALUES
            ('signal_ranker_enabled',  'true',         NOW()),
            ('signal_ranker_weights',  '{"volume_spike_ratio": 0.35, "gap_pct": 0.25, "relative_volume": 0.20, "volume_anomaly_score": 0.15, "float_rotation_pct": 0.05}', NOW()),
            ('signal_ranker_version',  '0.1.0-baseline', NOW())
        ON CONFLICT (key) DO NOTHING
    """)


def downgrade() -> None:
    op.execute("DELETE FROM system_config WHERE key IN ('signal_ranker_enabled', 'signal_ranker_weights', 'signal_ranker_version')")
    op.execute("DROP INDEX IF EXISTS idx_scanner_events_score")
    op.drop_column('scanner_events', 'signal_quality_score')
