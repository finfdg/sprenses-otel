"""Stok / Depo Maliyet modülü — stock_depots + stock_products + stock_movements

Sedna muhasebeden içe aktarılan stok verisi (depo/departman, ürün kartı, hareketler).

Revision ID: e9a1c3f7b2d4
Revises: d8f4b2a6c1e9
Create Date: 2026-06-07
"""
from alembic import op
import sqlalchemy as sa

revision = "e9a1c3f7b2d4"
down_revision = "d8f4b2a6c1e9"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "stock_depots",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("code", sa.String(20), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("no_consumption", sa.Boolean(), server_default="false"),
        sa.Column("is_expense", sa.Boolean(), server_default="false"),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_stock_depots_code", "stock_depots", ["code"], unique=True)

    op.create_table(
        "stock_products",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("sedna_id", sa.Integer(), nullable=False),
        sa.Column("code", sa.String(60), nullable=True),
        sa.Column("name", sa.String(300), nullable=False),
        sa.Column("currency", sa.String(8), nullable=True),
        sa.Column("stock_type", sa.Integer(), nullable=True),
        sa.Column("current_stock", sa.Numeric(18, 3), server_default="0"),
        sa.Column("last_cost", sa.Numeric(18, 4), server_default="0"),
        sa.Column("current_value", sa.Numeric(18, 2), server_default="0"),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_stock_products_sedna_id", "stock_products", ["sedna_id"], unique=True)
    op.create_index("ix_stock_prod_name", "stock_products", ["name"])

    op.create_table(
        "stock_movements",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("sedna_line_id", sa.Integer(), nullable=False),
        sa.Column("sedna_owner_id", sa.Integer(), nullable=True),
        sa.Column("date", sa.Date(), nullable=True),
        sa.Column("period", sa.String(7), nullable=True),
        sa.Column("type_code", sa.Integer(), nullable=True),
        sa.Column("type_label", sa.String(40), nullable=True),
        sa.Column("direction", sa.String(10), nullable=True),
        sa.Column("product_sedna_id", sa.Integer(), nullable=True),
        sa.Column("product_code", sa.String(60), nullable=True),
        sa.Column("product_name", sa.String(300), nullable=True),
        sa.Column("entry_depot", sa.String(20), nullable=True),
        sa.Column("exit_depot", sa.String(20), nullable=True),
        sa.Column("cons_depot", sa.String(20), nullable=True),
        sa.Column("quantity", sa.Numeric(18, 3), server_default="0"),
        sa.Column("unit_cost", sa.Numeric(18, 4), server_default="0"),
        sa.Column("net_amount", sa.Numeric(18, 2), server_default="0"),
        sa.Column("supplier_code", sa.String(60), nullable=True),
        sa.Column("supplier_name", sa.String(300), nullable=True),
        sa.Column("doc_no", sa.String(60), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_stock_movements_sedna_line_id", "stock_movements", ["sedna_line_id"], unique=True)
    op.create_index("ix_stock_movements_date", "stock_movements", ["date"])
    op.create_index("ix_stock_mov_period", "stock_movements", ["period"])
    op.create_index("ix_stock_mov_dir", "stock_movements", ["direction"])
    op.create_index("ix_stock_mov_prod", "stock_movements", ["product_sedna_id"])
    op.create_index("ix_stock_mov_cons", "stock_movements", ["cons_depot"])


def downgrade():
    op.drop_table("stock_movements")
    op.drop_table("stock_products")
    op.drop_table("stock_depots")
