"""system.docs modülü (Dokümanlar) + admin görüntüleme izni

Revision ID: e3b7c9d1f2a4
Revises: d2a6c4f8e1b5
Create Date: 2026-06-21

Sistem altına salt-okunur "Dokümanlar" modülü — proje .md dokümanlarını panelde
görüntüleyip indirmek için. İzin: `system.users`'ı görebilen her role view verilir
(sistem yöneticisi zaten dokümanları görebilmeli). Idempotent (NOT EXISTS guard'lı).
"""
from alembic import op

revision = "e3b7c9d1f2a4"
down_revision = "d2a6c4f8e1b5"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
        INSERT INTO modules (name, code, description, icon, parent_id, sort_order, is_active, created_at)
        SELECT 'Dokümanlar', 'system.docs', 'Proje dokümantasyonu — görüntüle ve indir',
               'document-text', (SELECT id FROM modules WHERE code = 'system'), 110, true, now()
        WHERE NOT EXISTS (SELECT 1 FROM modules WHERE code = 'system.docs')
    """)
    # system.users'ı görebilen rollere system.docs view ver (idempotent)
    op.execute("""
        INSERT INTO role_module_permissions (role_id, module_id, can_view, can_use, created_at)
        SELECT rmp.role_id, (SELECT id FROM modules WHERE code = 'system.docs'), true, false, now()
        FROM role_module_permissions rmp
        JOIN modules m ON m.id = rmp.module_id AND m.code = 'system.users'
        WHERE rmp.can_view = true
          AND NOT EXISTS (
              SELECT 1 FROM role_module_permissions x
              JOIN modules dm ON dm.id = x.module_id AND dm.code = 'system.docs'
              WHERE x.role_id = rmp.role_id
          )
    """)


def downgrade():
    op.execute("DELETE FROM role_module_permissions WHERE module_id = (SELECT id FROM modules WHERE code = 'system.docs')")
    op.execute("DELETE FROM modules WHERE code = 'system.docs'")
