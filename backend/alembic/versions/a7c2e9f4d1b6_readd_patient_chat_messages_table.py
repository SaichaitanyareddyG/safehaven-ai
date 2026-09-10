"""re-add patient chat messages table (v2, adds web_search_used)

Revision ID: a7c2e9f4d1b6
Revises: f3a1c9e7b2d4
Create Date: 2026-09-05 00:10:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = 'a7c2e9f4d1b6'
down_revision: Union[str, None] = 'f3a1c9e7b2d4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # This type name was already created and dropped once earlier in this
    # same migration history (261d5de4a45f, f3a1c9e7b2d4) — replaying the
    # full chain in one connection (as the test suite does from empty) makes
    # SQLAlchemy's own create_table-triggered enum auto-create unreliable for
    # a name it has already seen on that connection. Creating the type via
    # raw SQL and declaring the column with create_type=False sidesteps that
    # entirely — the standard pattern for a Postgres enum a migration chain
    # re-creates under a name it used before.
    op.execute("CREATE TYPE patient_chat_role AS ENUM ('PATIENT', 'ASSISTANT')")
    op.create_table('patient_chat_messages',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('patient_id', sa.UUID(), nullable=False),
    sa.Column('role', postgresql.ENUM('PATIENT', 'ASSISTANT', name='patient_chat_role', create_type=False), nullable=False),
    sa.Column('text', sa.Text(), nullable=False),
    sa.Column('emergency_flagged', sa.Boolean(), nullable=False),
    sa.Column('redirect_flagged', sa.Boolean(), nullable=False),
    sa.Column('web_search_used', sa.Boolean(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['patient_id'], ['patients.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_patient_chat_messages_created_at'), 'patient_chat_messages', ['created_at'], unique=False)
    op.create_index(op.f('ix_patient_chat_messages_patient_id'), 'patient_chat_messages', ['patient_id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_patient_chat_messages_patient_id'), table_name='patient_chat_messages')
    op.drop_index(op.f('ix_patient_chat_messages_created_at'), table_name='patient_chat_messages')
    op.drop_table('patient_chat_messages')
    op.execute("DROP TYPE patient_chat_role")
