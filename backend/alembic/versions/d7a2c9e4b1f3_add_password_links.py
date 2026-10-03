"""add password_links

Single-use invite and password-reset links (only their hash is stored).

Revision ID: d7a2c9e4b1f3
Revises: c4e8a1f7d2b6
Create Date: 2026-10-03 15:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = 'd7a2c9e4b1f3'
down_revision: Union[str, None] = 'c4e8a1f7d2b6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'password_links',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('user_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
        sa.Column('token_hash', sa.String(64), nullable=False, unique=True),
        sa.Column('purpose', sa.String(20), nullable=False),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('used_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index('ix_password_links_user_id', 'password_links', ['user_id'])


def downgrade() -> None:
    op.drop_index('ix_password_links_user_id', table_name='password_links')
    op.drop_table('password_links')
