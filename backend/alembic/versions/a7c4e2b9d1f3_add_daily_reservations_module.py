"""add_daily_reservations_module

sales.daily_reservations modülü (Günlük Hareketler — Sedna canlı gelen/iptal akışı)
+ Admin yetkisi. Tablo yok — modül salt-okunur canlı sorgu (Mizan/Fiş İcmali kalıbı).

Revision ID: a7c4e2b9d1f3
Revises: f1b3d5a7c9e2
Create Date: 2026-06-10 10:00:00.000000
"""
from typing import Sequence, Union

from alembic import op

revision: str = 'a7c4e2b9d1f3'
down_revision: Union[str, None] = 'f1b3d5a7c9e2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── Seed: Modül kaydı (sales altında, Otel Rezervasyon'un hemen ardına) ──
    op.execute("""
        INSERT INTO modules (name, code, description, parent_id, is_active, sort_order)
        SELECT 'Günlük Hareketler', 'sales.daily_reservations',
               'Gün gün gelen rezervasyonlar ve iptaller — Sedna önbüro verisinden canlı',
               (SELECT id FROM modules WHERE code = 'sales'), true, 25
        WHERE NOT EXISTS (SELECT 1 FROM modules WHERE code = 'sales.daily_reservations');
    """)

    # ── Seed: Admin yetkisi ──
    op.execute("""
        INSERT INTO role_module_permissions (role_id, module_id, can_view, can_use)
        SELECT r.id, m.id, true, true
        FROM roles r, modules m
        WHERE r.name = 'Admin' AND m.code = 'sales.daily_reservations'
        ON CONFLICT DO NOTHING;
    """)


def downgrade() -> None:
    op.execute("DELETE FROM role_module_permissions WHERE module_id IN (SELECT id FROM modules WHERE code = 'sales.daily_reservations');")
    op.execute("DELETE FROM modules WHERE code = 'sales.daily_reservations';")
