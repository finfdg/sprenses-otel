"""Faz C — cari bakiye mutabakatı + kredi/acente Sedna kod eşlemesi + dönem kilidi.

- credit_products.sedna_account_code (300.* leaf eşlemesi, unique)
- agency_groups.sedna_account_codes (JSON liste — acente başına para birimi ayrı 340 hesabı)
- finance_period_locks (tek satır; uyarı-modu dönem kilidi — bloklamaz)

Revision ID: f7a8b9c0d1e2
Revises: e5f6a7b8c9d0
Create Date: 2026-07-11
"""
import sqlalchemy as sa
from alembic import op

revision = "f7a8b9c0d1e2"
down_revision = "e5f6a7b8c9d0"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("credit_products", sa.Column("sedna_account_code", sa.String(30), nullable=True))
    op.create_unique_constraint(
        "uq_credit_products_sedna_account_code", "credit_products", ["sedna_account_code"])
    op.add_column("agency_groups", sa.Column("sedna_account_codes", sa.JSON(), nullable=True))
    op.create_table(
        "finance_period_locks",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("lock_date", sa.Date(), nullable=False),
        sa.Column("updated_by", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )


def downgrade() -> None:
    op.drop_table("finance_period_locks")
    op.drop_column("agency_groups", "sedna_account_codes")
    op.drop_constraint("uq_credit_products_sedna_account_code", "credit_products", type_="unique")
    op.drop_column("credit_products", "sedna_account_code")
