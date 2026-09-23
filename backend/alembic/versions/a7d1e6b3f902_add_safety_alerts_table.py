"""add safety_alerts table

Module 3 Stage 4 — the rules engine's output.

One row per EPISODE, not per event: events of the same type for the same
patient inside the dedupe window fold into the existing row and increment
event_count, so one fall cannot produce twenty alerts.

Revision ID: a7d1e6b3f902
Revises: f3c9d2a84e15
Create Date: 2026-09-23 14:20:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a7d1e6b3f902'
down_revision: Union[str, None] = 'f3c9d2a84e15'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'safety_alerts',
        sa.Column('id', sa.UUID(), nullable=False),
        # Denormalised onto the alert on purpose: an alert is a permanent record
        # of who was alerted about, and must stay answerable independently of
        # assignment history.
        sa.Column('patient_id', sa.UUID(), nullable=False),
        sa.Column('device_id', sa.UUID(), nullable=False),
        # NULL for DEVICE_OFFLINE, which is derived from the absence of data
        # rather than from an event.
        sa.Column('sensor_event_id', sa.UUID(), nullable=True),
        sa.Column(
            'alert_type',
            sa.Enum(
                'POSSIBLE_FALL',
                'ABNORMAL_MOVEMENT',
                'UNEXPECTED_MOBILITY',
                'DEVICE_LOW_BATTERY',
                'DEVICE_OFFLINE',
                name='safety_alert_type',
            ),
            nullable=False,
        ),
        # Operational priority — how soon someone should look. NOT a clinical
        # severity; nothing in Module 3 can judge medical acuity.
        sa.Column(
            'priority',
            sa.Enum('LOW', 'MEDIUM', 'HIGH', name='safety_alert_priority'),
            nullable=False,
        ),
        sa.Column(
            'status',
            sa.Enum('OPEN', 'ACKNOWLEDGED', 'RESOLVED', name='safety_alert_status'),
            nullable=False,
        ),
        sa.Column('event_count', sa.SmallInteger(), nullable=False),
        sa.Column('last_event_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('delayed', sa.Boolean(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('acknowledged_by', sa.UUID(), nullable=True),
        sa.Column('acknowledged_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('resolved_by', sa.UUID(), nullable=True),
        sa.Column('resolved_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['acknowledged_by'], ['users.id'], ),
        sa.ForeignKeyConstraint(['device_id'], ['wearable_devices.id'], ),
        sa.ForeignKeyConstraint(['patient_id'], ['patients.id'], ),
        sa.ForeignKeyConstraint(['resolved_by'], ['users.id'], ),
        sa.ForeignKeyConstraint(['sensor_event_id'], ['sensor_events.id'], ),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_safety_alerts_patient_id'), 'safety_alerts', ['patient_id'], unique=False)
    op.create_index(op.f('ix_safety_alerts_device_id'), 'safety_alerts', ['device_id'], unique=False)
    op.create_index(op.f('ix_safety_alerts_alert_type'), 'safety_alerts', ['alert_type'], unique=False)
    op.create_index(op.f('ix_safety_alerts_status'), 'safety_alerts', ['status'], unique=False)
    op.create_index(op.f('ix_safety_alerts_created_at'), 'safety_alerts', ['created_at'], unique=False)
    # The nurse dashboard's only hot query: live alerts, newest first.
    op.create_index(
        'ix_safety_alerts_status_created', 'safety_alerts', ['status', 'created_at'], unique=False
    )


def downgrade() -> None:
    op.drop_index('ix_safety_alerts_status_created', table_name='safety_alerts')
    op.drop_index(op.f('ix_safety_alerts_created_at'), table_name='safety_alerts')
    op.drop_index(op.f('ix_safety_alerts_status'), table_name='safety_alerts')
    op.drop_index(op.f('ix_safety_alerts_alert_type'), table_name='safety_alerts')
    op.drop_index(op.f('ix_safety_alerts_device_id'), table_name='safety_alerts')
    op.drop_index(op.f('ix_safety_alerts_patient_id'), table_name='safety_alerts')
    op.drop_table('safety_alerts')
    for enum_name in ('safety_alert_status', 'safety_alert_priority', 'safety_alert_type'):
        sa.Enum(name=enum_name).drop(op.get_bind(), checkfirst=True)
