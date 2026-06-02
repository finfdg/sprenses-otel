"""add cariler module

Revision ID: e1f2a3b4c5d6
Revises: d4b2e9f01a23
Create Date: 2026-03-12
"""
from typing import Union

from alembic import op
import sqlalchemy as sa

revision: str = "e1f2a3b4c5d6"
down_revision: Union[str, None] = "d4b2e9f01a23"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ─── vendors tablosu ─────────────────────────────────
    op.create_table(
        "vendors",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("hesap_kodu", sa.String(50), unique=True, nullable=False),
        sa.Column("hesap_adi", sa.String(300), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_vendors_hesap_kodu", "vendors", ["hesap_kodu"])

    # ─── vendor_uploads tablosu ──────────────────────────
    op.create_table(
        "vendor_uploads",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("file_name", sa.String(255), nullable=False),
        sa.Column("file_url", sa.String(500), nullable=False),
        sa.Column("total_vendors", sa.Integer, server_default="0"),
        sa.Column("total_transactions", sa.Integer, server_default="0"),
        sa.Column("new_transactions", sa.Integer, server_default="0"),
        sa.Column("skipped_transactions", sa.Integer, server_default="0"),
        sa.Column("uploaded_by", sa.Integer, sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("uploaded_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    # ─── vendor_transactions tablosu ─────────────────────
    op.create_table(
        "vendor_transactions",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("vendor_id", sa.Integer, sa.ForeignKey("vendors.id", ondelete="CASCADE"), nullable=False),
        sa.Column("upload_id", sa.Integer, sa.ForeignKey("vendor_uploads.id", ondelete="CASCADE"), nullable=False),
        sa.Column("date", sa.Date, nullable=False),
        sa.Column("evrak_no", sa.String(100), nullable=True),
        sa.Column("transaction_type", sa.String(100), nullable=True),
        sa.Column("fis_no", sa.String(50), nullable=True),
        sa.Column("description", sa.Text, nullable=True),
        sa.Column("borc", sa.Numeric(15, 2), server_default="0"),
        sa.Column("alacak", sa.Numeric(15, 2), server_default="0"),
        sa.Column("bakiye", sa.Numeric(15, 2), nullable=True),
        sa.Column("tx_hash", sa.String(64), nullable=False),
        sa.Column("payment_due_date", sa.Date, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("vendor_id", "tx_hash", name="uq_vendor_tx_hash"),
    )
    op.create_index("ix_vendor_tx_vendor", "vendor_transactions", ["vendor_id"])
    op.create_index("ix_vendor_tx_date", "vendor_transactions", ["date"])
    op.create_index("ix_vendor_tx_upload", "vendor_transactions", ["upload_id"])
    op.create_index("ix_vendor_tx_payment_due", "vendor_transactions", ["payment_due_date"])

    # ─── Modül kaydı ─────────────────────────────────────
    op.execute(
        "INSERT INTO modules (name, code, icon, parent_id, sort_order, is_active) "
        "VALUES ('Cariler', 'finance.cariler', 'users', "
        "(SELECT id FROM modules WHERE code = 'finance'), 3, true)"
    )

    # ─── Admin rolüne izin ver ───────────────────────────
    op.execute(
        "INSERT INTO role_module_permissions (role_id, module_id, can_view, can_use) "
        "SELECT r.id, m.id, true, true "
        "FROM roles r, modules m "
        "WHERE r.name = 'Admin' AND m.code = 'finance.cariler'"
    )


def downgrade() -> None:
    op.execute(
        "DELETE FROM role_module_permissions WHERE module_id IN "
        "(SELECT id FROM modules WHERE code = 'finance.cariler')"
    )
    op.execute("DELETE FROM modules WHERE code = 'finance.cariler'")

    op.drop_index("ix_vendor_tx_payment_due", table_name="vendor_transactions")
    op.drop_index("ix_vendor_tx_upload", table_name="vendor_transactions")
    op.drop_index("ix_vendor_tx_date", table_name="vendor_transactions")
    op.drop_index("ix_vendor_tx_vendor", table_name="vendor_transactions")
    op.drop_table("vendor_transactions")
    op.drop_table("vendor_uploads")
    op.drop_index("ix_vendors_hesap_kodu", table_name="vendors")
    op.drop_table("vendors")
