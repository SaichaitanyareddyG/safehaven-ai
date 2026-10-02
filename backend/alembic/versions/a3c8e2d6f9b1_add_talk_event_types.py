"""add TALK_URGENT and TALK_REQUEST to sensor_event_type and safety_alert_type

Module 3 — "Talk to SafeHaven": the backend raises these from what a patient
says to the band's voice assistant. Downgrade is a no-op (PostgreSQL cannot
drop an enum value; an unused one is harmless).

Revision ID: a3c8e2d6f9b1
Revises: f1a6d3b8c4e5
Create Date: 2026-10-02 23:00:00.000000

"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = 'a3c8e2d6f9b1'
down_revision: Union[str, None] = 'f1a6d3b8c4e5'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    for value in ("TALK_URGENT", "TALK_REQUEST"):
        op.execute(f"ALTER TYPE sensor_event_type ADD VALUE IF NOT EXISTS '{value}'")
        op.execute(f"ALTER TYPE safety_alert_type ADD VALUE IF NOT EXISTS '{value}'")


def downgrade() -> None:
    pass
