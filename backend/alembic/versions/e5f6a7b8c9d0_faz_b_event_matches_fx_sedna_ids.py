"""Faz B — kalıcı eşleşme izi + kur farkı + Sedna kimlikleri + entity uyuşmazlıkları.

- event_matches: eşleşme kaydı (Sedna AccountingMatch deseni; match_number'ın üst modeli)
- fx_differences: çapraz-para kur farkı + aylık değerleme kayıtları (646/656 eşleniği)
- sedna_bank_recon: entity_type/entity_id (eşleşmiş çek/cari Sedna sapmaları) +
  bank_account_id NULL'a açılır (entity kayıtlarında hesap yok)
- vendor_transactions / checks / sales_invoices / sales_collections: kalıcı Sedna RecId

Revision ID: e5f6a7b8c9d0
Revises: c7d8e9f0a1b2
Create Date: 2026-07-11
"""
import sqlalchemy as sa
from alembic import op

revision = "e5f6a7b8c9d0"
down_revision = "c7d8e9f0a1b2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "event_matches",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("match_number", sa.Integer(), nullable=True),
        sa.Column("bank_source_type", sa.String(30), nullable=False),
        sa.Column("bank_source_id", sa.Integer(), nullable=False),
        sa.Column("target_source_type", sa.String(30), nullable=False),
        sa.Column("target_source_id", sa.Integer(), nullable=False),
        sa.Column("amount", sa.Numeric(15, 2), nullable=True),
        sa.Column("currency", sa.String(3), nullable=True),
        sa.Column("rate_used", sa.Numeric(12, 6), nullable=True),
        sa.Column("method", sa.String(12), nullable=False, server_default="auto"),
        sa.Column("score", sa.Integer(), nullable=True),
        sa.Column("created_by", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_event_matches_bank", "event_matches", ["bank_source_type", "bank_source_id"])
    op.create_index("ix_event_matches_target", "event_matches", ["target_source_type", "target_source_id"])

    op.create_table(
        "fx_differences",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("event_match_id", sa.Integer(),
                  sa.ForeignKey("event_matches.id", ondelete="CASCADE"), nullable=True),
        sa.Column("period", sa.Date(), nullable=False),
        sa.Column("amount_try", sa.Numeric(15, 2), nullable=False),
        sa.Column("rate_estimate", sa.Numeric(12, 6), nullable=True),
        sa.Column("rate_realized", sa.Numeric(12, 6), nullable=True),
        sa.Column("expected_try", sa.Numeric(15, 2), nullable=True),
        sa.Column("realized_try", sa.Numeric(15, 2), nullable=True),
        sa.Column("source", sa.String(12), nullable=False, server_default="match"),
        sa.Column("description", sa.String(300), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_fx_differences_period", "fx_differences", ["period"])

    op.add_column("sedna_bank_recon", sa.Column("entity_type", sa.String(20), nullable=True))
    op.add_column("sedna_bank_recon", sa.Column("entity_id", sa.Integer(), nullable=True))
    op.create_index("ix_sedna_bank_recon_entity", "sedna_bank_recon", ["entity_type", "entity_id"])
    op.alter_column("sedna_bank_recon", "bank_account_id", nullable=True)

    op.add_column("vendor_transactions", sa.Column("sedna_rec_id", sa.Integer(), nullable=True))
    op.create_index("ix_vendor_transactions_sedna_rec_id", "vendor_transactions", ["sedna_rec_id"],
                    unique=True, postgresql_where=sa.text("sedna_rec_id IS NOT NULL"))
    op.add_column("checks", sa.Column("sedna_check_rec_id", sa.Integer(), nullable=True))
    op.create_index("ix_checks_sedna_check_rec_id", "checks", ["sedna_check_rec_id"],
                    unique=True, postgresql_where=sa.text("sedna_check_rec_id IS NOT NULL"))
    op.add_column("sales_invoices", sa.Column("sedna_rec_id", sa.Integer(), nullable=True))
    op.create_index("ix_sales_invoices_sedna_rec_id", "sales_invoices", ["sedna_rec_id"],
                    unique=True, postgresql_where=sa.text("sedna_rec_id IS NOT NULL"))
    op.add_column("sales_collections", sa.Column("sedna_rec_id", sa.Integer(), nullable=True))
    op.create_index("ix_sales_collections_sedna_rec_id", "sales_collections", ["sedna_rec_id"],
                    unique=True, postgresql_where=sa.text("sedna_rec_id IS NOT NULL"))


def downgrade() -> None:
    op.drop_index("ix_sales_collections_sedna_rec_id", table_name="sales_collections")
    op.drop_column("sales_collections", "sedna_rec_id")
    op.drop_index("ix_sales_invoices_sedna_rec_id", table_name="sales_invoices")
    op.drop_column("sales_invoices", "sedna_rec_id")
    op.drop_index("ix_checks_sedna_check_rec_id", table_name="checks")
    op.drop_column("checks", "sedna_check_rec_id")
    op.drop_index("ix_vendor_transactions_sedna_rec_id", table_name="vendor_transactions")
    op.drop_column("vendor_transactions", "sedna_rec_id")
    op.alter_column("sedna_bank_recon", "bank_account_id", nullable=False)
    op.drop_index("ix_sedna_bank_recon_entity", table_name="sedna_bank_recon")
    op.drop_column("sedna_bank_recon", "entity_id")
    op.drop_column("sedna_bank_recon", "entity_type")
    op.drop_index("ix_fx_differences_period", table_name="fx_differences")
    op.drop_table("fx_differences")
    op.drop_index("ix_event_matches_target", table_name="event_matches")
    op.drop_index("ix_event_matches_bank", table_name="event_matches")
    op.drop_table("event_matches")
