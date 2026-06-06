"""sales_invoices + sales_collections (otel satis faturalari + tahsilat)

Revision ID: e3a9c7d2b5f1
Revises: d1f7b3a9c6e4
Create Date: 2026-06-06
"""
from alembic import op
import sqlalchemy as sa

revision = "e3a9c7d2b5f1"
down_revision = "d1f7b3a9c6e4"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "sales_invoices",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("customer_code", sa.String(length=50), nullable=False),
        sa.Column("customer_name", sa.String(length=300), nullable=False),
        sa.Column("is_munferit", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("invoice_no", sa.String(length=60), nullable=True),
        sa.Column("invoice_date", sa.Date(), nullable=False),
        sa.Column("amount", sa.Numeric(15, 2), nullable=False),
        sa.Column("currency", sa.String(length=5), server_default="TL", nullable=False),
        sa.Column("description", sa.String(length=300), nullable=True),
        sa.Column("tx_hash", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )
    op.create_index("ix_sales_inv_customer", "sales_invoices", ["customer_code"])
    op.create_index("ix_sales_inv_date", "sales_invoices", ["invoice_date"])
    op.create_index("ix_sales_inv_hash", "sales_invoices", ["tx_hash"])

    op.create_table(
        "sales_collections",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("customer_code", sa.String(length=50), nullable=False),
        sa.Column("collection_date", sa.Date(), nullable=False),
        sa.Column("amount", sa.Numeric(15, 2), nullable=False),
        sa.Column("description", sa.String(length=300), nullable=True),
        sa.Column("tx_hash", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )
    op.create_index("ix_sales_col_customer", "sales_collections", ["customer_code"])
    op.create_index("ix_sales_col_hash", "sales_collections", ["tx_hash"])


def downgrade():
    op.drop_table("sales_collections")
    op.drop_table("sales_invoices")
