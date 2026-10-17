"""add patient app

Patient email, phone and app consent; the patient app account and its
single-use sign-in links (only their hash is stored).

Revision ID: e3a7c1d9f5b2
Revises: d7a2c9e4b1f3
Create Date: 2026-10-17 10:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = 'e3a7c1d9f5b2'
down_revision: Union[str, None] = 'd7a2c9e4b1f3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('patients', sa.Column('email', sa.String(320), nullable=True))
    op.add_column('patients', sa.Column('phone', sa.String(40), nullable=True))
    op.add_column('patients', sa.Column('app_consent_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column(
        'patients',
        sa.Column('app_consent_by', postgresql.UUID(as_uuid=True), sa.ForeignKey('users.id'), nullable=True),
    )
    op.create_index('ix_patients_email', 'patients', ['email'])

    op.create_table(
        'patient_app_accounts',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            'patient_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('patients.id', ondelete='CASCADE'),
            nullable=False, unique=True,
        ),
        sa.Column('status', sa.String(20), nullable=False),
        sa.Column('invited_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('invited_by', postgresql.UUID(as_uuid=True), sa.ForeignKey('users.id'), nullable=True),
        sa.Column('activated_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('last_sign_in_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('revoked_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('access_expires_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('session_version', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    )

    op.create_table(
        'patient_sign_in_links',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            'patient_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('patients.id', ondelete='CASCADE'),
            nullable=False,
        ),
        sa.Column('token_hash', sa.String(64), nullable=False, unique=True),
        sa.Column('purpose', sa.String(20), nullable=False),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('used_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index('ix_patient_sign_in_links_patient_id', 'patient_sign_in_links', ['patient_id'])

    # Same posture as every other table on the hosted database: RLS on, no
    # policies, so only the backend's own role (which bypasses RLS) reads them.
    if op.get_bind().dialect.name == 'postgresql':
        op.execute('ALTER TABLE patient_app_accounts ENABLE ROW LEVEL SECURITY')
        op.execute('ALTER TABLE patient_sign_in_links ENABLE ROW LEVEL SECURITY')


def downgrade() -> None:
    op.drop_index('ix_patient_sign_in_links_patient_id', table_name='patient_sign_in_links')
    op.drop_table('patient_sign_in_links')
    op.drop_table('patient_app_accounts')
    op.drop_index('ix_patients_email', table_name='patients')
    op.drop_column('patients', 'app_consent_by')
    op.drop_column('patients', 'app_consent_at')
    op.drop_column('patients', 'phone')
    op.drop_column('patients', 'email')
