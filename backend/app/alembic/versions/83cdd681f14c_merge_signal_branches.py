"""merge_signal_branches

Revision ID: 83cdd681f14c
Revises: b3e8f2a1c9d7, e8f40cc8abf7
Create Date: 2026-05-23 00:00:00.000000

"""

from typing import Sequence, Union

# revision identifiers, used by Alembic.
revision: str = "83cdd681f14c"
down_revision: Union[str, Sequence[str]] = ("b3e8f2a1c9d7", "e8f40cc8abf7")
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
