"""add_active_session_id_to_users

Revision ID: e9f10b0683f5
Revises: 4b033bba065d
Create Date: 2026-03-07 10:50:22.716626
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = 'e9f10b0683f5'
down_revision: Union[str, None] = '4b033bba065d'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('users', sa.Column('active_session_id', sa.String(length=36), nullable=True))


def downgrade() -> None:
    op.drop_column('users', 'active_session_id')
