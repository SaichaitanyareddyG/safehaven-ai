"""add qr_token to device_assignments

Module 3 Stage 10 — the band's QR code. Resolves the design question left open
by the Stage 2 correction (MODULE_3_IMPLEMENTATION_PLAN.md §19): the token is
stored in plaintext because the device must receive the raw value to draw it,
it is opaque and high-entropy, and it is nulled the moment an assignment ends.

Assignments that are already active get a token here, so a band in use today
shows its QR after the next heartbeat without being reassigned.

Revision ID: b4e2f8a1c6d9
Revises: a7d1e6b3f902
Create Date: 2026-10-02 12:00:00.000000

"""
import secrets
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b4e2f8a1c6d9'
down_revision: Union[str, None] = 'a7d1e6b3f902'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('device_assignments', sa.Column('qr_token', sa.String(length=32), nullable=True))
    op.create_unique_constraint('uq_device_assignments_qr_token', 'device_assignments', ['qr_token'])

    conn = op.get_bind()
    active = conn.execute(sa.text("SELECT id FROM device_assignments WHERE unassigned_at IS NULL")).fetchall()
    for (assignment_id,) in active:
        conn.execute(
            sa.text("UPDATE device_assignments SET qr_token = :t WHERE id = :id"),
            {"t": secrets.token_urlsafe(12), "id": assignment_id},
        )


def downgrade() -> None:
    op.drop_constraint('uq_device_assignments_qr_token', 'device_assignments', type_='unique')
    op.drop_column('device_assignments', 'qr_token')
