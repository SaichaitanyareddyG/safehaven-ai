"""add device update request

Staff "Update now": a band may install new firmware off its charger.

Revision ID: f3b5d7a9c1e2
Revises: e2a4c6b8d0f1
Create Date: 2026-10-22 20:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'f3b5d7a9c1e2'
down_revision: Union[str, None] = 'e2a4c6b8d0f1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('wearable_devices', sa.Column('update_requested_at', sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column('wearable_devices', 'update_requested_at')
