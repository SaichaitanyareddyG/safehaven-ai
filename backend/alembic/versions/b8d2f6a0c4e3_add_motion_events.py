"""add motion events

The fall detector's log from each band, for tuning on real motion.

Revision ID: b8d2f6a0c4e3
Revises: a7c1e5b9d3f2
Create Date: 2026-11-01 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = 'b8d2f6a0c4e3'
down_revision: Union[str, None] = 'a7c1e5b9d3f2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'motion_events',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('device_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('wearable_devices.id', ondelete='CASCADE'), nullable=False),
        sa.Column('occurred_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('firmware_version', sa.String(32), nullable=True),
        sa.Column('outcome', sa.String(8), nullable=False),
        sa.Column('freefall_ms', sa.Integer(), nullable=False),
        sa.Column('drop_cm', sa.Float(), nullable=False),
        sa.Column('peak_g', sa.Float(), nullable=False),
        sa.Column('turned_deg', sa.Float(), nullable=False),
        sa.Column('tilt_change_deg', sa.Float(), nullable=False),
        sa.Column('spin_dps', sa.Float(), nullable=False),
        sa.Column('axis', sa.String(1), nullable=False),
        sa.Column('still_ms', sa.Integer(), nullable=False),
        sa.Column('label', sa.String(16), nullable=True),
        sa.Column('received_at', sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index('ix_motion_events_device_id', 'motion_events', ['device_id'])
    if op.get_bind().dialect.name == 'postgresql':
        op.execute('ALTER TABLE motion_events ENABLE ROW LEVEL SECURITY')


def downgrade() -> None:
    op.drop_table('motion_events')
