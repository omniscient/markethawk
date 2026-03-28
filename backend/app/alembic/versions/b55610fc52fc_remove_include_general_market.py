"""Remove include_general_market from news_preferences

Revision ID: b55610fc52fc
Revises: a44499eb41eb
Create Date: 2026-03-23 19:08:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b55610fc52fc'
down_revision: Union[str, None] = 'a44499eb41eb'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_column('news_preferences', 'include_general_market')

def downgrade() -> None:
    op.add_column('news_preferences', sa.Column('include_general_market', sa.Boolean(), nullable=True))
