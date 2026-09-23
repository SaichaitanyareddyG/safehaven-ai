"""add additional patient languages

Revision ID: 9999e713dbb8
Revises: 13e32389741c
Create Date: 2026-09-15 08:16:24.323271

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '9999e713dbb8'
down_revision: Union[str, None] = '13e32389741c'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# Title VI / CLAS language access — see patients.models.Language's docstring.
_NEW_LANGUAGES = (
    "SPANISH",
    "MANDARIN",
    "VIETNAMESE",
    "TAGALOG",
    "ARABIC",
    "KOREAN",
    "RUSSIAN",
    "FRENCH",
)


def upgrade() -> None:
    # Autogenerate never detects added enum VALUES (only added types/columns),
    # so this is written by hand. IF NOT EXISTS keeps it re-runnable against a
    # database that already has some of them.
    #
    # Safe inside Alembic's transaction on PostgreSQL 12+ (this project runs
    # 16): the restriction is that a newly added value cannot be USED in the
    # same transaction, and nothing here writes one.
    for language in _NEW_LANGUAGES:
        op.execute(f"ALTER TYPE patient_language ADD VALUE IF NOT EXISTS '{language}'")


def downgrade() -> None:
    # PostgreSQL has no DROP VALUE. Reversing this would mean recreating the
    # type and rewriting every column that uses it (patients.preferred_language
    # and patient_output_translations.language) — destructive, and pointless
    # for a purely additive change, so it is deliberately not attempted.
    pass
