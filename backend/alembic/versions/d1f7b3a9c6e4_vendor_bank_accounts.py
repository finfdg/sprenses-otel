"""vendor_bank_accounts + payment_instruction_items.bank_name/iban

Revision ID: d1f7b3a9c6e4
Revises: c9e6a4f2d8b1
Create Date: 2026-06-06

Cari banka hesapları (banka + IBAN; bir cari → 0..N) ve ödeme talimatı kalemine
seçilen banka/IBAN snapshot'ı. Elle yazıldı.
"""
from alembic import op
import sqlalchemy as sa

revision = "d1f7b3a9c6e4"
down_revision = "c9e6a4f2d8b1"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "vendor_bank_accounts",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("vendor_id", sa.Integer(), sa.ForeignKey("vendors.id", ondelete="CASCADE"), nullable=False),
        sa.Column("bank_name", sa.String(100), nullable=True),
        sa.Column("iban", sa.String(34), nullable=False),
        sa.Column("account_holder", sa.String(200), nullable=True),
        sa.Column("is_default", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
    )
    op.create_index("ix_vendor_bank_vendor", "vendor_bank_accounts", ["vendor_id"])
    op.add_column("payment_instruction_items", sa.Column("bank_name", sa.String(100), nullable=True))
    op.add_column("payment_instruction_items", sa.Column("iban", sa.String(34), nullable=True))


def downgrade():
    op.drop_column("payment_instruction_items", "iban")
    op.drop_column("payment_instruction_items", "bank_name")
    op.drop_index("ix_vendor_bank_vendor", table_name="vendor_bank_accounts")
    op.drop_table("vendor_bank_accounts")
