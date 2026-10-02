"""add device_pairing_requests

Module 3 — device-initiated pairing. A new band shows a six-digit code; a
clinician types it into the dashboard; the band collects a single-use
enrolment code and enrols through the existing /device-api/enroll path.

Revision ID: c7d3a9e5f1b2
Revises: b4e2f8a1c6d9
Create Date: 2026-10-02 13:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = 'c7d3a9e5f1b2'
down_revision: Union[str, None] = 'b4e2f8a1c6d9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'device_pairing_requests',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('pairing_code', sa.String(length=8), nullable=False),
        sa.Column('poll_token_hash', sa.String(length=64), nullable=False),
        sa.Column('hardware_id', sa.String(length=64), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('device_id', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('approved_by', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('enrollment_code', sa.String(length=32), nullable=True),
        sa.Column('collected_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['device_id'], ['wearable_devices.id']),
        sa.ForeignKeyConstraint(['approved_by'], ['users.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('poll_token_hash'),
    )
    op.create_index(
        'ix_device_pairing_requests_pairing_code', 'device_pairing_requests', ['pairing_code']
    )


def downgrade() -> None:
    op.drop_index('ix_device_pairing_requests_pairing_code', table_name='device_pairing_requests')
    op.drop_table('device_pairing_requests')
