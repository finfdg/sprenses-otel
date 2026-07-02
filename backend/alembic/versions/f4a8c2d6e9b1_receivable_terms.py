"""Hak ediş vade tanımları — receivable_terms tablosu + finance.hakedis modül kaydı.

Revision ID: f4a8c2d6e9b1
Revises: e3b7c9d1f2a4
Create Date: 2026-07-02
"""
import sqlalchemy as sa
from alembic import op

revision = "f4a8c2d6e9b1"
down_revision = "e3b7c9d1f2a4"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "receivable_terms",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("customer_code", sa.String(50), nullable=False, unique=True),
        sa.Column("term_days", sa.Integer(), nullable=False, server_default="30"),
        sa.Column("notes", sa.String(300), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    # RBAC modül kaydı: Finans (id=16) altına Hak Ediş Takibi. Admin rolüne tam izin.
    # (id=920 — prod max 915; 905 stok'a ait, ÇAKIŞMAZ. Diğer roller Roller sayfasından.)
    op.execute("""
        INSERT INTO modules (id, name, code, description, icon, parent_id, sort_order, is_active, created_at)
        VALUES (920, 'Hak Ediş Takibi', 'finance.hakedis',
                'Acente fatura alacakları — 30/45 gün anlaşma vadesi takibi',
                'receipt', 16, 12, true, now())
        ON CONFLICT (id) DO NOTHING
    """)
    op.execute("""
        INSERT INTO role_module_permissions (role_id, module_id, can_view, can_use)
        SELECT r.id, 920, true, true FROM roles r WHERE r.name = 'Admin'
        ON CONFLICT DO NOTHING
    """)


def downgrade() -> None:
    op.execute("DELETE FROM role_module_permissions WHERE module_id = 920")
    op.execute("DELETE FROM modules WHERE id = 920")
    op.drop_table("receivable_terms")
