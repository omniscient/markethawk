"""add_scanner_run_id_to_scanner_events

Adds a nullable FK from scanner_events.scanner_run_id → scanner_runs.id so that
Guard 2.5 (strict quality gate) in AutoTradeExecutor can resolve the universe that
produced an event. Required by issue #496.

Revision ID: d4e5f6a7b8c9
Revises: c9d0e1f2a3b4
Create Date: 2026-06-25 00:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "d4e5f6a7b8c9"
down_revision: Union[str, None] = "c9d0e1f2a3b4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "scanner_events",
        sa.Column("scanner_run_id", sa.Integer(), nullable=True),
    )
    op.create_index(
        op.f("ix_scanner_events_scanner_run_id"),
        "scanner_events",
        ["scanner_run_id"],
        unique=False,
    )
    op.create_foreign_key(
        "fk_scanner_events_scanner_run_id",
        "scanner_events",
        "scanner_runs",
        ["scanner_run_id"],
        ["id"],
    )


def downgrade() -> None:
    op.drop_constraint(
        "fk_scanner_events_scanner_run_id", "scanner_events", type_="foreignkey"
    )
    op.drop_index(
        op.f("ix_scanner_events_scanner_run_id"), table_name="scanner_events"
    )
    op.drop_column("scanner_events", "scanner_run_id")
