"""add_ai_conversations

AI asistan konuşma kalıcılığı — ai_conversations + ai_messages.

Revision ID: d1a3c5e7f9b2
Revises: c9f2a4d7e1b3
Create Date: 2026-07-07
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = 'd1a3c5e7f9b2'
down_revision: Union[str, None] = 'c9f2a4d7e1b3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'ai_conversations',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('user_id', sa.Integer(),
                  sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
        sa.Column('title', sa.String(200), server_default='Yeni sohbet'),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index('ix_ai_conversations_user', 'ai_conversations', ['user_id'])

    op.create_table(
        'ai_messages',
        sa.Column('id', sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column('conversation_id', sa.Integer(),
                  sa.ForeignKey('ai_conversations.id', ondelete='CASCADE'), nullable=False),
        sa.Column('role', sa.String(20), nullable=False),
        sa.Column('content', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index('ix_ai_messages_conversation', 'ai_messages', ['conversation_id'])


def downgrade() -> None:
    op.drop_index('ix_ai_messages_conversation', table_name='ai_messages')
    op.drop_table('ai_messages')
    op.drop_index('ix_ai_conversations_user', table_name='ai_conversations')
    op.drop_table('ai_conversations')
