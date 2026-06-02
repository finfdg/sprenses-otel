"""add vendor_id to bank_transactions

Revision ID: g3b4c5d6e7f8
Revises: f2a3b4c5d6e7
Create Date: 2026-03-14
"""
from alembic import op
import sqlalchemy as sa

revision = "g3b4c5d6e7f8"
down_revision = "f2a3b4c5d6e7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "bank_transactions",
        sa.Column(
            "vendor_id",
            sa.Integer,
            sa.ForeignKey("vendors.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.create_index("ix_bank_tx_vendor", "bank_transactions", ["vendor_id"])


def downgrade() -> None:
    op.drop_index("ix_bank_tx_vendor", table_name="bank_transactions")
    op.drop_column("bank_transactions", "vendor_id")
