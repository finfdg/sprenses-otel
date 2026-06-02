"""Add status field to vendors table

Revision ID: ac3e8808bca8
Revises: 150b94a06791
Create Date: 2026-04-16 08:09:11.434512
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = 'ac3e8808bca8'
down_revision: Union[str, None] = '150b94a06791'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('vendors', sa.Column('status', sa.String(length=30), server_default='normal', nullable=False))


def downgrade() -> None:
    op.drop_column('vendors', 'status')
