"""add caregiver accounts

A patient's app can have several logins: their own and caregivers'. Each
login has its own email, sign-in links and phones.

Revision ID: c8e2a6d0f4b7
Revises: b6d0f4a8c2e5
Create Date: 2026-10-22 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = 'c8e2a6d0f4b7'
down_revision: Union[str, None] = 'b6d0f4a8c2e5'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

UUID = postgresql.UUID(as_uuid=True)


def upgrade() -> None:
    op.add_column('patient_app_accounts', sa.Column('role', sa.String(20), nullable=False, server_default='PATIENT'))
    op.add_column('patient_app_accounts', sa.Column('email', sa.String(320), nullable=True))
    op.add_column('patient_app_accounts', sa.Column('display_name', sa.String(200), nullable=True))
    op.add_column('patient_app_accounts', sa.Column('relationship', sa.String(100), nullable=True))
    op.execute(
        "UPDATE patient_app_accounts a SET email = lower(p.email) FROM patients p WHERE p.id = a.patient_id"
    )
    op.drop_constraint('patient_app_accounts_patient_id_key', 'patient_app_accounts', type_='unique')
    op.create_index('ix_patient_app_accounts_patient_id', 'patient_app_accounts', ['patient_id'])
    op.create_index(
        'uq_app_account_patient_self', 'patient_app_accounts', ['patient_id'],
        unique=True, postgresql_where=sa.text("role = 'PATIENT'"),
    )
    op.create_index('ix_patient_app_accounts_email', 'patient_app_accounts', [sa.text('lower(email)')])

    op.add_column(
        'patient_sign_in_links',
        sa.Column('account_id', UUID, sa.ForeignKey('patient_app_accounts.id', ondelete='CASCADE'), nullable=True),
    )
    op.create_index('ix_patient_sign_in_links_account_id', 'patient_sign_in_links', ['account_id'])
    op.execute(
        "UPDATE patient_sign_in_links l SET account_id = a.id FROM patient_app_accounts a "
        "WHERE a.patient_id = l.patient_id AND a.role = 'PATIENT'"
    )

    op.add_column(
        'patient_push_subscriptions',
        sa.Column('account_id', UUID, sa.ForeignKey('patient_app_accounts.id', ondelete='CASCADE'), nullable=True),
    )
    op.create_index('ix_patient_push_subscriptions_account_id', 'patient_push_subscriptions', ['account_id'])
    op.execute(
        "UPDATE patient_push_subscriptions s SET account_id = a.id FROM patient_app_accounts a "
        "WHERE a.patient_id = s.patient_id AND a.role = 'PATIENT'"
    )

    op.add_column(
        'patient_dose_logs',
        sa.Column(
            'recorded_by_account_id', UUID, sa.ForeignKey('patient_app_accounts.id', ondelete='SET NULL'), nullable=True
        ),
    )


def downgrade() -> None:
    op.drop_column('patient_dose_logs', 'recorded_by_account_id')
    op.drop_index('ix_patient_push_subscriptions_account_id', table_name='patient_push_subscriptions')
    op.drop_column('patient_push_subscriptions', 'account_id')
    op.drop_index('ix_patient_sign_in_links_account_id', table_name='patient_sign_in_links')
    op.drop_column('patient_sign_in_links', 'account_id')
    op.drop_index('ix_patient_app_accounts_email', table_name='patient_app_accounts')
    op.drop_index('uq_app_account_patient_self', table_name='patient_app_accounts')
    op.drop_index('ix_patient_app_accounts_patient_id', table_name='patient_app_accounts')
    op.execute("DELETE FROM patient_app_accounts WHERE role <> 'PATIENT'")
    op.create_unique_constraint('patient_app_accounts_patient_id_key', 'patient_app_accounts', ['patient_id'])
    op.drop_column('patient_app_accounts', 'relationship')
    op.drop_column('patient_app_accounts', 'display_name')
    op.drop_column('patient_app_accounts', 'email')
    op.drop_column('patient_app_accounts', 'role')
