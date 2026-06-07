"""scheduled_definitions.billing_offset_months — cari fatura gecikmesi (tüketim ayı kayması)

Bazı abonelik faturaları tüketim ayından SONRA kesilir (ör. su: ASAT faturası ay başında
gelir = önceki ayın tüketimi). Bu alan kaç ay geriye kaydırılacağını tutar (su=1, elektrik=0).

Revision ID: d8f4b2a6c1e9
Revises: c7e3a1f9b4d8
Create Date: 2026-06-06
"""
from alembic import op
import sqlalchemy as sa

revision = "d8f4b2a6c1e9"
down_revision = "c7e3a1f9b4d8"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "scheduled_definitions",
        sa.Column("billing_offset_months", sa.Integer(), nullable=False, server_default="0"),
    )


def downgrade():
    op.drop_column("scheduled_definitions", "billing_offset_months")
