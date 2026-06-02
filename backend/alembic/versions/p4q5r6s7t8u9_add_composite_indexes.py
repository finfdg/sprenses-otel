"""Performans iyileştirmesi — kompozit indeksler.

25 eş zamanlı kullanıcı analizi sonrası eklenen indeksler:
- finance_events: (event_date DESC, id DESC) — nakit akım sayfalama
- bank_transactions: (account_id, date DESC) — hesap bazlı işlem listesi
- exchange_rates: (currency_code, date DESC) — kur çekim sorgusu
- bank_statements: (account_id) — CASCADE silme performansı

Revision ID: p4q5r6s7t8u9
Revises: i8j9k0l1m2n3
Create Date: 2026-03-27
"""
from alembic import op

revision = "p4q5r6s7t8u9"
down_revision = "i8j9k0l1m2n3"
branch_labels = None
depends_on = None


def upgrade():
    # 1. finance_events: Nakit akım listesi ORDER BY event_date DESC, id DESC
    op.create_index(
        "idx_fe_date_id",
        "finance_events",
        ["event_date", "id"],
        postgresql_ops={"event_date": "DESC", "id": "DESC"},
    )

    # 2. bank_transactions: Hesap bazlı işlem listesi
    op.create_index(
        "ix_bank_tx_account_date_desc",
        "bank_transactions",
        ["account_id", "date", "id"],
        postgresql_ops={"date": "DESC", "id": "DESC"},
    )

    # 3. exchange_rates: Kur çekim sorgusu (currency_code + date DESC)
    op.create_index(
        "ix_exchange_rates_currency_date",
        "exchange_rates",
        ["currency_code", "date"],
        postgresql_ops={"date": "DESC"},
    )

    # 4. bank_statements: CASCADE silme performansı
    op.create_index(
        "ix_bank_stmt_account",
        "bank_statements",
        ["account_id"],
    )


def downgrade():
    op.drop_index("ix_bank_stmt_account", table_name="bank_statements")
    op.drop_index("ix_exchange_rates_currency_date", table_name="exchange_rates")
    op.drop_index("ix_bank_tx_account_date_desc", table_name="bank_transactions")
    op.drop_index("idx_fe_date_id", table_name="finance_events")
