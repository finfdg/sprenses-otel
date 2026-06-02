"""add_error_logs_and_log_modules

Revision ID: 1018118731f2
Revises: 69c783a240bc
Create Date: 2026-04-01 15:07:46.367721
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = '1018118731f2'
down_revision: Union[str, None] = '69c783a240bc'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # error_logs tablosu
    op.create_table('error_logs',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('level', sa.String(length=20), nullable=False),
        sa.Column('source', sa.String(length=100), nullable=False),
        sa.Column('message', sa.Text(), nullable=False),
        sa.Column('traceback', sa.Text(), nullable=True),
        sa.Column('method', sa.String(length=10), nullable=True),
        sa.Column('path', sa.String(length=500), nullable=True),
        sa.Column('user_id', sa.Integer(), nullable=True),
        sa.Column('ip_address', sa.String(length=50), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_error_logs_created_at', 'error_logs', ['created_at'], unique=False)
    op.create_index('ix_error_logs_level', 'error_logs', ['level'], unique=False)
    op.create_index('ix_error_logs_source', 'error_logs', ['source'], unique=False)

    # system.audit_logs ve system.error_logs modüllerini ekle
    op.execute("""
        INSERT INTO modules (name, code, parent_id, icon, sort_order, is_active, created_at)
        SELECT 'Audit Logları', 'system.audit_logs',
            (SELECT id FROM modules WHERE code = 'system'),
            'clipboard-document-list', 40, true, now()
        WHERE NOT EXISTS (SELECT 1 FROM modules WHERE code = 'system.audit_logs')
    """)
    op.execute("""
        INSERT INTO modules (name, code, parent_id, icon, sort_order, is_active, created_at)
        SELECT 'Hata Logları', 'system.error_logs',
            (SELECT id FROM modules WHERE code = 'system'),
            'exclamation-triangle', 50, true, now()
        WHERE NOT EXISTS (SELECT 1 FROM modules WHERE code = 'system.error_logs')
    """)

    # Admin rolüne izin ver
    op.execute("""
        INSERT INTO role_module_permissions (role_id, module_id, can_view, can_use)
        SELECT r.id, m.id, true, true
        FROM roles r, modules m
        WHERE r.name = 'Admin'
          AND m.code IN ('system.audit_logs', 'system.error_logs')
          AND NOT EXISTS (
            SELECT 1 FROM role_module_permissions
            WHERE role_id = r.id AND module_id = m.id
          )
    """)


def downgrade() -> None:
    op.execute("DELETE FROM role_module_permissions WHERE module_id IN (SELECT id FROM modules WHERE code IN ('system.audit_logs', 'system.error_logs'))")
    op.execute("DELETE FROM modules WHERE code IN ('system.audit_logs', 'system.error_logs')")
    op.drop_index('ix_error_logs_source', table_name='error_logs')
    op.drop_index('ix_error_logs_level', table_name='error_logs')
    op.drop_index('ix_error_logs_created_at', table_name='error_logs')
    op.drop_table('error_logs')
