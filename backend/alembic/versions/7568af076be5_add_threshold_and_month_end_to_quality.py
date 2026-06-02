"""add_threshold_and_month_end_to_quality

Revision ID: 7568af076be5
Revises: 365f70fcfa70
Create Date: 2026-03-04 17:14:18.811860
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = '7568af076be5'
down_revision: Union[str, None] = '365f70fcfa70'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Şablon eşik değerleri
    op.add_column(
        'quality_templates',
        sa.Column('increase_threshold', sa.Float(), nullable=True, server_default='10.0'),
    )
    op.add_column(
        'quality_templates',
        sa.Column('decrease_threshold', sa.Float(), nullable=True, server_default='10.0'),
    )

    # Alan ay sonu bayrağı
    op.add_column(
        'quality_template_fields',
        sa.Column('is_month_end_only', sa.Boolean(), nullable=False, server_default='false'),
    )


def downgrade() -> None:
    op.drop_column('quality_templates', 'decrease_threshold')
    op.drop_column('quality_templates', 'increase_threshold')
    op.drop_column('quality_template_fields', 'is_month_end_only')
