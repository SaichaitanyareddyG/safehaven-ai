"""add sensor_events table

Module 3 Stage 3 — event ingestion.

The unique constraint on (device_id, device_event_id) is the idempotency
guarantee: retries and offline-queue drains resend events freely, and this is
what makes that safe rather than relying on callers being careful.

Revision ID: f3c9d2a84e15
Revises: e2b8c5d17f43
Create Date: 2026-09-23 13:40:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = 'f3c9d2a84e15'
down_revision: Union[str, None] = 'e2b8c5d17f43'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'sensor_events',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('device_id', sa.UUID(), nullable=False),
        # NOT NULL: an event that cannot be attributed to a patient is not
        # stored at all (the API answers 202 and discards it).
        sa.Column('assignment_id', sa.UUID(), nullable=False),
        sa.Column('device_event_id', sa.String(length=64), nullable=False),
        sa.Column(
            'event_type',
            sa.Enum(
                'POSSIBLE_FALL',
                'ABNORMAL_MOVEMENT',
                'UNEXPECTED_MOBILITY',
                'DEVICE_LOW_BATTERY',
                name='sensor_event_type',
            ),
            nullable=False,
        ),
        # Both timestamps, always: they differ whenever an event was queued
        # through a network outage, and a nurse needs to see which is which.
        sa.Column('occurred_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('received_at', sa.DateTime(timezone=True), nullable=False),
        # Motion measurements only — enforced by a strict pydantic schema with
        # extra fields forbidden, so a device cannot smuggle PHI in here.
        sa.Column('metrics', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('delayed', sa.Boolean(), nullable=False),
        sa.ForeignKeyConstraint(['assignment_id'], ['device_assignments.id'], ),
        sa.ForeignKeyConstraint(['device_id'], ['wearable_devices.id'], ),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('device_id', 'device_event_id', name='ux_sensor_events_device_event'),
    )
    op.create_index(op.f('ix_sensor_events_device_id'), 'sensor_events', ['device_id'], unique=False)
    op.create_index(
        op.f('ix_sensor_events_assignment_id'), 'sensor_events', ['assignment_id'], unique=False
    )
    op.create_index(op.f('ix_sensor_events_event_type'), 'sensor_events', ['event_type'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_sensor_events_event_type'), table_name='sensor_events')
    op.drop_index(op.f('ix_sensor_events_assignment_id'), table_name='sensor_events')
    op.drop_index(op.f('ix_sensor_events_device_id'), table_name='sensor_events')
    op.drop_table('sensor_events')
    sa.Enum(name='sensor_event_type').drop(op.get_bind(), checkfirst=True)
