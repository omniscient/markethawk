"""add_failed_tickers_to_scanner_runs

Revision ID: c1d2e3f4a5b6
Revises: b3e8f2a1c9d7, e8f40cc8abf7
Create Date: 2026-05-24 01:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "c1d2e3f4a5b6"
down_revision: Union[str, Sequence[str]] = "83cdd681f14c"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "scanner_runs",
        sa.Column(
            "failed_tickers", postgresql.JSONB(astext_type=sa.Text()), nullable=True
        ),
    )


def downgrade() -> None:
    op.drop_column("scanner_runs", "failed_tickers")
