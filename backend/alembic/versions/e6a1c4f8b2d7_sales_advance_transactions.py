"""Alınan avans hareketlerini ay bazında sakla.

Revision ID: e6a1c4f8b2d7
Revises: d5e9f3a7b2c4
Create Date: 2026-08-05
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "e6a1c4f8b2d7"
down_revision: Union[str, None] = "d5e9f3a7b2c4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "sales_advance_transactions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("sedna_rec_id", sa.Integer(), nullable=False),
        sa.Column("code", sa.String(length=50), nullable=False),
        sa.Column("name", sa.String(length=300), nullable=True),
        sa.Column("transaction_date", sa.Date(), nullable=False),
        sa.Column("document_no", sa.String(length=60), nullable=True),
        sa.Column("currency", sa.String(length=5), server_default="TL", nullable=False),
        sa.Column("received", sa.Numeric(15, 2), server_default="0", nullable=False),
        sa.Column("consumed", sa.Numeric(15, 2), server_default="0", nullable=False),
        sa.Column("received_tl", sa.Numeric(15, 2), server_default="0", nullable=False),
        sa.Column("consumed_tl", sa.Numeric(15, 2), server_default="0", nullable=False),
        sa.Column("description", sa.String(length=300), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_sales_adv_tx_sedna_rec_id", "sales_advance_transactions", ["sedna_rec_id"], unique=True,
    )
    op.create_index(
        "ix_sales_adv_tx_date", "sales_advance_transactions", ["transaction_date"], unique=False,
    )
    op.create_index(
        "ix_sales_adv_tx_code", "sales_advance_transactions", ["code"], unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_sales_adv_tx_code", table_name="sales_advance_transactions")
    op.drop_index("ix_sales_adv_tx_date", table_name="sales_advance_transactions")
    op.drop_index("ix_sales_adv_tx_sedna_rec_id", table_name="sales_advance_transactions")
    op.drop_table("sales_advance_transactions")
