"""drop patient chat messages table

Revision ID: f3a1c9e7b2d4
Revises: 9850830ad17a
Create Date: 2026-09-05 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'f3a1c9e7b2d4'
down_revision: Union[str, None] = '9850830ad17a'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

patient_chat_role_enum = sa.Enum('PATIENT', 'ASSISTANT', name='patient_chat_role')


def upgrade() -> None:
    op.drop_index(op.f('ix_patient_chat_messages_patient_id'), table_name='patient_chat_messages')
    op.drop_index(op.f('ix_patient_chat_messages_created_at'), table_name='patient_chat_messages')
    op.drop_table('patient_chat_messages')
    patient_chat_role_enum.drop(op.get_bind(), checkfirst=True)


def downgrade() -> None:
    patient_chat_role_enum.create(op.get_bind(), checkfirst=True)
    op.create_table('patient_chat_messages',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('patient_id', sa.UUID(), nullable=False),
    sa.Column('role', sa.Enum('PATIENT', 'ASSISTANT', name='patient_chat_role', create_type=False), nullable=False),
    sa.Column('text', sa.Text(), nullable=False),
    sa.Column('emergency_flagged', sa.Boolean(), nullable=False),
    sa.Column('redirect_flagged', sa.Boolean(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['patient_id'], ['patients.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_patient_chat_messages_created_at'), 'patient_chat_messages', ['created_at'], unique=False)
    op.create_index(op.f('ix_patient_chat_messages_patient_id'), 'patient_chat_messages', ['patient_id'], unique=False)
