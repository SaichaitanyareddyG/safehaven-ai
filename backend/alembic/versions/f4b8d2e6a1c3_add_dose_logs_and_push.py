"""add dose logs and push reminders

The patient's own Taken/Skipped per scheduled dose, Web Push subscriptions,
and a one-per-slot record of reminders sent.

Revision ID: f4b8d2e6a1c3
Revises: e3a7c1d9f5b2
Create Date: 2026-10-17 16:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = 'f4b8d2e6a1c3'
down_revision: Union[str, None] = 'e3a7c1d9f5b2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

UUID = postgresql.UUID(as_uuid=True)


def upgrade() -> None:
    op.create_table(
        'patient_dose_logs',
        sa.Column('id', UUID, primary_key=True),
        sa.Column('patient_id', UUID, sa.ForeignKey('patients.id', ondelete='CASCADE'), nullable=False),
        sa.Column('instruction_id', UUID, sa.ForeignKey('care_instructions.id', ondelete='CASCADE'), nullable=False),
        sa.Column('dose_date', sa.Date(), nullable=False),
        sa.Column('dose_time', sa.String(5), nullable=False),
        sa.Column('status', sa.String(10), nullable=False),
        sa.Column('recorded_at', sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint('instruction_id', 'dose_date', 'dose_time', name='uq_dose_log_slot'),
    )
    op.create_index('ix_patient_dose_logs_patient_id', 'patient_dose_logs', ['patient_id'])

    op.create_table(
        'patient_push_subscriptions',
        sa.Column('id', UUID, primary_key=True),
        sa.Column('patient_id', UUID, sa.ForeignKey('patients.id', ondelete='CASCADE'), nullable=False),
        sa.Column('endpoint', sa.Text(), nullable=False, unique=True),
        sa.Column('p256dh', sa.String(200), nullable=False),
        sa.Column('auth', sa.String(100), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('last_sent_at', sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index('ix_patient_push_subscriptions_patient_id', 'patient_push_subscriptions', ['patient_id'])

    op.create_table(
        'patient_dose_reminders_sent',
        sa.Column('id', UUID, primary_key=True),
        sa.Column('patient_id', UUID, sa.ForeignKey('patients.id', ondelete='CASCADE'), nullable=False),
        sa.Column('dose_date', sa.Date(), nullable=False),
        sa.Column('dose_time', sa.String(5), nullable=False),
        sa.Column('sent_at', sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint('patient_id', 'dose_date', 'dose_time', name='uq_dose_reminder_slot'),
    )

    if op.get_bind().dialect.name == 'postgresql':
        for table in ('patient_dose_logs', 'patient_push_subscriptions', 'patient_dose_reminders_sent'):
            op.execute(f'ALTER TABLE {table} ENABLE ROW LEVEL SECURITY')


def downgrade() -> None:
    op.drop_table('patient_dose_reminders_sent')
    op.drop_index('ix_patient_push_subscriptions_patient_id', table_name='patient_push_subscriptions')
    op.drop_table('patient_push_subscriptions')
    op.drop_index('ix_patient_dose_logs_patient_id', table_name='patient_dose_logs')
    op.drop_table('patient_dose_logs')
