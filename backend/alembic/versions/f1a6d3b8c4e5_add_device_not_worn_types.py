"""add DEVICE_NOT_WORN to sensor_event_type and safety_alert_type

Module 3 — the band reports when it has been lying still like an object
rather than on a wrist. Downgrade is a no-op (PostgreSQL cannot drop an enum
value; an unused one is harmless).

Revision ID: f1a6d3b8c4e5
Revises: e9f5c2a7b3d4
Create Date: 2026-10-02 19:00:00.000000

"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = 'f1a6d3b8c4e5'
down_revision: Union[str, None] = 'e9f5c2a7b3d4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TYPE sensor_event_type ADD VALUE IF NOT EXISTS 'DEVICE_NOT_WORN'")
    op.execute("ALTER TYPE safety_alert_type ADD VALUE IF NOT EXISTS 'DEVICE_NOT_WORN'")


def downgrade() -> None:
    pass
