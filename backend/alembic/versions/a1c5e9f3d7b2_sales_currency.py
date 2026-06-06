"""sales_invoices/collections döviz tutarı (amount_currency) + collection currency

Revision ID: a1c5e9f3d7b2
Revises: f4b8d1e6a2c7
Create Date: 2026-06-06
"""
from alembic import op
import sqlalchemy as sa

revision = "a1c5e9f3d7b2"
down_revision = "f4b8d1e6a2c7"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("sales_invoices", sa.Column("amount_currency", sa.Numeric(15, 2), server_default="0", nullable=False))
    op.add_column("sales_collections", sa.Column("currency", sa.String(length=5), server_default="TL", nullable=False))
    op.add_column("sales_collections", sa.Column("amount_currency", sa.Numeric(15, 2), server_default="0", nullable=False))


def downgrade():
    op.drop_column("sales_collections", "amount_currency")
    op.drop_column("sales_collections", "currency")
    op.drop_column("sales_invoices", "amount_currency")
