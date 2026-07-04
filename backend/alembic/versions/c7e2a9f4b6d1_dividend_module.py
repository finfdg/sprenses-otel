"""Kâr payı dağıtımı (temettü) modülü — 4 tablo + eski jenerik dividend verisi temizliği

Temettü, jenerik "planlı ödeme" fabrikasından (scheduled_definitions/entries) bespoke bir
kâr payı dağıtım modülüne taşındı. 4 yeni tablo (dağıtım → pay sahipleri + taksitler + ödemeler).

ÇAKIŞMA TEMİZLİĞİ (ZORUNLU): finance_events(source_type, source_id) UNIQUE'tir. Yeni modül
'dividend' kaynağını dividend_installments.id ile anahtarlar; eski fabrika modülü aynı 'dividend'
kaynağını scheduled_entries.id ile anahtarlıyordu → örtüşen id'lerde ON CONFLICT yanlış satırı
ezerdi. Bu yüzden eski source_type='dividend' kayıtları finance_events + scheduled_entries +
scheduled_definitions'tan SİLİNİR. Gate YOK — yarı-temizlik çakışan UNIQUE anahtar bırakır.
Bu geri alınamaz (downgrade eski jenerik veriyi geri getirmez).

Modül 258 (accounting.dividend, parent 249) zaten seed'li/prod'da — INSERT edilmez.

ELLE yazıldı (autogenerate yanlış DROP üretebilir).

Revision ID: c7e2a9f4b6d1
Revises: a6fb877d2af1
Create Date: 2026-07-04
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "c7e2a9f4b6d1"
down_revision: Union[str, None] = "a6fb877d2af1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "dividend_distributions",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("decision_date", sa.Date(), nullable=True),
        sa.Column("total_gross", sa.Numeric(15, 2), nullable=False, server_default="0"),
        sa.Column("capital", sa.Numeric(15, 2), nullable=True),
        sa.Column("withholding_rate", sa.Numeric(6, 4), nullable=False, server_default="0.15"),
        sa.Column("installment_count", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("year", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="active"),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_by", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_dividend_distributions_year", "dividend_distributions", ["year"])
    op.create_index("ix_dividend_distributions_status", "dividend_distributions", ["status"])

    op.create_table(
        "dividend_shareholders",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("distribution_id", sa.Integer(), sa.ForeignKey("dividend_distributions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("share_value", sa.Numeric(15, 2), nullable=False, server_default="0"),
        sa.Column("share_ratio", sa.Numeric(9, 6), nullable=False, server_default="0"),
        sa.Column("gross_dividend", sa.Numeric(15, 2), nullable=False, server_default="0"),
        sa.Column("stopaj_amount", sa.Numeric(15, 2), nullable=False, server_default="0"),
        sa.Column("net_dividend", sa.Numeric(15, 2), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_dividend_shareholders_dist", "dividend_shareholders", ["distribution_id"])

    op.create_table(
        "dividend_installments",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("distribution_id", sa.Integer(), sa.ForeignKey("dividend_distributions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("installment_no", sa.Integer(), nullable=False),
        sa.Column("due_date", sa.Date(), nullable=False),
        sa.Column("label", sa.String(50), nullable=True),
        sa.Column("gross_amount", sa.Numeric(15, 2), nullable=False, server_default="0"),
        sa.Column("stopaj_amount", sa.Numeric(15, 2), nullable=False, server_default="0"),
        sa.Column("net_amount", sa.Numeric(15, 2), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_dividend_installments_dist", "dividend_installments", ["distribution_id"])
    op.create_index("ix_dividend_installments_due", "dividend_installments", ["due_date"])

    op.create_table(
        "dividend_payments",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("distribution_id", sa.Integer(), sa.ForeignKey("dividend_distributions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("installment_id", sa.Integer(), sa.ForeignKey("dividend_installments.id", ondelete="CASCADE"), nullable=False),
        sa.Column("shareholder_id", sa.Integer(), sa.ForeignKey("dividend_shareholders.id", ondelete="CASCADE"), nullable=False),
        sa.Column("gross_amount", sa.Numeric(15, 2), nullable=False, server_default="0"),
        sa.Column("stopaj_amount", sa.Numeric(15, 2), nullable=False, server_default="0"),
        sa.Column("net_amount", sa.Numeric(15, 2), nullable=False, server_default="0"),
        sa.Column("is_paid", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("paid_date", sa.Date(), nullable=True),
        sa.Column("stopaj_paid", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("stopaj_paid_date", sa.Date(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_dividend_payments_dist", "dividend_payments", ["distribution_id"])
    op.create_index("ix_dividend_payments_installment", "dividend_payments", ["installment_id"])
    op.create_index("ix_dividend_payments_shareholder", "dividend_payments", ["shareholder_id"])
    op.create_index("ix_dividend_payments_installment_paid", "dividend_payments", ["installment_id", "is_paid"])

    # ── Eski jenerik dividend verisini temizle (çakışma düzeltmesi — ZORUNLU, gate'siz) ──
    op.execute("DELETE FROM finance_events WHERE source_type = 'dividend'")
    op.execute("DELETE FROM scheduled_entries WHERE source_type = 'dividend'")
    op.execute("DELETE FROM scheduled_definitions WHERE source_type = 'dividend'")


def downgrade() -> None:
    # NOT: eski jenerik dividend verisi geri getirilmez (temizlik geri alınamaz).
    op.drop_table("dividend_payments")
    op.drop_table("dividend_installments")
    op.drop_table("dividend_shareholders")
    op.drop_table("dividend_distributions")
