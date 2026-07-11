"""Sedna Mutabakat (accounting.mutabakat) — banka↔Sedna uyuşmazlık takibi.

- bank_accounts: sedna_account_code (102.* leaf eşlemesi) + sedna_code_confirmed
- sedna_recon_runs: mutabakat koşu başlığı (pencere + sayaçlar)
- sedna_bank_recon: uyuşmazlık kayıtları (durum yaşam döngüsü; otomatik kapanma)
- RBAC: accounting.mutabakat modülü (id=921, parent=Muhasebe 249) + Admin izni

Revision ID: c7d8e9f0a1b2
Revises: b3c9d5e7f1a2
Create Date: 2026-07-11
"""
import sqlalchemy as sa
from alembic import op

revision = "c7d8e9f0a1b2"
down_revision = "b3c9d5e7f1a2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("bank_accounts", sa.Column("sedna_account_code", sa.String(30), nullable=True))
    op.add_column(
        "bank_accounts",
        sa.Column("sedna_code_confirmed", sa.Boolean(), nullable=False, server_default="false"),
    )
    op.create_unique_constraint("uq_bank_accounts_sedna_account_code", "bank_accounts", ["sedna_account_code"])

    op.create_table(
        "sedna_recon_runs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("run_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("window_start", sa.Date(), nullable=False),
        sa.Column("window_end", sa.Date(), nullable=False),
        sa.Column("triggered_by", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("accounts_scanned", sa.Integer(), server_default="0"),
        sa.Column("accounts_skipped", sa.Integer(), server_default="0"),
        sa.Column("matched_count", sa.Integer(), server_default="0"),
        sa.Column("open_count", sa.Integer(), server_default="0"),
        sa.Column("new_count", sa.Integer(), server_default="0"),
        sa.Column("auto_closed_count", sa.Integer(), server_default="0"),
        sa.Column("note", sa.String(500), nullable=True),
    )

    op.create_table(
        "sedna_bank_recon",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("bank_account_id", sa.Integer(),
                  sa.ForeignKey("bank_accounts.id", ondelete="CASCADE"), nullable=False),
        sa.Column("bank_transaction_id", sa.Integer(),
                  sa.ForeignKey("bank_transactions.id", ondelete="CASCADE"), nullable=True),
        sa.Column("sedna_trans_rec_id", sa.Integer(), nullable=True),
        sa.Column("sedna_owner_id", sa.Integer(), nullable=True),
        sa.Column("sedna_voucher", sa.String(30), nullable=True),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("amount", sa.Numeric(15, 2), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False, server_default="TRY"),
        sa.Column("event_date", sa.Date(), nullable=False),
        sa.Column("description", sa.String(500), nullable=True),
        sa.Column("sedna_description", sa.String(500), nullable=True),
        sa.Column("sedna_record_user", sa.String(50), nullable=True),
        sa.Column("sedna_change_date", sa.DateTime(timezone=True), nullable=True),
        sa.Column("detected_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("notified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("resolved_by", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("resolution", sa.String(20), nullable=True),
        sa.Column("resolution_note", sa.String(500), nullable=True),
    )
    op.create_index("ix_sedna_bank_recon_account_status", "sedna_bank_recon", ["bank_account_id", "status"])
    op.create_index("ix_sedna_bank_recon_btx", "sedna_bank_recon", ["bank_transaction_id"])
    op.create_index("ix_sedna_bank_recon_sedna_rec", "sedna_bank_recon", ["sedna_trans_rec_id"])
    op.create_index("ix_sedna_bank_recon_event_date", "sedna_bank_recon", ["event_date"])

    # RBAC modül kaydı: Muhasebe (accounting) altına Sedna Mutabakat. Admin rolüne tam izin.
    # Sabit id KULLANILMAZ — ortamlar arası id sapması var (test DB'de 921 dolu, prod'da boş);
    # kod-bazlı idempotent insert + max(id)+1. (CI'da otoriter kaynak tests/ci/02_seed.sql.)
    op.execute("""
        INSERT INTO modules (id, name, code, description, icon, parent_id, sort_order, is_active, created_at)
        SELECT (SELECT COALESCE(MAX(id), 0) + 1 FROM modules),
               'Sedna Mutabakat', 'accounting.mutabakat',
               'Banka ↔ Sedna uyuşmazlık takibi — uyuşmayan veriler, hesap eşleme',
               'scale',
               (SELECT id FROM modules WHERE code = 'accounting' ORDER BY id DESC LIMIT 1),
               8, true, now()
        WHERE NOT EXISTS (SELECT 1 FROM modules WHERE code = 'accounting.mutabakat')
    """)
    op.execute("""
        INSERT INTO role_module_permissions (role_id, module_id, can_view, can_use)
        SELECT r.id, m.id, true, true
        FROM roles r, modules m
        WHERE r.name = 'Admin' AND m.code = 'accounting.mutabakat'
        ON CONFLICT DO NOTHING
    """)


def downgrade() -> None:
    op.execute("""
        DELETE FROM role_module_permissions
        WHERE module_id IN (SELECT id FROM modules WHERE code = 'accounting.mutabakat')
    """)
    op.execute("DELETE FROM modules WHERE code = 'accounting.mutabakat'")
    op.drop_index("ix_sedna_bank_recon_event_date", table_name="sedna_bank_recon")
    op.drop_index("ix_sedna_bank_recon_sedna_rec", table_name="sedna_bank_recon")
    op.drop_index("ix_sedna_bank_recon_btx", table_name="sedna_bank_recon")
    op.drop_index("ix_sedna_bank_recon_account_status", table_name="sedna_bank_recon")
    op.drop_table("sedna_bank_recon")
    op.drop_table("sedna_recon_runs")
    op.drop_constraint("uq_bank_accounts_sedna_account_code", "bank_accounts", type_="unique")
    op.drop_column("bank_accounts", "sedna_code_confirmed")
    op.drop_column("bank_accounts", "sedna_account_code")
