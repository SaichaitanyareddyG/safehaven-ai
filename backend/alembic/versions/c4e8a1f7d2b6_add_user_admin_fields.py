"""add admin fields to users

User management: an admin creates accounts with a one-time password, so a
user can be deactivated (never deleted — audit rows keep pointing at them),
must choose their own password at first sign-in, shows a last sign-in, and
sees the dashboard's guided tour once.

Revision ID: c4e8a1f7d2b6
Revises: b5d9f3a7c1e2
Create Date: 2026-10-03 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c4e8a1f7d2b6'
down_revision: Union[str, None] = 'b5d9f3a7c1e2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('users', sa.Column('is_active', sa.Boolean(), nullable=False, server_default=sa.text('true')))
    op.add_column(
        'users', sa.Column('must_change_password', sa.Boolean(), nullable=False, server_default=sa.text('false'))
    )
    op.add_column('users', sa.Column('last_login_at', sa.DateTime(timezone=True), nullable=True))
    # Existing accounts already know the dashboard: no tour for them.
    op.add_column('users', sa.Column('tour_completed_at', sa.DateTime(timezone=True), nullable=True))
    op.execute("UPDATE users SET tour_completed_at = now()")


def downgrade() -> None:
    op.drop_column('users', 'tour_completed_at')
    op.drop_column('users', 'last_login_at')
    op.drop_column('users', 'must_change_password')
    op.drop_column('users', 'is_active')
