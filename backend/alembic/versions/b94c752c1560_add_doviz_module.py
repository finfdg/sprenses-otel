"""add_doviz_module

Revision ID: b94c752c1560
Revises: 8d04499a53d5
Create Date: 2026-03-09 15:54:18.051629
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = 'b94c752c1560'
down_revision: Union[str, None] = '8d04499a53d5'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. exchange_rates tablosu
    op.create_table('exchange_rates',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('date', sa.Date(), nullable=False),
        sa.Column('currency_code', sa.String(length=3), nullable=False),
        sa.Column('currency_name', sa.String(length=50), nullable=True),
        sa.Column('unit', sa.Integer(), server_default='1', nullable=False),
        sa.Column('forex_buying', sa.Numeric(precision=12, scale=4), nullable=True),
        sa.Column('forex_selling', sa.Numeric(precision=12, scale=4), nullable=True),
        sa.Column('banknote_buying', sa.Numeric(precision=12, scale=4), nullable=True),
        sa.Column('banknote_selling', sa.Numeric(precision=12, scale=4), nullable=True),
        sa.Column('source', sa.String(length=20), server_default='tcmb', nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('date', 'currency_code', name='uq_exchange_rate_date_currency'),
    )
    op.create_index('ix_exchange_rates_currency_code', 'exchange_rates', ['currency_code'], unique=False)
    op.create_index('ix_exchange_rates_date', 'exchange_rates', ['date'], unique=False)

    # 2. Döviz modülünü kaydet (Finans altında)
    op.execute(
        "INSERT INTO modules (name, code, icon, parent_id, sort_order, is_active) "
        "VALUES ('Döviz', 'finance.doviz', 'currency-dollar', "
        "(SELECT id FROM modules WHERE code = 'finance'), 2, true)"
    )

    # 3. Admin rolüne izin ver
    op.execute(
        "INSERT INTO role_module_permissions (role_id, module_id, can_view, can_use) "
        "SELECT r.id, m.id, true, true "
        "FROM roles r, modules m "
        "WHERE r.name = 'Admin' AND m.code = 'finance.doviz'"
    )


def downgrade() -> None:
    op.execute(
        "DELETE FROM role_module_permissions WHERE module_id IN "
        "(SELECT id FROM modules WHERE code = 'finance.doviz')"
    )
    op.execute("DELETE FROM modules WHERE code = 'finance.doviz'")
    op.drop_index('ix_exchange_rates_date', table_name='exchange_rates')
    op.drop_index('ix_exchange_rates_currency_code', table_name='exchange_rates')
    op.drop_table('exchange_rates')
