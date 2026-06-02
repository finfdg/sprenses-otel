"""add_missing_indexes

Revision ID: f522c5a3cf22
Revises: f87fdf6b0d2d
Create Date: 2026-02-24 10:21:07.755773
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = 'f522c5a3cf22'
down_revision: Union[str, None] = 'f87fdf6b0d2d'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Performans index'leri
    op.create_index('ix_conversation_members_conv_user', 'conversation_members', ['conversation_id', 'user_id'], unique=False)
    op.create_index('ix_conversation_members_user_id', 'conversation_members', ['user_id'], unique=False)
    op.create_index(op.f('ix_conversations_updated_at'), 'conversations', ['updated_at'], unique=False)
    op.create_index('ix_messages_sender_id', 'messages', ['sender_id'], unique=False)
    op.create_index(op.f('ix_users_role_id'), 'users', ['role_id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_users_role_id'), table_name='users')
    op.drop_index('ix_messages_sender_id', table_name='messages')
    op.drop_index(op.f('ix_conversations_updated_at'), table_name='conversations')
    op.drop_index('ix_conversation_members_user_id', table_name='conversation_members')
    op.drop_index('ix_conversation_members_conv_user', table_name='conversation_members')
