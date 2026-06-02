"""add footer_text to quality_templates

Revision ID: 6aed1a1a66a1
Revises: h7i8j9k0l1m2
Create Date: 2026-03-04 16:11:40.058621
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = '6aed1a1a66a1'
down_revision: Union[str, None] = 'h7i8j9k0l1m2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('quality_templates', sa.Column('footer_text', sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column('quality_templates', 'footer_text')
