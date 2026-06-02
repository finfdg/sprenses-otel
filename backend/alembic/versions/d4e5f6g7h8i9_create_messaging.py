"""Create messaging tables (conversations, conversation_members, messages)

Revision ID: d4e5f6g7h8i9
Revises: c3d4e5f6g7h8
Create Date: 2026-02-22
"""
from alembic import op
import sqlalchemy as sa

revision = "d4e5f6g7h8i9"
down_revision = "c3d4e5f6g7h8"
branch_labels = None
depends_on = None


def upgrade():
    # 1. conversations table
    op.create_table(
        "conversations",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("type", sa.String(20), nullable=False, server_default="private"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )

    # 2. conversation_members table
    op.create_table(
        "conversation_members",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("conversation_id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("last_read_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("joined_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["conversation_id"], ["conversations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("conversation_id", "user_id", name="uq_conversation_member"),
        sa.PrimaryKeyConstraint("id"),
    )

    # 3. messages table
    op.create_table(
        "messages",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("conversation_id", sa.Integer(), nullable=False),
        sa.Column("sender_id", sa.Integer(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("message_type", sa.String(20), nullable=False, server_default="text"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["conversation_id"], ["conversations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["sender_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_messages_conversation_created", "messages",
        ["conversation_id", "created_at"]
    )

    # 4. Register messaging module
    op.execute("""
        INSERT INTO modules (name, code, icon, parent_id, sort_order, is_active)
        VALUES ('Mesajlaşma', 'messaging', 'chat', NULL, 5, true)
    """)

    # 5. Grant Admin role full access
    op.execute("""
        INSERT INTO role_module_permissions (role_id, module_id, can_view, can_use)
        SELECT r.id, m.id, true, true
        FROM roles r, modules m
        WHERE r.name = 'Admin' AND m.code = 'messaging'
    """)


def downgrade():
    op.execute("DELETE FROM role_module_permissions WHERE module_id IN (SELECT id FROM modules WHERE code = 'messaging')")
    op.execute("DELETE FROM modules WHERE code = 'messaging'")
    op.drop_index("ix_messages_conversation_created", table_name="messages")
    op.drop_table("messages")
    op.drop_table("conversation_members")
    op.drop_table("conversations")
