"""add group messaging and file columns

Revision ID: c1218b0c6358
Revises: g6h7i8j9k0l1
Create Date: 2026-02-24 13:08:47.639627
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = 'c1218b0c6358'
down_revision: Union[str, None] = 'g6h7i8j9k0l1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # conversations: grup desteği
    op.add_column('conversations', sa.Column('name', sa.String(length=100), nullable=True))
    op.add_column('conversations', sa.Column('created_by', sa.Integer(), nullable=True))
    op.create_foreign_key(
        'fk_conversations_created_by_users',
        'conversations', 'users', ['created_by'], ['id'], ondelete='SET NULL'
    )

    # conversation_members: yönetici desteği
    op.add_column('conversation_members', sa.Column(
        'is_admin', sa.Boolean(), nullable=False, server_default=sa.text('false')
    ))

    # messages: dosya desteği
    op.add_column('messages', sa.Column('file_url', sa.String(length=500), nullable=True))
    op.add_column('messages', sa.Column('file_name', sa.String(length=255), nullable=True))
    op.add_column('messages', sa.Column('file_size', sa.Integer(), nullable=True))
    op.add_column('messages', sa.Column('file_type', sa.String(length=100), nullable=True))


def downgrade() -> None:
    op.drop_column('messages', 'file_type')
    op.drop_column('messages', 'file_size')
    op.drop_column('messages', 'file_name')
    op.drop_column('messages', 'file_url')
    op.drop_column('conversation_members', 'is_admin')
    op.drop_constraint('fk_conversations_created_by_users', 'conversations', type_='foreignkey')
    op.drop_column('conversations', 'created_by')
    op.drop_column('conversations', 'name')
