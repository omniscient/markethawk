"""add_scanner_run_async_columns

Revision ID: 6541905c6b14
Revises: ed1162e42f12
Create Date: 2026-04-27 12:31:14.657488

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "6541905c6b14"
down_revision: Union[str, None] = "ed1162e42f12"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "scanner_runs", sa.Column("scan_start_date", sa.Date(), nullable=True)
    )
    op.add_column("scanner_runs", sa.Column("scan_end_date", sa.Date(), nullable=True))
    op.add_column(
        "scanner_runs", sa.Column("celery_task_id", sa.String(length=64), nullable=True)
    )
    op.create_index(
        op.f("ix_scanner_runs_celery_task_id"),
        "scanner_runs",
        ["celery_task_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_scanner_runs_celery_task_id"), table_name="scanner_runs")
    op.drop_column("scanner_runs", "celery_task_id")
    op.drop_column("scanner_runs", "scan_end_date")
    op.drop_column("scanner_runs", "scan_start_date")
