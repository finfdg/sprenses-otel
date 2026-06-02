"""add transaction tagging system

Revision ID: d4b2e9f01a23
Revises: c3a1f8e92d01
Create Date: 2026-03-10
"""
from typing import Union

from alembic import op
import sqlalchemy as sa

revision: str = "d4b2e9f01a23"
down_revision: Union[str, None] = "c3a1f8e92d01"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1) transaction_categories tablosu
    op.create_table(
        "transaction_categories",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("name", sa.String(50), unique=True, nullable=False),
        sa.Column("color", sa.String(20), nullable=False),
        sa.Column("sort_order", sa.Integer, server_default="0"),
        sa.Column("is_active", sa.Boolean, server_default="true"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    # 2) Seed kategoriler
    op.execute("""
        INSERT INTO transaction_categories (name, color, sort_order) VALUES
        ('Virman', 'purple', 1),
        ('POS', 'teal', 2),
        ('Kredi', 'orange', 3),
        ('Cari', 'cyan', 4),
        ('Personel', 'pink', 5),
        ('Vergi/SGK', 'red', 6),
        ('Komisyon', 'amber', 7),
        ('Kira', 'indigo', 8),
        ('Diğer', 'gray', 9)
    """)

    # 3) bank_transactions'a yeni kolonlar
    op.add_column("bank_transactions", sa.Column(
        "category_id", sa.Integer,
        sa.ForeignKey("transaction_categories.id", ondelete="SET NULL"),
        nullable=True,
    ))
    op.add_column("bank_transactions", sa.Column(
        "tag_note", sa.String(300), nullable=True,
    ))
    op.add_column("bank_transactions", sa.Column(
        "tag_source", sa.String(10), nullable=True,
    ))
    op.create_index("ix_bank_tx_category", "bank_transactions", ["category_id"])


def downgrade() -> None:
    op.drop_index("ix_bank_tx_category", table_name="bank_transactions")
    op.drop_column("bank_transactions", "tag_source")
    op.drop_column("bank_transactions", "tag_note")
    op.drop_column("bank_transactions", "category_id")
    op.drop_table("transaction_categories")
