"""add_quality_gate_to_scanner_runs

Revision ID: 9f1e80e7a081
Revises: b45cf49c1c5a
Create Date: 2026-06-22 02:46:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

# revision identifiers, used by Alembic.
revision: str = "9f1e80e7a081"
down_revision: Union[str, None] = "b45cf49c1c5a"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "scanner_runs",
        sa.Column("quality_gate", JSONB, nullable=True),
    )


def downgrade() -> None:
    op.drop_column("scanner_runs", "quality_gate")
