"""add charging to wearable_devices

Module 3 — the band reports when it is on its charger: detection is paused
and its patient is not monitored, which the dashboard must show.

Revision ID: b5d9f3a7c1e2
Revises: a3c8e2d6f9b1
Create Date: 2026-10-03 10:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b5d9f3a7c1e2'
down_revision: Union[str, None] = 'a3c8e2d6f9b1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'wearable_devices',
        sa.Column('charging', sa.Boolean(), nullable=False, server_default=sa.text('false')),
    )


def downgrade() -> None:
    op.drop_column('wearable_devices', 'charging')
