"""add_checks_module

Revision ID: d2c0d2b06bd3
Revises: ee61e9f2a02e
Create Date: 2026-03-24 16:39:00.629801
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = 'd2c0d2b06bd3'
down_revision: Union[str, None] = 'ee61e9f2a02e'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # check_uploads tablosu
    op.create_table(
        'check_uploads',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('file_name', sa.String(255), nullable=False),
        sa.Column('file_url', sa.String(500), nullable=True),
        sa.Column('total_checks', sa.Integer(), server_default='0'),
        sa.Column('new_checks', sa.Integer(), server_default='0'),
        sa.Column('skipped_checks', sa.Integer(), server_default='0'),
        sa.Column('uploaded_by', sa.Integer(), sa.ForeignKey('users.id', ondelete='SET NULL'), nullable=True),
        sa.Column('uploaded_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    # checks tablosu
    #
    # NOT: bank_transaction_id / match_number / matched_vendor_id sütunları, ix_checks_bank_tx
    # indeksi ve uq_check_no_vendor_date kısıtı (check_no + vendor_code + due_date) prod'a
    # sonradan elle eklenmiş; ileri yönde bir migration ile kayıt altına alınmamıştı. Sıfırdan
    # `alembic upgrade head` ile oluşan şemanın model/prod ile bire bir eşleşmesi için bu
    # alanlar checks'in doğduğu yere (bu create_table) taşındı. Prod head'de stamp'li olduğundan
    # (bu migration tekrar çalışmaz) prod etkilenmez. Bkz. app/models/check.py
    op.create_table(
        'checks',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('upload_id', sa.Integer(), sa.ForeignKey('check_uploads.id', ondelete='CASCADE'), nullable=False),
        sa.Column('check_type', sa.String(20), nullable=True),
        sa.Column('sequence_no', sa.Integer(), nullable=True),
        sa.Column('check_no', sa.String(50), nullable=False),
        sa.Column('vendor_code', sa.String(50), nullable=True),
        sa.Column('vendor_name', sa.String(300), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('city', sa.String(50), nullable=True),
        sa.Column('due_date', sa.Date(), nullable=False),
        sa.Column('amount_tl', sa.Numeric(15, 2), nullable=False),
        sa.Column('currency', sa.String(5), server_default='TL'),
        sa.Column('amount_currency', sa.Numeric(15, 2), nullable=False),
        sa.Column('transaction_type', sa.String(50), nullable=True),
        sa.Column('status', sa.String(20), server_default='pending'),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column('bank_transaction_id', sa.Integer(), sa.ForeignKey('bank_transactions.id', ondelete='SET NULL'), nullable=True),
        sa.Column('match_number', sa.Integer(), nullable=True),
        sa.Column('matched_vendor_id', sa.Integer(), sa.ForeignKey('vendors.id', ondelete='SET NULL'), nullable=True),
        sa.UniqueConstraint('check_no', 'vendor_code', 'due_date', name='uq_check_no_vendor_date'),
        sa.Index('ix_checks_due_date', 'due_date'),
        sa.Index('ix_checks_vendor_code', 'vendor_code'),
        sa.Index('ix_checks_bank_tx', 'bank_transaction_id'),
    )

    # finance.checks modülünü ekle
    op.execute("""
        INSERT INTO modules (name, code, description, icon, parent_id, sort_order, is_active)
        SELECT 'Verilen Çekler', 'finance.checks', 'Verilen çek takibi', 'DocumentCheckIcon',
               id, 5, true
        FROM modules WHERE code = 'finance'
    """)

    # Admin rolüne izin ver
    op.execute("""
        INSERT INTO role_module_permissions (role_id, module_id, can_view, can_use)
        SELECT rmp.role_id, m.id, true, true
        FROM modules m, role_module_permissions rmp
        JOIN modules pm ON rmp.module_id = pm.id AND pm.code = 'finance.cash_flow'
        WHERE m.code = 'finance.checks'
        ON CONFLICT DO NOTHING
    """)


def downgrade() -> None:
    op.execute("DELETE FROM role_module_permissions WHERE module_id IN (SELECT id FROM modules WHERE code = 'finance.checks')")
    op.execute("DELETE FROM modules WHERE code = 'finance.checks'")
    op.drop_table('checks')
    op.drop_table('check_uploads')
