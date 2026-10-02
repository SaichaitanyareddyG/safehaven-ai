"""add HELP_REQUESTED to sensor_event_type and safety_alert_type

Module 3 — the band's help button (hold the front button for 2 s).

PostgreSQL cannot drop a value from an enum type, so downgrade is a
deliberate no-op: an unused enum value is harmless, and removing it would mean
rebuilding both types and every column that uses them.

Revision ID: d8e4b1f6a2c3
Revises: c7d3a9e5f1b2
Create Date: 2026-10-02 14:00:00.000000

"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = 'd8e4b1f6a2c3'
down_revision: Union[str, None] = 'c7d3a9e5f1b2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TYPE sensor_event_type ADD VALUE IF NOT EXISTS 'HELP_REQUESTED'")
    op.execute("ALTER TYPE safety_alert_type ADD VALUE IF NOT EXISTS 'HELP_REQUESTED'")


def downgrade() -> None:
    pass
