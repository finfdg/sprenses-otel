"""add_ai_usage

AI asistan token/maliyet kullanım tablosu (raporlama + kota izleme).

Revision ID: c9f2a4d7e1b3
Revises: b8e5c2f1a9d7
Create Date: 2026-07-07
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = 'c9f2a4d7e1b3'
down_revision: Union[str, None] = 'b8e5c2f1a9d7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'ai_usage',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('user_id', sa.Integer(),
                  sa.ForeignKey('users.id', ondelete='SET NULL'), nullable=True),
        sa.Column('model', sa.String(50), nullable=False),
        sa.Column('input_tokens', sa.Integer(), server_default='0'),
        sa.Column('output_tokens', sa.Integer(), server_default='0'),
        sa.Column('cache_read_tokens', sa.Integer(), server_default='0'),
        sa.Column('cost_usd', sa.Numeric(10, 5), server_default='0'),
        sa.Column('tool_count', sa.Integer(), server_default='0'),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index('ix_ai_usage_user', 'ai_usage', ['user_id'])
    op.create_index('ix_ai_usage_created', 'ai_usage', ['created_at'])


def downgrade() -> None:
    op.drop_index('ix_ai_usage_created', table_name='ai_usage')
    op.drop_index('ix_ai_usage_user', table_name='ai_usage')
    op.drop_table('ai_usage')
