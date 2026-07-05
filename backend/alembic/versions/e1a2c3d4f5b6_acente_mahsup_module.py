"""acente mahsup & nakit akım modülü + agency_groups vade/kickback kolonları

"Acente Mahsup & Nakit Akım" (sales.acente_mahsup) — Satış altında salt-okunur
projeksiyon panosu (Rezervasyon → Fatura → Avans Mahsubu → Vadeli Tahsilat, EUR).
Modül kaydı + Admin yetkisi + agency_groups'a iki konfig kolonu:
  - term_days (int, default 30): acente tahsilat vadesi (nakit akım kaydırması)
  - kickback_percent (numeric 5,2, default 0): yıl sonu ciro primi oranı

ELLE yazıldı (autogenerate yanlış DROP üretebilir) — yalnız additive: 2 nullable-olmayan
server_default'lu kolon + 1 modül + RBAC. Mevcut veri etkilenmez.

Revision ID: e1a2c3d4f5b6
Revises: d8c3f1a2b4e6
Create Date: 2026-07-05
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "e1a2c3d4f5b6"
down_revision: Union[str, None] = "d8c3f1a2b4e6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── agency_groups: projeksiyon konfig kolonları (server_default ile mevcut satırlar dolar) ──
    op.add_column("agency_groups",
                  sa.Column("term_days", sa.Integer(), server_default="30", nullable=False))
    op.add_column("agency_groups",
                  sa.Column("kickback_percent", sa.Numeric(5, 2), server_default="0", nullable=False))

    # ── Seed: Modül kaydı (sales altında, Oda Tipleri'nin ardına) ──
    op.execute("""
        INSERT INTO modules (name, code, description, parent_id, is_active, sort_order)
        SELECT 'Acente Mahsup & Nakit Akım', 'sales.acente_mahsup',
               'Rezervasyon → fatura → avans mahsubu → vadeli tahsilat projeksiyonu (EUR) + yıl sonu ciro hedefi',
               (SELECT id FROM modules WHERE code = 'sales'), true, 40
        WHERE NOT EXISTS (SELECT 1 FROM modules WHERE code = 'sales.acente_mahsup');
    """)

    # ── Seed: Admin yetkisi ──
    op.execute("""
        INSERT INTO role_module_permissions (role_id, module_id, can_view, can_use)
        SELECT r.id, m.id, true, true
        FROM roles r, modules m
        WHERE r.name = 'Admin' AND m.code = 'sales.acente_mahsup'
        ON CONFLICT DO NOTHING;
    """)


def downgrade() -> None:
    op.execute("DELETE FROM role_module_permissions WHERE module_id IN (SELECT id FROM modules WHERE code = 'sales.acente_mahsup');")
    op.execute("DELETE FROM modules WHERE code = 'sales.acente_mahsup';")
    op.drop_column("agency_groups", "kickback_percent")
    op.drop_column("agency_groups", "term_days")
