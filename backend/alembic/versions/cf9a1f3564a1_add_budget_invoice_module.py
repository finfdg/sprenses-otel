"""add_budget_invoice_module

Revision ID: cf9a1f3564a1
Revises: p4q5r6s7t8u9
Create Date: 2026-04-01 10:21:03.793251
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = 'cf9a1f3564a1'
down_revision: Union[str, None] = 'p4q5r6s7t8u9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── Departments ────────────────────────────────────────
    op.create_table('departments',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(length=100), nullable=False),
        sa.Column('code', sa.String(length=30), nullable=False),
        sa.Column('manager_id', sa.Integer(), nullable=True),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default=sa.text('true')),
        sa.Column('sort_order', sa.Integer(), nullable=False, server_default=sa.text('0')),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True),
        sa.ForeignKeyConstraint(['manager_id'], ['users.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('name'),
    )
    op.create_index(op.f('ix_departments_id'), 'departments', ['id'], unique=False)
    op.create_index(op.f('ix_departments_code'), 'departments', ['code'], unique=True)

    # ── Budget Categories ──────────────────────────────────
    op.create_table('budget_categories',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(length=100), nullable=False),
        sa.Column('type', sa.String(length=10), nullable=False),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default=sa.text('true')),
        sa.Column('sort_order', sa.Integer(), nullable=False, server_default=sa.text('0')),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('name', 'type', name='uq_budget_category_name_type'),
    )
    op.create_index(op.f('ix_budget_categories_id'), 'budget_categories', ['id'], unique=False)

    # ── Budgets ────────────────────────────────────────────
    op.create_table('budgets',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('department_id', sa.Integer(), nullable=False),
        sa.Column('category_id', sa.Integer(), nullable=False),
        sa.Column('year', sa.Integer(), nullable=False),
        sa.Column('month', sa.Integer(), nullable=False),
        sa.Column('planned_amount', sa.Numeric(precision=15, scale=2), nullable=False, server_default=sa.text('0')),
        sa.Column('actual_amount', sa.Numeric(precision=15, scale=2), nullable=False, server_default=sa.text('0')),
        sa.Column('currency', sa.String(length=5), nullable=False, server_default=sa.text("'TRY'")),
        sa.Column('notes', sa.Text(), nullable=True),
        sa.Column('created_by', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True),
        sa.ForeignKeyConstraint(['category_id'], ['budget_categories.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['created_by'], ['users.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['department_id'], ['departments.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('department_id', 'category_id', 'year', 'month', name='uq_budget_dept_cat_year_month'),
    )
    op.create_index(op.f('ix_budgets_id'), 'budgets', ['id'], unique=False)
    op.create_index(op.f('ix_budgets_department_id'), 'budgets', ['department_id'], unique=False)
    op.create_index(op.f('ix_budgets_category_id'), 'budgets', ['category_id'], unique=False)
    op.create_index('ix_budgets_year_month', 'budgets', ['year', 'month'], unique=False)

    # ── Invoices ───────────────────────────────────────────
    op.create_table('invoices',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('invoice_no', sa.String(length=50), nullable=True),
        sa.Column('vendor_name', sa.String(length=300), nullable=True),
        sa.Column('department_id', sa.Integer(), nullable=False),
        sa.Column('category_id', sa.Integer(), nullable=True),
        sa.Column('amount', sa.Numeric(precision=15, scale=2), nullable=False),
        sa.Column('currency', sa.String(length=5), nullable=False, server_default=sa.text("'TRY'")),
        sa.Column('invoice_date', sa.Date(), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('status', sa.String(length=20), nullable=False, server_default=sa.text("'draft'")),
        sa.Column('submitted_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('submitted_by', sa.Integer(), nullable=True),
        sa.Column('approved_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('approved_by', sa.Integer(), nullable=True),
        sa.Column('rejection_note', sa.Text(), nullable=True),
        sa.Column('approval_note', sa.Text(), nullable=True),
        sa.Column('created_by', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True),
        sa.ForeignKeyConstraint(['approved_by'], ['users.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['category_id'], ['budget_categories.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['created_by'], ['users.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['department_id'], ['departments.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['submitted_by'], ['users.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_invoices_id'), 'invoices', ['id'], unique=False)
    op.create_index(op.f('ix_invoices_department_id'), 'invoices', ['department_id'], unique=False)
    op.create_index(op.f('ix_invoices_category_id'), 'invoices', ['category_id'], unique=False)
    op.create_index(op.f('ix_invoices_status'), 'invoices', ['status'], unique=False)
    op.create_index('ix_invoices_dept_status', 'invoices', ['department_id', 'status'], unique=False)
    op.create_index('ix_invoices_status_submitted', 'invoices', ['status', 'submitted_at'], unique=False)

    # ── Invoice Attachments ────────────────────────────────
    op.create_table('invoice_attachments',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('invoice_id', sa.Integer(), nullable=False),
        sa.Column('file_name', sa.String(length=255), nullable=False),
        sa.Column('file_url', sa.String(length=500), nullable=False),
        sa.Column('file_type', sa.String(length=100), nullable=True),
        sa.Column('file_size', sa.Integer(), nullable=True),
        sa.Column('uploaded_by', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True),
        sa.ForeignKeyConstraint(['invoice_id'], ['invoices.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['uploaded_by'], ['users.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_invoice_attachments_id'), 'invoice_attachments', ['id'], unique=False)
    op.create_index(op.f('ix_invoice_attachments_invoice_id'), 'invoice_attachments', ['invoice_id'], unique=False)

    # ── Seed: Modules ──────────────────────────────────────
    op.execute("""
        INSERT INTO modules (name, code, description, parent_id, is_active, sort_order)
        SELECT 'Bütçe', 'finance.butce', 'Bütçe planlama ve departman yönetimi',
               (SELECT id FROM modules WHERE code = 'finance'), true, 80
        WHERE NOT EXISTS (SELECT 1 FROM modules WHERE code = 'finance.butce');
    """)
    op.execute("""
        INSERT INTO modules (name, code, description, parent_id, is_active, sort_order)
        SELECT 'Faturalar', 'finance.faturalar', 'Fatura girişi ve onay iş akışı',
               (SELECT id FROM modules WHERE code = 'finance'), true, 90
        WHERE NOT EXISTS (SELECT 1 FROM modules WHERE code = 'finance.faturalar');
    """)

    # Grant Admin role permissions
    op.execute("""
        INSERT INTO role_module_permissions (role_id, module_id, can_view, can_use)
        SELECT r.id, m.id, true, true
        FROM roles r, modules m
        WHERE r.name = 'Admin' AND m.code IN ('finance.butce', 'finance.faturalar')
        ON CONFLICT DO NOTHING;
    """)

    # ── Seed: Departments ──────────────────────────────────
    op.execute("""
        INSERT INTO departments (name, code, sort_order) VALUES
        ('Yiyecek & İçecek', 'fb', 1),
        ('Kat Hizmetleri', 'housekeeping', 2),
        ('Ön Büro', 'front_office', 3),
        ('Teknik Servis', 'engineering', 4),
        ('Satış & Pazarlama', 'sales', 5),
        ('İnsan Kaynakları', 'hr', 6),
        ('Bilgi Teknolojileri', 'it', 7),
        ('Muhasebe', 'accounting', 8),
        ('Genel Müdürlük', 'gm', 9),
        ('Güvenlik', 'security', 10),
        ('SPA & Sağlık', 'spa', 11),
        ('Animasyon', 'animation', 12)
        ON CONFLICT DO NOTHING;
    """)

    # ── Seed: Budget Categories ────────────────────────────
    op.execute("""
        INSERT INTO budget_categories (name, type, sort_order) VALUES
        ('Oda Geliri', 'income', 1),
        ('F&B Geliri', 'income', 2),
        ('SPA Geliri', 'income', 3),
        ('Diğer Gelir', 'income', 4),
        ('Personel Gideri', 'expense', 10),
        ('Yiyecek Malzeme', 'expense', 11),
        ('İçecek Malzeme', 'expense', 12),
        ('Temizlik Malzeme', 'expense', 13),
        ('Enerji', 'expense', 14),
        ('Su', 'expense', 15),
        ('Bakım & Onarım', 'expense', 16),
        ('Pazarlama', 'expense', 17),
        ('Sigorta', 'expense', 18),
        ('Vergi & SGK', 'expense', 19),
        ('Komisyon', 'expense', 20),
        ('Kira', 'expense', 21),
        ('İletişim', 'expense', 22),
        ('Ulaşım', 'expense', 23),
        ('Diğer Gider', 'expense', 24)
        ON CONFLICT DO NOTHING;
    """)


def downgrade() -> None:
    op.drop_index(op.f('ix_invoice_attachments_invoice_id'), table_name='invoice_attachments')
    op.drop_index(op.f('ix_invoice_attachments_id'), table_name='invoice_attachments')
    op.drop_table('invoice_attachments')
    op.drop_index('ix_invoices_status_submitted', table_name='invoices')
    op.drop_index(op.f('ix_invoices_status'), table_name='invoices')
    op.drop_index(op.f('ix_invoices_id'), table_name='invoices')
    op.drop_index('ix_invoices_dept_status', table_name='invoices')
    op.drop_index(op.f('ix_invoices_department_id'), table_name='invoices')
    op.drop_index(op.f('ix_invoices_category_id'), table_name='invoices')
    op.drop_table('invoices')
    op.drop_index('ix_budgets_year_month', table_name='budgets')
    op.drop_index(op.f('ix_budgets_id'), table_name='budgets')
    op.drop_index(op.f('ix_budgets_department_id'), table_name='budgets')
    op.drop_index(op.f('ix_budgets_category_id'), table_name='budgets')
    op.drop_table('budgets')
    op.drop_index(op.f('ix_departments_id'), table_name='departments')
    op.drop_index(op.f('ix_departments_code'), table_name='departments')
    op.drop_table('departments')
    op.drop_index(op.f('ix_budget_categories_id'), table_name='budget_categories')
    op.drop_table('budget_categories')

    op.execute("DELETE FROM role_module_permissions WHERE module_id IN (SELECT id FROM modules WHERE code IN ('finance.butce', 'finance.faturalar'));")
    op.execute("DELETE FROM modules WHERE code IN ('finance.butce', 'finance.faturalar');")
