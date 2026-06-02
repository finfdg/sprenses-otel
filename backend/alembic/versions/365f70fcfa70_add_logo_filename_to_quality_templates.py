"""add logo_filename to quality_templates

Revision ID: 365f70fcfa70
Revises: 6aed1a1a66a1
Create Date: 2026-03-04 16:31:00.449355
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = '365f70fcfa70'
down_revision: Union[str, None] = '6aed1a1a66a1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('quality_templates', sa.Column('logo_filename', sa.String(length=255), nullable=True))


def downgrade() -> None:
    op.drop_column('quality_templates', 'logo_filename')
