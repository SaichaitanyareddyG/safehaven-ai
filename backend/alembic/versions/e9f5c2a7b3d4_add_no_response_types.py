"""add NO_RESPONSE to sensor_event_type and safety_alert_type

Module 3 — escalation when a possible fall goes unanswered on the band for
60 s. Downgrade is a no-op for the same reason as d8e4b1f6a2c3: PostgreSQL
cannot drop an enum value, and an unused one is harmless.

Revision ID: e9f5c2a7b3d4
Revises: d8e4b1f6a2c3
Create Date: 2026-10-02 15:00:00.000000

"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = 'e9f5c2a7b3d4'
down_revision: Union[str, None] = 'd8e4b1f6a2c3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TYPE sensor_event_type ADD VALUE IF NOT EXISTS 'NO_RESPONSE'")
    op.execute("ALTER TYPE safety_alert_type ADD VALUE IF NOT EXISTS 'NO_RESPONSE'")


def downgrade() -> None:
    pass
