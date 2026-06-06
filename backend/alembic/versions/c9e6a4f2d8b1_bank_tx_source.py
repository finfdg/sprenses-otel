"""bank_transactions.source — ekstre vs manuel (ekstre-dışı düzeltme)

Revision ID: c9e6a4f2d8b1
Revises: b8d5f3a1c9e2
Create Date: 2026-06-06

Manuel (ekstre-dışı) banka hareketlerini ayırt etmek için. Manuel satırlar ilgili
ekstre yüklenince o tarih aralığında otomatik temizlenir → çift kayıt olmaz.
Elle yazıldı.
"""
from alembic import op
import sqlalchemy as sa

revision = "c9e6a4f2d8b1"
down_revision = "b8d5f3a1c9e2"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "bank_transactions",
        sa.Column("source", sa.String(20), nullable=False, server_default="statement"),
    )


def downgrade():
    op.drop_column("bank_transactions", "source")
