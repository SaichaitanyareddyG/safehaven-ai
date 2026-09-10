"""add identification_method to administration_events

Revision ID: 159be66f1ce4
Revises: 349efef042b5
Create Date: 2026-09-06 00:53:07.304986

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '159be66f1ce4'
down_revision: Union[str, None] = '349efef042b5'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

identification_method_enum = sa.Enum('BARCODE', 'IMAGE', name='administration_identification_method')


def upgrade() -> None:
    # add_column (unlike create_table) does not auto-create the enum type —
    # see migration 9850830ad17a for the same issue hit earlier in this
    # project. Explicit create + create_type=False avoids it.
    identification_method_enum.create(op.get_bind(), checkfirst=True)
    op.add_column(
        'administration_events',
        sa.Column(
            'identification_method',
            sa.Enum('BARCODE', 'IMAGE', name='administration_identification_method', create_type=False),
            nullable=False,
            server_default='BARCODE',  # backfills existing rows — all prior events were barcode scans,
                                        # since image identification did not exist before this migration
        ),
    )
    # The column keeps its Python-level default going forward; the server
    # default was only needed for the backfill, so drop it to avoid masking
    # a future bug where the application forgets to set this explicitly.
    op.alter_column('administration_events', 'identification_method', server_default=None)


def downgrade() -> None:
    op.drop_column('administration_events', 'identification_method')
    identification_method_enum.drop(op.get_bind(), checkfirst=True)
