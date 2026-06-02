"""add_private_conversation_unique_constraint

Revision ID: 5c53043e295c
Revises: df2165d9264c
Create Date: 2026-02-25 03:40:02.664299
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '5c53043e295c'
down_revision: Union[str, None] = 'df2165d9264c'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Yeni sütunları ekle
    op.add_column('conversations', sa.Column('private_user_low', sa.Integer(), nullable=True))
    op.add_column('conversations', sa.Column('private_user_high', sa.Integer(), nullable=True))

    # 2. Mevcut private konuşmaları backfill et
    op.execute("""
        UPDATE conversations c
        SET private_user_low = sub.low_id,
            private_user_high = sub.high_id
        FROM (
            SELECT cm.conversation_id,
                   MIN(cm.user_id) AS low_id,
                   MAX(cm.user_id) AS high_id
            FROM conversation_members cm
            JOIN conversations conv ON conv.id = cm.conversation_id
            WHERE conv.type = 'private'
            GROUP BY cm.conversation_id
            HAVING COUNT(*) = 2
        ) sub
        WHERE c.id = sub.conversation_id
          AND c.type = 'private'
          AND c.private_user_low IS NULL
    """)

    # 3. Unique constraint ekle
    op.create_unique_constraint(
        'uq_private_conversation_users', 'conversations',
        ['private_user_low', 'private_user_high']
    )


def downgrade() -> None:
    op.drop_constraint('uq_private_conversation_users', 'conversations', type_='unique')
    op.drop_column('conversations', 'private_user_high')
    op.drop_column('conversations', 'private_user_low')
