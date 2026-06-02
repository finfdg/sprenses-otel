"""add_dept_fields_to_vendor_transactions

Revision ID: 69c783a240bc
Revises: cf9a1f3564a1
Create Date: 2026-04-01
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = '69c783a240bc'
down_revision: Union[str, None] = 'cf9a1f3564a1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('vendor_transactions', sa.Column('department_id', sa.Integer(), nullable=True))
    op.add_column('vendor_transactions', sa.Column('budget_category_id', sa.Integer(), nullable=True))
    op.add_column('vendor_transactions', sa.Column('dept_status', sa.String(length=20), nullable=True))
    op.add_column('vendor_transactions', sa.Column('dept_assigned_by', sa.Integer(), nullable=True))
    op.add_column('vendor_transactions', sa.Column('dept_assigned_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column('vendor_transactions', sa.Column('dept_approved_by', sa.Integer(), nullable=True))
    op.add_column('vendor_transactions', sa.Column('dept_approved_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column('vendor_transactions', sa.Column('dept_rejection_note', sa.Text(), nullable=True))

    op.create_foreign_key('fk_vtx_department', 'vendor_transactions', 'departments', ['department_id'], ['id'], ondelete='SET NULL')
    op.create_foreign_key('fk_vtx_budget_category', 'vendor_transactions', 'budget_categories', ['budget_category_id'], ['id'], ondelete='SET NULL')
    op.create_foreign_key('fk_vtx_dept_assigned_by', 'vendor_transactions', 'users', ['dept_assigned_by'], ['id'], ondelete='SET NULL')
    op.create_foreign_key('fk_vtx_dept_approved_by', 'vendor_transactions', 'users', ['dept_approved_by'], ['id'], ondelete='SET NULL')

    op.create_index('ix_vtx_department', 'vendor_transactions', ['department_id'])
    op.create_index('ix_vtx_dept_status', 'vendor_transactions', ['dept_status'])

    # invoices tablosunu kaldır (artık vendor_transactions üzerinden çalışıyoruz)
    op.drop_table('invoice_attachments')
    op.drop_table('invoices')

    # faturalar modülünü kaldır, yerine onay modülü ekle
    op.execute("DELETE FROM role_module_permissions WHERE module_id IN (SELECT id FROM modules WHERE code = 'finance.faturalar');")
    op.execute("DELETE FROM modules WHERE code = 'finance.faturalar';")

    op.execute("""
        INSERT INTO modules (name, code, description, parent_id, is_active, sort_order)
        SELECT 'Onay', 'finance.onay', 'Departman fatura onay iş akışı',
               (SELECT id FROM modules WHERE code = 'finance'), true, 90
        WHERE NOT EXISTS (SELECT 1 FROM modules WHERE code = 'finance.onay');
    """)
    op.execute("""
        INSERT INTO role_module_permissions (role_id, module_id, can_view, can_use)
        SELECT r.id, m.id, true, true
        FROM roles r, modules m
        WHERE r.name = 'Admin' AND m.code = 'finance.onay'
        ON CONFLICT DO NOTHING;
    """)


def downgrade() -> None:
    op.execute("DELETE FROM role_module_permissions WHERE module_id IN (SELECT id FROM modules WHERE code = 'finance.onay');")
    op.execute("DELETE FROM modules WHERE code = 'finance.onay';")

    op.drop_index('ix_vtx_dept_status', table_name='vendor_transactions')
    op.drop_index('ix_vtx_department', table_name='vendor_transactions')
    op.drop_constraint('fk_vtx_dept_approved_by', 'vendor_transactions', type_='foreignkey')
    op.drop_constraint('fk_vtx_dept_assigned_by', 'vendor_transactions', type_='foreignkey')
    op.drop_constraint('fk_vtx_budget_category', 'vendor_transactions', type_='foreignkey')
    op.drop_constraint('fk_vtx_department', 'vendor_transactions', type_='foreignkey')
    op.drop_column('vendor_transactions', 'dept_rejection_note')
    op.drop_column('vendor_transactions', 'dept_approved_at')
    op.drop_column('vendor_transactions', 'dept_approved_by')
    op.drop_column('vendor_transactions', 'dept_assigned_at')
    op.drop_column('vendor_transactions', 'dept_assigned_by')
    op.drop_column('vendor_transactions', 'dept_status')
    op.drop_column('vendor_transactions', 'budget_category_id')
    op.drop_column('vendor_transactions', 'department_id')
