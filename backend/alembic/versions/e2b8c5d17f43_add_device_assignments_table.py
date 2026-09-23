"""add device_assignments table

Module 3 Stage 2 — patient assignment and monitoring profiles.

The two partial unique indexes are the interesting part: they enforce "at most
one ACTIVE assignment per device" and "at most one ACTIVE patient monitor" in
the database, so two concurrent assignment requests cannot both succeed. The
service also checks in Python, but that check alone loses a race.

Revision ID: e2b8c5d17f43
Revises: d1f4a7c93b02
Create Date: 2026-09-23 12:55:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e2b8c5d17f43'
down_revision: Union[str, None] = 'd1f4a7c93b02'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'device_assignments',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('device_id', sa.UUID(), nullable=False),
        sa.Column('patient_id', sa.UUID(), nullable=False),
        # Context only — never used to decide whether to monitor.
        sa.Column('encounter_id', sa.UUID(), nullable=True),
        sa.Column(
            'monitoring_profile',
            sa.Enum('STANDARD', 'FALL_RISK', 'RESTRICTED_MOBILITY', name='device_monitoring_profile'),
            nullable=False,
        ),
        sa.Column('assigned_by', sa.UUID(), nullable=False),
        sa.Column('assigned_at', sa.DateTime(timezone=True), nullable=False),
        # unassigned_by is NULL when the discharge cascade ended it: there is no
        # clinician to attribute an automatic action to.
        sa.Column('unassigned_by', sa.UUID(), nullable=True),
        sa.Column('unassigned_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['assigned_by'], ['users.id'], ),
        sa.ForeignKeyConstraint(['device_id'], ['wearable_devices.id'], ),
        sa.ForeignKeyConstraint(['encounter_id'], ['encounters.id'], ),
        sa.ForeignKeyConstraint(['patient_id'], ['patients.id'], ),
        sa.ForeignKeyConstraint(['unassigned_by'], ['users.id'], ),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_device_assignments_device_id'), 'device_assignments', ['device_id'], unique=False)
    op.create_index(op.f('ix_device_assignments_patient_id'), 'device_assignments', ['patient_id'], unique=False)

    # "Active" is derived from unassigned_at IS NULL — there is no stored
    # boolean to disagree with it. These partial indexes are what make that
    # derivation safe under concurrency.
    op.create_index(
        'ux_device_assignments_active_device',
        'device_assignments',
        ['device_id'],
        unique=True,
        postgresql_where=sa.text('unassigned_at IS NULL'),
    )
    op.create_index(
        'ux_device_assignments_active_patient',
        'device_assignments',
        ['patient_id'],
        unique=True,
        postgresql_where=sa.text('unassigned_at IS NULL'),
    )


def downgrade() -> None:
    op.drop_index('ux_device_assignments_active_patient', table_name='device_assignments')
    op.drop_index('ux_device_assignments_active_device', table_name='device_assignments')
    op.drop_index(op.f('ix_device_assignments_patient_id'), table_name='device_assignments')
    op.drop_index(op.f('ix_device_assignments_device_id'), table_name='device_assignments')
    op.drop_table('device_assignments')
    sa.Enum(name='device_monitoring_profile').drop(op.get_bind(), checkfirst=True)
