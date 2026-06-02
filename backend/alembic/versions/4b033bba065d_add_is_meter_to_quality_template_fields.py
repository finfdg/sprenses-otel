"""add is_meter to quality_template_fields

Revision ID: 4b033bba065d
Revises: 445a2448f6dd
Create Date: 2026-03-05 13:41:41.946837
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = '4b033bba065d'
down_revision: Union[str, None] = '445a2448f6dd'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'quality_template_fields',
        sa.Column('is_meter', sa.Boolean(), nullable=False, server_default=sa.text('false')),
    )


def downgrade() -> None:
    op.drop_column('quality_template_fields', 'is_meter')
