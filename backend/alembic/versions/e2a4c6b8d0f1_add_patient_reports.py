"""add patient reports

Documents attached to a patient (lab, imaging, discharge summary, letters),
optionally shared to the patient app.

Revision ID: e2a4c6b8d0f1
Revises: d9f3b7e1a5c8
Create Date: 2026-10-22 18:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = 'e2a4c6b8d0f1'
down_revision: Union[str, None] = 'd9f3b7e1a5c8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

UUID = postgresql.UUID(as_uuid=True)


def upgrade() -> None:
    op.create_table(
        'patient_reports',
        sa.Column('id', UUID, primary_key=True),
        sa.Column('patient_id', UUID, sa.ForeignKey('patients.id', ondelete='CASCADE'), nullable=False),
        sa.Column('title', sa.String(200), nullable=False),
        sa.Column('category', sa.String(30), nullable=False),
        sa.Column('report_date', sa.Date(), nullable=True),
        sa.Column('content_type', sa.String(50), nullable=False),
        sa.Column('size', sa.Integer(), nullable=False),
        sa.Column('sha256', sa.String(64), nullable=False),
        sa.Column('data', sa.LargeBinary(), nullable=False),
        sa.Column('shared_with_patient', sa.Boolean(), nullable=False),
        sa.Column('uploaded_by', UUID, sa.ForeignKey('users.id'), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('removed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('removed_by', UUID, sa.ForeignKey('users.id'), nullable=True),
    )
    op.create_index('ix_patient_reports_patient_id', 'patient_reports', ['patient_id'])
    if op.get_bind().dialect.name == 'postgresql':
        op.execute('ALTER TABLE patient_reports ENABLE ROW LEVEL SECURITY')


def downgrade() -> None:
    op.drop_index('ix_patient_reports_patient_id', table_name='patient_reports')
    op.drop_table('patient_reports')
