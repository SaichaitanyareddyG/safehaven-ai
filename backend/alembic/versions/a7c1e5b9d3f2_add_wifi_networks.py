"""add wifi networks

Wi-Fi networks admins list for the bands; passwords encrypted at rest.

Revision ID: a7c1e5b9d3f2
Revises: f3b5d7a9c1e2
Create Date: 2026-10-25 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = 'a7c1e5b9d3f2'
down_revision: Union[str, None] = 'f3b5d7a9c1e2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'wifi_networks',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('label', sa.String(100), nullable=False),
        sa.Column('ssid', sa.String(32), nullable=False),
        sa.Column('security', sa.String(8), nullable=False),
        sa.Column('username', sa.String(64), nullable=True),
        sa.Column('identity', sa.String(64), nullable=True),
        sa.Column('password_encrypted', sa.Text(), nullable=False),
        sa.Column('created_by', postgresql.UUID(as_uuid=True), sa.ForeignKey('users.id'), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    )
    if op.get_bind().dialect.name == 'postgresql':
        op.execute('ALTER TABLE wifi_networks ENABLE ROW LEVEL SECURITY')


def downgrade() -> None:
    op.drop_table('wifi_networks')
