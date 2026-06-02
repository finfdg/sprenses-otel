"""add_correction_note_to_form_values

Revision ID: 445a2448f6dd
Revises: 7568af076be5
Create Date: 2026-03-04 18:54:16.803598
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '445a2448f6dd'
down_revision: Union[str, None] = '7568af076be5'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('quality_form_values',
        sa.Column('correction_note', sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column('quality_form_values', 'correction_note')
