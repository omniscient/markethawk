"""seed_sector_etfs_universe

Revision ID: b1c2d3e4f5a6
Revises: fa2957d31876
Create Date: 2026-05-14 12:00:00.000000
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "b1c2d3e4f5a6"
down_revision: Union[str, None] = "b5e6f7a8b9c0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()
    conn.execute(
        sa.text("""
        INSERT INTO stock_universes (id, name, description, criteria, is_active)
        VALUES (2, :name, :desc, CAST(:criteria AS json), true)
        ON CONFLICT (id) DO NOTHING
    """),
        {
            "name": "Sector ETFs",
            "desc": "11 SPDR sector ETFs for pre-market momentum context",
            "criteria": '{"type": "sector_etfs"}',
        },
    )

    conn.execute(
        sa.text("""
        INSERT INTO stock_universe_tickers (universe_id, ticker, asset_class, data_source)
        SELECT 2, v.ticker, 'stocks', 'massive'
        FROM (VALUES
            ('XLK'), ('XLF'), ('XLV'), ('XLY'), ('XLP'),
            ('XLE'), ('XLI'), ('XLB'), ('XLRE'), ('XLU'), ('XLC')
        ) AS v(ticker)
        WHERE NOT EXISTS (
            SELECT 1 FROM stock_universe_tickers sut
            WHERE sut.universe_id = 2 AND sut.ticker = v.ticker
        )
    """)
    )


def downgrade() -> None:
    conn = op.get_bind()
    conn.execute(sa.text("DELETE FROM stock_universe_tickers WHERE universe_id = 2"))
    conn.execute(sa.text("DELETE FROM stock_universes WHERE id = 2"))
