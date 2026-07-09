"""satış alt modülleri sales.acente_mahsup altında birleştirildi

Otel Rezervasyon (sales.hotel_reservation), Günlük Hareketler (sales.daily_reservations)
ve Oda Tipleri (sales.room_types) AYRI RBAC modülleri kaldırıldı; tüm kabiliyetler
"Acente Mahsup & Nakit Akım" (sales.acente_mahsup) modülü altında toplandı.

- Rol izinleri OR ile sales.acente_mahsup'a birleştirilir: eski üç modülün herhangi
  birinde view/use izni olan rol, birleşik modülde de aynı izni alır (izin kaybı yok).
- approval_workflows / approval_requests.module_code eski kodlardan yeni koda taşınır
  (bekleyen room_type onay talepleri executor'daki yeni handler anahtarıyla çalışır).
- 3 eski modül satırı ve izin satırları silinir. VERİ TABLOLARINA (reservations,
  room_types, agency_groups, reservation_uploads) DOKUNULMAZ — yalnız RBAC birleşir.

ELLE yazıldı (autogenerate yanlış DROP üretebilir) — yalnız veri (modules /
role_module_permissions / approval_*) günceller, şema değişikliği yok.

Downgrade en-iyi-çaba: 3 modül yeniden oluşturulur ve her role acente_mahsup'taki
izinlerin AYNISI verilir (orijinal ince ayrım geri getirilemez); approval kayıtlarından
yalnız entity_type='room_type' olanlar sales.room_types'a geri taşınır.

Revision ID: b3c9d5e7f1a2
Revises: d1a3c5e7f9b2
Create Date: 2026-07-09
"""
from typing import Sequence, Union

from alembic import op

revision: str = "b3c9d5e7f1a2"
down_revision: Union[str, None] = "d1a3c5e7f9b2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_OLD_CODES = "('sales.hotel_reservation', 'sales.daily_reservations', 'sales.room_types')"


def upgrade() -> None:
    # ── 0) Hedef modül garanti (taze DB'de e1a2c3d4f5b6 zaten ekler) ──
    op.execute("""
        INSERT INTO modules (name, code, description, parent_id, is_active, sort_order)
        SELECT 'Acente Mahsup & Nakit Akım', 'sales.acente_mahsup',
               'Satış — rezervasyonlar, günlük hareketler, oda tipleri, acente mahsup & nakit akım projeksiyonu',
               (SELECT id FROM modules WHERE code = 'sales'), true, 20
        WHERE NOT EXISTS (SELECT 1 FROM modules WHERE code = 'sales.acente_mahsup');
    """)

    # ── 1) Rol izinlerini OR ile birleştir ──
    op.execute(f"""
        INSERT INTO role_module_permissions (role_id, module_id, can_view, can_use)
        SELECT p.role_id,
               (SELECT id FROM modules WHERE code = 'sales.acente_mahsup'),
               bool_or(p.can_view),
               bool_or(p.can_use)
        FROM role_module_permissions p
        JOIN modules m ON m.id = p.module_id
        WHERE m.code IN {_OLD_CODES}
        GROUP BY p.role_id
        ON CONFLICT ON CONSTRAINT uq_role_module DO UPDATE SET
            can_view = role_module_permissions.can_view OR EXCLUDED.can_view,
            can_use  = role_module_permissions.can_use  OR EXCLUDED.can_use;
    """)

    # ── 2) Onay akışı kayıtlarını yeni modüle taşı ──
    # approval_workflows modüle FK (module_id, ondelete=SET NULL) ile bağlanır —
    # modül silinmeden ÖNCE yeni modüle işaretlenmeli, yoksa workflow yetim kalır.
    op.execute(f"""
        UPDATE approval_workflows
        SET module_id = (SELECT id FROM modules WHERE code = 'sales.acente_mahsup')
        WHERE module_id IN (SELECT id FROM modules WHERE code IN {_OLD_CODES});
    """)
    # approval_requests modül kodunu string saklar
    op.execute(f"""
        UPDATE approval_requests SET module_code = 'sales.acente_mahsup'
        WHERE module_code IN {_OLD_CODES};
    """)

    # ── 3) Eski modülleri ve izinlerini kaldır ──
    op.execute(f"""
        DELETE FROM role_module_permissions
        WHERE module_id IN (SELECT id FROM modules WHERE code IN {_OLD_CODES});
    """)
    op.execute(f"DELETE FROM modules WHERE code IN {_OLD_CODES};")

    # ── 4) Birleşik modülün ad/açıklama/sırasını güncelle ──
    op.execute("""
        UPDATE modules SET
            name = 'Acente Mahsup & Nakit Akım',
            description = 'Satış — rezervasyonlar, günlük hareketler, oda tipleri, acente mahsup & nakit akım projeksiyonu',
            sort_order = 20
        WHERE code = 'sales.acente_mahsup';
    """)


def downgrade() -> None:
    # Best-effort: modülleri yeniden oluştur, acente_mahsup izinlerini kopyala
    op.execute("""
        INSERT INTO modules (name, code, description, parent_id, is_active, sort_order)
        SELECT 'Otel Rezervasyon', 'sales.hotel_reservation',
               'Otel rezervasyon verilerinin XLS ile yüklenmesi ve analiz raporları',
               (SELECT id FROM modules WHERE code = 'sales'), true, 20
        WHERE NOT EXISTS (SELECT 1 FROM modules WHERE code = 'sales.hotel_reservation');
    """)
    op.execute("""
        INSERT INTO modules (name, code, description, parent_id, is_active, sort_order)
        SELECT 'Günlük Hareketler', 'sales.daily_reservations',
               'Gün gün gelen yeni rezervasyonlar ve iptaller — Sedna önbüro canlı verisi',
               (SELECT id FROM modules WHERE code = 'sales'), true, 25
        WHERE NOT EXISTS (SELECT 1 FROM modules WHERE code = 'sales.daily_reservations');
    """)
    op.execute("""
        INSERT INTO modules (name, code, description, parent_id, is_active, sort_order)
        SELECT 'Oda Tipleri', 'sales.room_types',
               'Otel oda tipi envanteri — doluluk hesaplamasında payda olarak kullanılır',
               (SELECT id FROM modules WHERE code = 'sales'), true, 30
        WHERE NOT EXISTS (SELECT 1 FROM modules WHERE code = 'sales.room_types');
    """)
    op.execute("""
        INSERT INTO role_module_permissions (role_id, module_id, can_view, can_use)
        SELECT p.role_id, nm.id, p.can_view, p.can_use
        FROM role_module_permissions p
        JOIN modules am ON am.id = p.module_id AND am.code = 'sales.acente_mahsup'
        CROSS JOIN modules nm
        WHERE nm.code IN ('sales.hotel_reservation', 'sales.daily_reservations', 'sales.room_types')
        ON CONFLICT ON CONSTRAINT uq_role_module DO NOTHING;
    """)
    op.execute("""
        UPDATE approval_workflows
        SET module_id = (SELECT id FROM modules WHERE code = 'sales.room_types')
        WHERE module_id = (SELECT id FROM modules WHERE code = 'sales.acente_mahsup')
          AND EXISTS (
            SELECT 1 FROM approval_requests r
            WHERE r.workflow_id = approval_workflows.id AND r.entity_type = 'room_type');
    """)
    op.execute("""
        UPDATE approval_requests SET module_code = 'sales.room_types'
        WHERE module_code = 'sales.acente_mahsup' AND entity_type = 'room_type';
    """)
