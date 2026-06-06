"""recurring↔cari bağlantısı: scheduled_definitions.vendor_id + scheduled_entries.synced_from_cari

Düzenli ödeme tanımları (ör. Elektrik→CK, Su→ASAT) cari satıcıya bağlanır; girişlerin
tahmini tutarları cari gerçek fatura + ödeme durumuyla senkronlanır.

Revision ID: c7e3a1f9b4d8
Revises: b6d2f8a4e1c9
Create Date: 2026-06-06
"""
from alembic import op
import sqlalchemy as sa

revision = "c7e3a1f9b4d8"
down_revision = "b6d2f8a4e1c9"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "scheduled_definitions",
        sa.Column("vendor_id", sa.Integer(), nullable=True),
    )
    op.create_index(
        "ix_scheddef_vendor", "scheduled_definitions", ["vendor_id"], unique=False,
    )
    op.create_foreign_key(
        "fk_scheddef_vendor", "scheduled_definitions", "vendors",
        ["vendor_id"], ["id"], ondelete="SET NULL",
    )
    op.add_column(
        "scheduled_entries",
        sa.Column("synced_from_cari", sa.Boolean(), nullable=False, server_default="false"),
    )


def downgrade():
    op.drop_column("scheduled_entries", "synced_from_cari")
    op.drop_constraint("fk_scheddef_vendor", "scheduled_definitions", type_="foreignkey")
    op.drop_index("ix_scheddef_vendor", table_name="scheduled_definitions")
    op.drop_column("scheduled_definitions", "vendor_id")
