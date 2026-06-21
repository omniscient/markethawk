"""add scanner_run data_degraded column

Revision ID: b45cf49c1c5a
Revises: a7f3c2e1b8d9
Create Date: 2026-06-21 16:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "b45cf49c1c5a"
down_revision: Union[str, None] = "a7f3c2e1b8d9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "scanner_runs",
        sa.Column("data_degraded", sa.Boolean(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("scanner_runs", "data_degraded")
