"""Kontrat modülü (sales.kontratlar) — 10 tablo + RBAC modül kaydı.

Faz 1 (2026-07-17): agency_contracts + contract_documents/periods/room_types/
payment_plans/installments/actions/action_tiers/allotments/deductions.
Tasarım: 16 operatör kontrat analizi (kontrat-entegrasyon raporu).

Revision ID: b7d2f4a8c1e6
Revises: a1c4e7f9b2d5
Create Date: 2026-07-17
"""
import sqlalchemy as sa
from alembic import op

revision = "b7d2f4a8c1e6"
down_revision = "a1c4e7f9b2d5"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "agency_contracts",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("agency_group_id", sa.Integer(),
                  sa.ForeignKey("agency_groups.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("code", sa.String(50), nullable=False, unique=True),
        sa.Column("title", sa.String(200), nullable=True),
        sa.Column("legal_counterparty", sa.String(300), nullable=True),
        sa.Column("signed_date", sa.Date(), nullable=True),
        sa.Column("season_code", sa.String(20), nullable=False),
        sa.Column("valid_from", sa.Date(), nullable=True),
        sa.Column("valid_to", sa.Date(), nullable=True),
        sa.Column("currency", sa.String(5), nullable=False, server_default="EUR"),
        sa.Column("fx_rule", sa.String(40), nullable=True),
        sa.Column("fx_fixed_rate", sa.Numeric(10, 4), nullable=True),
        sa.Column("pricing_model", sa.String(30), nullable=True),
        sa.Column("board_default", sa.String(10), nullable=False, server_default="AI"),
        sa.Column("min_stay_default", sa.Integer(), nullable=True),
        sa.Column("release_days_default", sa.Integer(), nullable=True),
        sa.Column("invoice_due_basis", sa.String(40), nullable=True),
        sa.Column("invoice_due_days", sa.Integer(), nullable=True),
        sa.Column("markets", sa.JSON(), nullable=True),
        sa.Column("exclusive_markets", sa.JSON(), nullable=True),
        sa.Column("closed_markets", sa.JSON(), nullable=True),
        sa.Column("status", sa.String(20), nullable=False, server_default="active"),
        sa.Column("supersedes_contract_id", sa.Integer(),
                  sa.ForeignKey("agency_contracts.id", ondelete="SET NULL"), nullable=True),
        sa.Column("sedna_contrack_ids", sa.JSON(), nullable=True),
        sa.Column("data_confidence", sa.String(30), nullable=False, server_default="verified"),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_agency_contracts_group", "agency_contracts", ["agency_group_id"])
    op.create_index("ix_agency_contracts_season", "agency_contracts", ["season_code"])

    op.create_table(
        "contract_documents",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("agency_group_id", sa.Integer(),
                  sa.ForeignKey("agency_groups.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("contract_id", sa.Integer(),
                  sa.ForeignKey("agency_contracts.id", ondelete="SET NULL"), nullable=True),
        sa.Column("doc_type", sa.String(20), nullable=False, server_default="other"),
        sa.Column("file_path", sa.String(500), nullable=False),
        sa.Column("original_name", sa.String(255), nullable=False),
        sa.Column("doc_date", sa.Date(), nullable=True),
        sa.Column("uploaded_by", sa.Integer(),
                  sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("notes", sa.String(500), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_contract_documents_contract", "contract_documents", ["contract_id"])

    op.create_table(
        "contract_periods",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("contract_id", sa.Integer(),
                  sa.ForeignKey("agency_contracts.id", ondelete="CASCADE"), nullable=False),
        sa.Column("code", sa.String(10), nullable=False),
        sa.Column("date_start", sa.Date(), nullable=False),
        sa.Column("date_end", sa.Date(), nullable=False),
        sa.Column("release_days", sa.Integer(), nullable=True),
        sa.Column("min_stay", sa.Integer(), nullable=True),
    )
    op.create_index("ix_contract_periods_contract", "contract_periods", ["contract_id"])

    op.create_table(
        "contract_room_types",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("contract_id", sa.Integer(),
                  sa.ForeignKey("agency_contracts.id", ondelete="CASCADE"), nullable=False),
        sa.Column("contract_code", sa.String(40), nullable=False),
        sa.Column("contract_name", sa.String(120), nullable=True),
        sa.Column("room_type_id", sa.Integer(),
                  sa.ForeignKey("room_types.id", ondelete="SET NULL"), nullable=True),
        sa.Column("pricing_basis", sa.String(10), nullable=True),
        sa.Column("occupancy_min", sa.Integer(), nullable=True),
        sa.Column("occupancy_max", sa.Integer(), nullable=True),
        sa.Column("max_adults", sa.Integer(), nullable=True),
    )
    op.create_index("ix_contract_room_types_contract", "contract_room_types", ["contract_id"])

    op.create_table(
        "contract_payment_plans",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("contract_id", sa.Integer(),
                  sa.ForeignKey("agency_contracts.id", ondelete="CASCADE"), nullable=False),
        sa.Column("plan_type", sa.String(30), nullable=False),
        sa.Column("description", sa.String(300), nullable=True),
        sa.Column("total_amount", sa.Numeric(14, 2), nullable=True),
        sa.Column("currency", sa.String(5), nullable=False, server_default="EUR"),
        sa.Column("offset_rule", sa.String(30), nullable=True),
        sa.Column("carryover_rule", sa.String(300), nullable=True),
        sa.Column("late_interest", sa.String(150), nullable=True),
        sa.Column("data_confidence", sa.String(30), nullable=False, server_default="verified"),
        sa.Column("notes", sa.String(500), nullable=True),
    )
    op.create_index("ix_contract_payment_plans_contract", "contract_payment_plans", ["contract_id"])

    op.create_table(
        "contract_actions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("contract_id", sa.Integer(),
                  sa.ForeignKey("agency_contracts.id", ondelete="CASCADE"), nullable=False),
        sa.Column("action_type", sa.String(30), nullable=False),
        sa.Column("title", sa.String(200), nullable=True),
        sa.Column("sales_start", sa.Date(), nullable=True),
        sa.Column("sales_end", sa.Date(), nullable=True),
        sa.Column("open_ended", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("basis", sa.String(15), nullable=True),
        sa.Column("combinable", sa.String(20), nullable=True),
        sa.Column("market_scope", sa.JSON(), nullable=True),
        sa.Column("room_scope", sa.JSON(), nullable=True),
        sa.Column("supersedes_action_id", sa.Integer(),
                  sa.ForeignKey("contract_actions.id", ondelete="SET NULL"), nullable=True),
        sa.Column("source_document_id", sa.Integer(),
                  sa.ForeignKey("contract_documents.id", ondelete="SET NULL"), nullable=True),
        sa.Column("status", sa.String(20), nullable=False, server_default="confirmed"),
        sa.Column("data_confidence", sa.String(30), nullable=False, server_default="verified"),
        sa.Column("notes", sa.String(500), nullable=True),
    )
    op.create_index("ix_contract_actions_contract", "contract_actions", ["contract_id"])

    op.create_table(
        "contract_action_tiers",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("action_id", sa.Integer(),
                  sa.ForeignKey("contract_actions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("stay_start", sa.Date(), nullable=True),
        sa.Column("stay_end", sa.Date(), nullable=True),
        sa.Column("discount_percent", sa.Numeric(6, 2), nullable=True),
        sa.Column("fixed_net_price", sa.Numeric(12, 2), nullable=True),
        sa.Column("room_scope", sa.JSON(), nullable=True),
        sa.Column("note", sa.String(200), nullable=True),
    )
    op.create_index("ix_contract_action_tiers_action", "contract_action_tiers", ["action_id"])

    op.create_table(
        "contract_installments",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("plan_id", sa.Integer(),
                  sa.ForeignKey("contract_payment_plans.id", ondelete="CASCADE"), nullable=False),
        sa.Column("due_date", sa.Date(), nullable=True),
        sa.Column("due_event", sa.String(30), nullable=True),
        sa.Column("offset_days", sa.Integer(), nullable=True),
        sa.Column("amount", sa.Numeric(14, 2), nullable=True),
        sa.Column("percent", sa.Numeric(6, 2), nullable=True),
        sa.Column("percent_basis", sa.String(30), nullable=True),
        sa.Column("currency", sa.String(5), nullable=False, server_default="EUR"),
        sa.Column("status", sa.String(20), nullable=False, server_default="pending"),
        sa.Column("paid_date", sa.Date(), nullable=True),
        sa.Column("bank_transaction_id", sa.Integer(),
                  sa.ForeignKey("bank_transactions.id", ondelete="SET NULL"), nullable=True),
        sa.Column("is_conditional", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("condition_note", sa.String(300), nullable=True),
        sa.Column("linked_action_id", sa.Integer(),
                  sa.ForeignKey("contract_actions.id", ondelete="SET NULL"), nullable=True),
        sa.Column("supersedes_installment_id", sa.Integer(),
                  sa.ForeignKey("contract_installments.id", ondelete="SET NULL"), nullable=True),
        sa.Column("data_confidence", sa.String(30), nullable=False, server_default="verified"),
        sa.Column("notes", sa.String(300), nullable=True),
    )
    op.create_index("ix_contract_installments_plan", "contract_installments", ["plan_id"])
    op.create_index("ix_contract_installments_due", "contract_installments", ["due_date"])
    op.create_index("ix_contract_installments_status", "contract_installments", ["status"])

    op.create_table(
        "contract_allotments",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("contract_id", sa.Integer(),
                  sa.ForeignKey("agency_contracts.id", ondelete="CASCADE"), nullable=False),
        sa.Column("contract_room_type_id", sa.Integer(),
                  sa.ForeignKey("contract_room_types.id", ondelete="SET NULL"), nullable=True),
        sa.Column("room_count", sa.Integer(), nullable=False),
        sa.Column("date_start", sa.Date(), nullable=True),
        sa.Column("date_end", sa.Date(), nullable=True),
        sa.Column("allotment_type", sa.String(20), nullable=False, server_default="allot"),
        sa.Column("guaranteed_share_percent", sa.Numeric(5, 2), nullable=True),
        sa.Column("notes", sa.String(300), nullable=True),
    )
    op.create_index("ix_contract_allotments_contract", "contract_allotments", ["contract_id"])

    op.create_table(
        "contract_deductions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("contract_id", sa.Integer(),
                  sa.ForeignKey("agency_contracts.id", ondelete="CASCADE"), nullable=False),
        sa.Column("deduction_type", sa.String(40), nullable=False),
        sa.Column("percent", sa.Numeric(6, 2), nullable=True),
        sa.Column("fixed_amount", sa.Numeric(14, 2), nullable=True),
        sa.Column("currency", sa.String(5), nullable=True),
        sa.Column("applies", sa.String(20), nullable=False, server_default="per_invoice"),
        sa.Column("tier_from", sa.Numeric(14, 2), nullable=True),
        sa.Column("tier_to", sa.Numeric(14, 2), nullable=True),
        sa.Column("settlement_month", sa.Integer(), nullable=True),
        sa.Column("cumulative_with_kb", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("notes", sa.String(300), nullable=True),
    )
    op.create_index("ix_contract_deductions_contract", "contract_deductions", ["contract_id"])

    # RBAC: Satış (id=896) altına Kontratlar modülü. Admin'e tam izin.
    # (id=925 — mevcut max 921; çakışmaz. Diğer roller Roller sayfasından.)
    op.execute("""
        INSERT INTO modules (id, name, code, description, icon, parent_id, sort_order, is_active, created_at)
        VALUES (925, 'Kontratlar', 'sales.kontratlar',
                'Acente kontrat arşivi — sezon, ödeme planı, aksiyon/SPO, kontenjan, kesinti',
                'file-text', 896, 5, true, now())
        ON CONFLICT (id) DO NOTHING
    """)
    op.execute("""
        INSERT INTO role_module_permissions (role_id, module_id, can_view, can_use)
        SELECT r.id, 925, true, true FROM roles r WHERE r.name = 'Admin'
        ON CONFLICT DO NOTHING
    """)


def downgrade() -> None:
    op.execute("DELETE FROM role_module_permissions WHERE module_id = 925")
    op.execute("DELETE FROM modules WHERE id = 925")
    for t in ("contract_deductions", "contract_allotments", "contract_installments",
              "contract_action_tiers", "contract_actions", "contract_payment_plans",
              "contract_room_types", "contract_periods", "contract_documents",
              "agency_contracts"):
        op.drop_table(t)
