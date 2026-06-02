"""add vendor payment_days column

Revision ID: f2a3b4c5d6e7
Revises: e1f2a3b4c5d6
Create Date: 2026-03-12
"""
from typing import Union

from alembic import op
import sqlalchemy as sa

revision: str = "f2a3b4c5d6e7"
down_revision: Union[str, None] = "e1f2a3b4c5d6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("vendors", sa.Column("payment_days", sa.Integer, server_default="90", nullable=False))


def downgrade() -> None:
    op.drop_column("vendors", "payment_days")
