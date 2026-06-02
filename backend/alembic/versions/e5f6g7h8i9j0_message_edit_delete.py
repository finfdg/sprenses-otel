"""Add is_edited, edited_at, is_deleted to messages

Revision ID: e5f6g7h8i9j0
Revises: d4e5f6g7h8i9
Create Date: 2026-02-23
"""
from alembic import op
import sqlalchemy as sa

revision = "e5f6g7h8i9j0"
down_revision = "d4e5f6g7h8i9"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("messages", sa.Column("is_edited", sa.Boolean(), nullable=False, server_default=sa.text("false")))
    op.add_column("messages", sa.Column("edited_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("messages", sa.Column("is_deleted", sa.Boolean(), nullable=False, server_default=sa.text("false")))


def downgrade():
    op.drop_column("messages", "is_deleted")
    op.drop_column("messages", "edited_at")
    op.drop_column("messages", "is_edited")
