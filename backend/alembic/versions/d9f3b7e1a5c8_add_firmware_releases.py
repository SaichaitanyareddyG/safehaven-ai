"""add firmware releases

Band firmware builds offered over Wi-Fi to bands on their charger.

Revision ID: d9f3b7e1a5c8
Revises: c8e2a6d0f4b7
Create Date: 2026-10-22 15:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = 'd9f3b7e1a5c8'
down_revision: Union[str, None] = 'c8e2a6d0f4b7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'firmware_releases',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('version', sa.String(64), nullable=False, unique=True),
        sa.Column('size', sa.Integer(), nullable=False),
        sa.Column('sha256', sa.String(64), nullable=False),
        sa.Column('image', sa.LargeBinary(), nullable=False),
        sa.Column('notes', sa.Text(), nullable=True),
        sa.Column('is_current', sa.Boolean(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    )
    if op.get_bind().dialect.name == 'postgresql':
        op.execute('ALTER TABLE firmware_releases ENABLE ROW LEVEL SECURITY')


def downgrade() -> None:
    op.drop_table('firmware_releases')
