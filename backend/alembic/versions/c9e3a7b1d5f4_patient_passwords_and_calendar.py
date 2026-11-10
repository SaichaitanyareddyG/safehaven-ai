"""Patient app: passwords, reminder prompt, calendar feed

Revision ID: c9e3a7b1d5f4
Revises: b8d2f6a0c4e3
Create Date: 2026-11-09
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "c9e3a7b1d5f4"
down_revision: Union[str, None] = "b8d2f6a0c4e3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("patient_app_accounts", sa.Column("password_hash", sa.String(100), nullable=True))
    op.add_column("patient_app_accounts", sa.Column("password_set_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("patient_app_accounts", sa.Column("reminders_prompted_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("patient_app_accounts", sa.Column("calendar_token", sa.String(64), nullable=True))
    op.create_index(
        "ux_patient_app_accounts_calendar_token", "patient_app_accounts", ["calendar_token"], unique=True
    )
    # Access no longer ends at a date after discharge (2026-11-09): lift any
    # end already set, so nobody is locked out by the old rule.
    op.execute("UPDATE patient_app_accounts SET access_expires_at = NULL")


def downgrade() -> None:
    op.drop_index("ux_patient_app_accounts_calendar_token", table_name="patient_app_accounts")
    op.drop_column("patient_app_accounts", "calendar_token")
    op.drop_column("patient_app_accounts", "reminders_prompted_at")
    op.drop_column("patient_app_accounts", "password_set_at")
    op.drop_column("patient_app_accounts", "password_hash")
