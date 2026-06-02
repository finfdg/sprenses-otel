"""add blocked_amount to bank_accounts

Revision ID: c3a1f8e92d01
Revises: b94c752c1560
Create Date: 2026-03-10
"""
from typing import Union

from alembic import op
import sqlalchemy as sa

revision: str = "c3a1f8e92d01"
down_revision: Union[str, None] = "b94c752c1560"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("bank_accounts", sa.Column("blocked_amount", sa.Numeric(15, 2), nullable=True))


def downgrade() -> None:
    op.drop_column("bank_accounts", "blocked_amount")
