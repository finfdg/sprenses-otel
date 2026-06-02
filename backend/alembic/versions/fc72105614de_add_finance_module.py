"""add_finance_module

Revision ID: fc72105614de
Revises: e9f10b0683f5
Create Date: 2026-03-07 11:08:29.603108
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = 'fc72105614de'
down_revision: Union[str, None] = 'e9f10b0683f5'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # cash_flows tablosu
    op.create_table('cash_flows',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('title', sa.String(length=200), nullable=False),
        sa.Column('type', sa.String(length=20), nullable=False),
        sa.Column('amount', sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('date', sa.Date(), server_default=sa.text('CURRENT_DATE'), nullable=False),
        sa.Column('created_by', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['created_by'], ['users.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_cash_flows_created_by', 'cash_flows', ['created_by'], unique=False)
    op.create_index('ix_cash_flows_date', 'cash_flows', ['date'], unique=False)
    op.create_index('ix_cash_flows_type', 'cash_flows', ['type'], unique=False)

    # Finans ana modülü
    op.execute(
        "INSERT INTO modules (name, code, icon, parent_id, sort_order, is_active) "
        "VALUES ('Finans', 'finance', 'banknotes', NULL, 8, true)"
    )
    # Nakit Akım alt modülü
    op.execute(
        "INSERT INTO modules (name, code, icon, parent_id, sort_order, is_active) "
        "VALUES ('Nakit Akım', 'finance.cash_flow', 'arrow-trending', "
        "(SELECT id FROM modules WHERE code = 'finance'), 0, true)"
    )

    # Admin rolüne izin ver
    op.execute(
        "INSERT INTO role_module_permissions (role_id, module_id, can_view, can_use) "
        "SELECT r.id, m.id, true, true "
        "FROM roles r, modules m "
        "WHERE r.name = 'Admin' AND m.code IN ('finance', 'finance.cash_flow')"
    )

    # Örnek veriler
    op.execute(
        "INSERT INTO cash_flows (title, type, amount, description, date, created_by) VALUES "
        "('Oda Gelirleri', 'income', 45000.00, 'Mart ayı oda satış geliri', '2026-03-01', "
        "(SELECT id FROM users WHERE username = 'admin' LIMIT 1)), "
        "('Restoran Geliri', 'income', 12500.00, 'Restoran ve bar geliri', '2026-03-02', "
        "(SELECT id FROM users WHERE username = 'admin' LIMIT 1)), "
        "('SPA Geliri', 'income', 8200.00, 'SPA ve wellness geliri', '2026-03-03', "
        "(SELECT id FROM users WHERE username = 'admin' LIMIT 1)), "
        "('Toplantı Salonu', 'income', 6800.00, 'Toplantı salonu kiralama', '2026-03-04', "
        "(SELECT id FROM users WHERE username = 'admin' LIMIT 1)), "
        "('Minibar Geliri', 'income', 3400.00, 'Minibar satışları', '2026-03-05', "
        "(SELECT id FROM users WHERE username = 'admin' LIMIT 1)), "
        "('Personel Maaşları', 'expense', 32000.00, 'Mart ayı personel maaşları', '2026-03-01', "
        "(SELECT id FROM users WHERE username = 'admin' LIMIT 1)), "
        "('Elektrik Faturası', 'expense', 5200.00, 'Mart ayı elektrik gideri', '2026-03-02', "
        "(SELECT id FROM users WHERE username = 'admin' LIMIT 1)), "
        "('Gıda Alımları', 'expense', 8900.00, 'Restoran gıda tedariği', '2026-03-03', "
        "(SELECT id FROM users WHERE username = 'admin' LIMIT 1)), "
        "('Temizlik Malzemeleri', 'expense', 2100.00, 'Temizlik ve hijyen ürünleri', '2026-03-04', "
        "(SELECT id FROM users WHERE username = 'admin' LIMIT 1)), "
        "('Bakım Onarım', 'expense', 4500.00, 'Genel bakım ve onarım giderleri', '2026-03-05', "
        "(SELECT id FROM users WHERE username = 'admin' LIMIT 1))"
    )


def downgrade() -> None:
    op.execute("DELETE FROM cash_flows")
    op.execute(
        "DELETE FROM role_module_permissions WHERE module_id IN "
        "(SELECT id FROM modules WHERE code IN ('finance', 'finance.cash_flow'))"
    )
    op.execute("DELETE FROM modules WHERE code IN ('finance.cash_flow', 'finance')")
    op.drop_index('ix_cash_flows_type', table_name='cash_flows')
    op.drop_index('ix_cash_flows_date', table_name='cash_flows')
    op.drop_index('ix_cash_flows_created_by', table_name='cash_flows')
    op.drop_table('cash_flows')
