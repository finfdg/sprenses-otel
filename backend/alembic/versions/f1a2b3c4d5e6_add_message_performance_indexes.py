"""add_message_performance_indexes

Revision ID: f1a2b3c4d5e6
Revises: e3a4b5c6d7e8
Create Date: 2026-02-24 15:00:00.000000

"""
from typing import Sequence, Union

from alembic import op

revision: str = "f1a2b3c4d5e6"
down_revision: Union[str, None] = "e3a4b5c6d7e8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_index("ix_messages_is_deleted", "messages", ["is_deleted"], unique=False)
    op.create_index(
        "ix_messages_conv_deleted_created",
        "messages",
        ["conversation_id", "is_deleted", "created_at"],
        unique=False,
    )
    op.create_index("ix_messages_message_type", "messages", ["message_type"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_messages_message_type", table_name="messages")
    op.drop_index("ix_messages_conv_deleted_created", table_name="messages")
    op.drop_index("ix_messages_is_deleted", table_name="messages")
