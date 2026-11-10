"""Patient app: account deactivated by the patient themselves

Revision ID: d2f4b8c6e0a1
Revises: c9e3a7b1d5f4
Create Date: 2026-11-10
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "d2f4b8c6e0a1"
down_revision: Union[str, None] = "c9e3a7b1d5f4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "patient_app_accounts",
        sa.Column("deactivated_by_patient", sa.Boolean(), nullable=False, server_default=sa.false()),
    )


def downgrade() -> None:
    op.drop_column("patient_app_accounts", "deactivated_by_patient")
