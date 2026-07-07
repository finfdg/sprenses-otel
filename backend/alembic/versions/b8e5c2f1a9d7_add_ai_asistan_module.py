"""add_ai_asistan_module

Yapay Zeka Asistanı modülü (ai üst modülü + ai.asistan alt modülü) ve Admin izni.
FAZ 1 — salt-okuma asistan. Detay: docs/modules/ai-asistan.md

Revision ID: b8e5c2f1a9d7
Revises: a7d3f9b1e8c4
Create Date: 2026-07-07
"""
from typing import Sequence, Union

from alembic import op

revision: str = 'b8e5c2f1a9d7'
down_revision: Union[str, None] = 'a7d3f9b1e8c4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Üst modül: ai (parent_id NULL)
    op.execute("""
        INSERT INTO modules (name, code, description, icon, parent_id, sort_order, is_active)
        SELECT 'Yapay Zeka', 'ai', 'Yapay zeka asistanı', 'Sparkles',
               NULL, (SELECT COALESCE(MAX(sort_order), 0) + 1 FROM modules), true
        WHERE NOT EXISTS (SELECT 1 FROM modules WHERE code = 'ai')
    """)

    # Alt modül: ai.asistan
    op.execute("""
        INSERT INTO modules (name, code, description, icon, parent_id, sort_order, is_active)
        SELECT 'Asistan', 'ai.asistan', 'Doğal dilde soru-cevap asistanı', 'Sparkles',
               m.id, (SELECT COALESCE(MAX(sort_order), 0) + 1 FROM modules), true
        FROM modules m WHERE m.code = 'ai'
          AND NOT EXISTS (SELECT 1 FROM modules WHERE code = 'ai.asistan')
    """)

    # Admin rolüne her iki modül için can_view + can_use
    op.execute("""
        INSERT INTO role_module_permissions (role_id, module_id, can_view, can_use)
        SELECT r.id, m.id, true, true
        FROM roles r, modules m
        WHERE r.name = 'Admin' AND m.code IN ('ai', 'ai.asistan')
        ON CONFLICT DO NOTHING
    """)


def downgrade() -> None:
    op.execute("""
        DELETE FROM role_module_permissions
        WHERE module_id IN (SELECT id FROM modules WHERE code IN ('ai.asistan', 'ai'))
    """)
    op.execute("DELETE FROM modules WHERE code = 'ai.asistan'")
    op.execute("DELETE FROM modules WHERE code = 'ai'")
