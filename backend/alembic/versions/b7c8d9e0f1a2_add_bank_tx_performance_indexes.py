"""Add performance indexes for bank_transactions

bank_transactions tablosuna eksik indeksler eklendi:
- type: income/expense filtrelemesi
- category_id: kategori bazlı sorgular
- match_number: eşleştirme sorguları

finance_events ve vendor_transactions tablolarında istenen indeksler
zaten mevcut (idx_fe_source, idx_fe_date, idx_fe_matched,
ix_vendor_tx_vendor, ix_vendor_tx_payment_due).

Revision ID: b7c8d9e0f1a2
Revises: 6a5525e8960a
Create Date: 2026-04-12
"""
from typing import Sequence, Union

from alembic import op

revision: str = "b7c8d9e0f1a2"
down_revision: Union[str, None] = "6a5525e8960a"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # bank_transactions.type — income/expense filtrelemesi
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_bank_tx_type
        ON bank_transactions (type)
    """)

    # NOT: ix_bank_tx_category, d4b2e9f01a23 (transaction_tagging) migration'ında
    # oluşturulur ve orada düşürülür. Buradaki tekrar (IF NOT EXISTS) artık no-op olduğu
    # için kaldırıldı; aksi halde downgrade'de çift drop (UndefinedObject) hatası oluyordu.

    # bank_transactions.match_number — eşleştirme sorguları
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_bank_tx_match_number
        ON bank_transactions (match_number)
    """)


def downgrade() -> None:
    op.drop_index("ix_bank_tx_match_number", table_name="bank_transactions")
    # ix_bank_tx_category d4b2e9f01a23 tarafından yönetilir; burada düşürülmez (çift drop önlenir)
    op.drop_index("ix_bank_tx_type", table_name="bank_transactions")
