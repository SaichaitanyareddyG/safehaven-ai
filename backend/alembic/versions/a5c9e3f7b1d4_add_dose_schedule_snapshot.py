"""add dose schedule snapshot

The dose schedule as approved, saved on the instruction. Instructions
approved earlier have none and keep using the same rules on their facts.

Revision ID: a5c9e3f7b1d4
Revises: f4b8d2e6a1c3
Create Date: 2026-10-17 20:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = 'a5c9e3f7b1d4'
down_revision: Union[str, None] = 'f4b8d2e6a1c3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('care_instructions', sa.Column('dose_schedule', postgresql.JSONB(), nullable=True))


def downgrade() -> None:
    op.drop_column('care_instructions', 'dose_schedule')
