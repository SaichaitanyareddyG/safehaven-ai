"""add appointments

Booked hospital appointments shown in the patient app, and a one-per-kind
record of reminders sent.

Revision ID: b6d0f4a8c2e5
Revises: a5c9e3f7b1d4
Create Date: 2026-10-22 09:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = 'b6d0f4a8c2e5'
down_revision: Union[str, None] = 'a5c9e3f7b1d4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

UUID = postgresql.UUID(as_uuid=True)


def upgrade() -> None:
    op.create_table(
        'appointments',
        sa.Column('id', UUID, primary_key=True),
        sa.Column('patient_id', UUID, sa.ForeignKey('patients.id', ondelete='CASCADE'), nullable=False),
        sa.Column('title', sa.String(200), nullable=False),
        sa.Column('starts_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('location', sa.String(300), nullable=True),
        sa.Column('notes', sa.Text(), nullable=True),
        sa.Column('status', sa.String(20), nullable=False),
        sa.Column('created_by', UUID, sa.ForeignKey('users.id'), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index('ix_appointments_patient_id', 'appointments', ['patient_id'])
    op.create_index('ix_appointments_starts_at', 'appointments', ['starts_at'])
    op.create_table(
        'appointment_reminders_sent',
        sa.Column('id', UUID, primary_key=True),
        sa.Column('appointment_id', UUID, sa.ForeignKey('appointments.id', ondelete='CASCADE'), nullable=False),
        sa.Column('kind', sa.String(20), nullable=False),
        sa.Column('sent_at', sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint('appointment_id', 'kind', name='uq_appointment_reminder'),
    )
    if op.get_bind().dialect.name == 'postgresql':
        op.execute('ALTER TABLE appointments ENABLE ROW LEVEL SECURITY')
        op.execute('ALTER TABLE appointment_reminders_sent ENABLE ROW LEVEL SECURITY')


def downgrade() -> None:
    op.drop_table('appointment_reminders_sent')
    op.drop_index('ix_appointments_starts_at', table_name='appointments')
    op.drop_index('ix_appointments_patient_id', table_name='appointments')
    op.drop_table('appointments')
