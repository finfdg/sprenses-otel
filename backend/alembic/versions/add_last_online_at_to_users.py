"""add last_online_at to users

Revision ID: a2b3c4d5e6f7
Revises: 1018118731f2
Create Date: 2026-04-01
"""
from alembic import op
import sqlalchemy as sa

revision = "a2b3c4d5e6f7"
down_revision = "1018118731f2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("users", sa.Column("last_online_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column("users", "last_online_at")
