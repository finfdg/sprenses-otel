"""sales_advances (Sedna 340 Alınan Avanslar hesap özeti)

Revision ID: b6d2f8a4e1c9
Revises: a1c5e9f3d7b2
Create Date: 2026-06-06
"""
from alembic import op
import sqlalchemy as sa

revision = "b6d2f8a4e1c9"
down_revision = "a1c5e9f3d7b2"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "sales_advances",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("code", sa.String(length=50), nullable=False),
        sa.Column("name", sa.String(length=300), nullable=True),
        sa.Column("currency", sa.String(length=5), server_default="TL", nullable=False),
        sa.Column("received", sa.Numeric(15, 2), server_default="0", nullable=False),
        sa.Column("consumed", sa.Numeric(15, 2), server_default="0", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )
    op.create_index("ix_sales_advances_code", "sales_advances", ["code"])


def downgrade():
    op.drop_table("sales_advances")
