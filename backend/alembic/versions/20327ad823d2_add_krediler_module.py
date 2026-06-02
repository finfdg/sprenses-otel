"""add_krediler_module

Revision ID: 20327ad823d2
Revises: d2c0d2b06bd3
Create Date: 2026-03-24 19:46:37.492246
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = '20327ad823d2'
down_revision: Union[str, None] = 'd2c0d2b06bd3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # credit_products tablosu
    op.create_table(
        'credit_products',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('type', sa.String(30), nullable=False),
        sa.Column('name', sa.String(200), nullable=False),
        sa.Column('bank_name', sa.String(100), nullable=True),
        sa.Column('company', sa.String(200), nullable=True),
        sa.Column('currency', sa.String(5), nullable=False, server_default='TRY'),
        sa.Column('total_amount', sa.Numeric(15, 2), nullable=False, server_default='0'),
        sa.Column('remaining_amount', sa.Numeric(15, 2), nullable=False, server_default='0'),
        sa.Column('interest_rate', sa.Numeric(6, 4), nullable=True),
        sa.Column('start_date', sa.Date(), nullable=True),
        sa.Column('end_date', sa.Date(), nullable=True),
        sa.Column('status', sa.String(20), nullable=False, server_default='active'),
        sa.Column('details', sa.Text(), nullable=True),
        sa.Column('notes', sa.Text(), nullable=True),
        sa.Column('created_by', sa.Integer(), sa.ForeignKey('users.id', ondelete='SET NULL'), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index('ix_credit_products_type', 'credit_products', ['type'])
    op.create_index('ix_credit_products_status', 'credit_products', ['status'])

    # credit_payments tablosu
    op.create_table(
        'credit_payments',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('credit_product_id', sa.Integer(),
                   sa.ForeignKey('credit_products.id', ondelete='CASCADE'), nullable=False),
        sa.Column('installment_no', sa.Integer(), nullable=True),
        sa.Column('due_date', sa.Date(), nullable=False),
        sa.Column('amount', sa.Numeric(15, 2), nullable=False),
        sa.Column('principal', sa.Numeric(15, 2), nullable=True),
        sa.Column('interest', sa.Numeric(15, 2), nullable=True),
        sa.Column('tax', sa.Numeric(15, 2), nullable=True),
        sa.Column('is_paid', sa.Boolean(), nullable=False, server_default='false'),
        sa.Column('paid_date', sa.Date(), nullable=True),
        sa.Column('bank_transaction_id', sa.Integer(),
                   sa.ForeignKey('bank_transactions.id', ondelete='SET NULL'), nullable=True),
        sa.Column('match_number', sa.Integer(), nullable=True),
        sa.Column('notes', sa.String(300), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index('ix_credit_payments_due_date', 'credit_payments', ['due_date'])
    op.create_index('ix_credit_payments_product', 'credit_payments', ['credit_product_id'])

    # Modül kaydı: finance.krediler
    op.execute("""
        INSERT INTO modules (name, code, description, icon, parent_id, sort_order, is_active)
        SELECT 'Krediler', 'finance.krediler', 'Kredi ürünleri ve ödeme planı yönetimi', 'CreditCard',
               m.id, (SELECT COALESCE(MAX(sort_order), 0) + 1 FROM modules), true
        FROM modules m WHERE m.code = 'finance'
        ON CONFLICT DO NOTHING
    """)

    # Admin rolüne izin ver
    op.execute("""
        INSERT INTO role_module_permissions (role_id, module_id, can_view, can_use)
        SELECT r.id, m.id, true, true
        FROM roles r, modules m
        WHERE r.name = 'Admin' AND m.code = 'finance.krediler'
        ON CONFLICT DO NOTHING
    """)


def downgrade() -> None:
    op.execute("DELETE FROM role_module_permissions WHERE module_id = (SELECT id FROM modules WHERE code = 'finance.krediler')")
    op.execute("DELETE FROM modules WHERE code = 'finance.krediler'")
    op.drop_table('credit_payments')
    op.drop_table('credit_products')
