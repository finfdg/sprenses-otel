"""add_banks_module

Revision ID: 2b4495d4c8f5
Revises: b6a51d72e1ce
Create Date: 2026-03-09 12:22:49.845164
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = '2b4495d4c8f5'
down_revision: Union[str, None] = 'b6a51d72e1ce'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Tablolar
    op.create_table('bank_accounts',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('bank_name', sa.String(length=100), nullable=False),
        sa.Column('branch_name', sa.String(length=200), nullable=True),
        sa.Column('account_no', sa.String(length=50), nullable=True),
        sa.Column('iban', sa.String(length=34), nullable=False),
        sa.Column('currency', sa.String(length=3), server_default='TRY', nullable=False),
        sa.Column('holder_name', sa.String(length=300), nullable=True),
        sa.Column('is_active', sa.Boolean(), server_default='true', nullable=False),
        sa.Column('created_by', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['created_by'], ['users.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('iban'),
    )
    op.create_table('bank_statements',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('account_id', sa.Integer(), nullable=False),
        sa.Column('file_name', sa.String(length=255), nullable=False),
        sa.Column('file_url', sa.String(length=500), nullable=False),
        sa.Column('file_type', sa.String(length=10), nullable=False),
        sa.Column('period_start', sa.Date(), nullable=True),
        sa.Column('period_end', sa.Date(), nullable=True),
        sa.Column('total_transactions', sa.Integer(), server_default='0', nullable=False),
        sa.Column('new_transactions', sa.Integer(), server_default='0', nullable=False),
        sa.Column('skipped_transactions', sa.Integer(), server_default='0', nullable=False),
        sa.Column('uploaded_by', sa.Integer(), nullable=True),
        sa.Column('uploaded_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['account_id'], ['bank_accounts.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['uploaded_by'], ['users.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_table('bank_transactions',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('account_id', sa.Integer(), nullable=False),
        sa.Column('statement_id', sa.Integer(), nullable=True),
        sa.Column('date', sa.Date(), nullable=False),
        sa.Column('receipt_no', sa.String(length=50), nullable=True),
        sa.Column('description', sa.Text(), nullable=False),
        sa.Column('amount', sa.Numeric(precision=15, scale=2), nullable=False),
        sa.Column('balance', sa.Numeric(precision=15, scale=2), nullable=True),
        sa.Column('type', sa.String(length=10), nullable=False),
        sa.Column('tx_hash', sa.String(length=64), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['account_id'], ['bank_accounts.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['statement_id'], ['bank_statements.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('account_id', 'tx_hash', name='uq_bank_tx_account_hash'),
    )
    op.create_index('ix_bank_tx_account', 'bank_transactions', ['account_id'], unique=False)
    op.create_index('ix_bank_tx_date', 'bank_transactions', ['date'], unique=False)

    # 2. Bankalar alt modülü (finance altına)
    op.execute(
        "INSERT INTO modules (name, code, icon, parent_id, sort_order, is_active) "
        "VALUES ('Bankalar', 'finance.banks', 'building-library', "
        "(SELECT id FROM modules WHERE code = 'finance'), 1, true)"
    )

    # 3. Admin rolüne izin ver
    op.execute(
        "INSERT INTO role_module_permissions (role_id, module_id, can_view, can_use) "
        "SELECT r.id, m.id, true, true "
        "FROM roles r, modules m "
        "WHERE r.name = 'Admin' AND m.code = 'finance.banks'"
    )

    # 4. Varsayılan Ziraat hesapları
    op.execute(
        "INSERT INTO bank_accounts (bank_name, iban, currency, created_by) VALUES "
        "('Ziraat Bankası', 'TR530001001977594481885009', 'TRY', "
        "(SELECT id FROM users WHERE username = 'admin' LIMIT 1)), "
        "('Ziraat Bankası', 'TR800001001977594481885008', 'EUR', "
        "(SELECT id FROM users WHERE username = 'admin' LIMIT 1))"
    )


def downgrade() -> None:
    op.execute("DELETE FROM bank_transactions")
    op.execute("DELETE FROM bank_statements")
    op.execute("DELETE FROM bank_accounts")
    op.execute(
        "DELETE FROM role_module_permissions WHERE module_id IN "
        "(SELECT id FROM modules WHERE code = 'finance.banks')"
    )
    op.execute("DELETE FROM modules WHERE code = 'finance.banks'")
    op.drop_index('ix_bank_tx_date', table_name='bank_transactions')
    op.drop_index('ix_bank_tx_account', table_name='bank_transactions')
    op.drop_table('bank_transactions')
    op.drop_table('bank_statements')
    op.drop_table('bank_accounts')
