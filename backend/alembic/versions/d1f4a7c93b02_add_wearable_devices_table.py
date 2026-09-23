"""add wearable_devices table

Module 3 Stage 1 — the device registry. Assignment, sensor events and alerts
arrive in later stages and get their own migrations, so each stage stays
independently reviewable and reversible.

Revision ID: d1f4a7c93b02
Revises: a3b6966e88d9
Create Date: 2026-09-23 12:10:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'd1f4a7c93b02'
down_revision: Union[str, None] = 'a3b6966e88d9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'wearable_devices',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('device_code', sa.String(length=32), nullable=False),
        sa.Column(
            'status',
            sa.Enum('ACTIVE', 'DISABLED', 'RETIRED', name='wearable_device_status'),
            nullable=False,
        ),
        # Credential and enrolment code are stored ONLY as SHA-256 hashes. A
        # database read alone can never be used to impersonate a device.
        sa.Column('credential_hash', sa.String(length=64), nullable=True),
        sa.Column('hardware_id', sa.String(length=64), nullable=True),
        sa.Column('enrollment_code_hash', sa.String(length=64), nullable=True),
        sa.Column('enrollment_expires_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('firmware_version', sa.String(length=32), nullable=True),
        sa.Column('battery_percent', sa.SmallInteger(), nullable=True),
        sa.Column('last_seen_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_by', sa.UUID(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['created_by'], ['users.id'], ),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_wearable_devices_device_code'), 'wearable_devices', ['device_code'], unique=True)
    op.create_index(op.f('ix_wearable_devices_credential_hash'), 'wearable_devices', ['credential_hash'], unique=True)
    op.create_index(
        op.f('ix_wearable_devices_enrollment_code_hash'), 'wearable_devices', ['enrollment_code_hash'], unique=True
    )
    # Drives offline detection, which is derived on read rather than swept by a
    # background job (there is no scheduler in this codebase).
    op.create_index(op.f('ix_wearable_devices_last_seen_at'), 'wearable_devices', ['last_seen_at'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_wearable_devices_last_seen_at'), table_name='wearable_devices')
    op.drop_index(op.f('ix_wearable_devices_enrollment_code_hash'), table_name='wearable_devices')
    op.drop_index(op.f('ix_wearable_devices_credential_hash'), table_name='wearable_devices')
    op.drop_index(op.f('ix_wearable_devices_device_code'), table_name='wearable_devices')
    op.drop_table('wearable_devices')
    # Native enums are not dropped by drop_table and would block a re-run.
    sa.Enum(name='wearable_device_status').drop(op.get_bind(), checkfirst=True)
