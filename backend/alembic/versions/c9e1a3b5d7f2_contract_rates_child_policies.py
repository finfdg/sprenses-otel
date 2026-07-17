"""Kontrat fiyat matrisi + çocuk politikası tabloları (Faz 4a).

contract_rates: 4 fiyat arketipini taşır (base_price=PP/PU baz, multiplier=doluluk
çarpanı, fixed_total=kombinasyon-toplam satırı). Veri girişi Faz 4b'de (taranmış
rate listlerden — data_confidence disipliniyle).

Revision ID: c9e1a3b5d7f2
Revises: b7d2f4a8c1e6
Create Date: 2026-07-17
"""
import sqlalchemy as sa
from alembic import op

revision = "c9e1a3b5d7f2"
down_revision = "b7d2f4a8c1e6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "contract_rates",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("contract_id", sa.Integer(),
                  sa.ForeignKey("agency_contracts.id", ondelete="CASCADE"), nullable=False),
        sa.Column("period_id", sa.Integer(),
                  sa.ForeignKey("contract_periods.id", ondelete="CASCADE"), nullable=True),
        sa.Column("contract_room_type_id", sa.Integer(),
                  sa.ForeignKey("contract_room_types.id", ondelete="CASCADE"), nullable=True),
        sa.Column("board", sa.String(10), nullable=False, server_default="AI"),
        sa.Column("occupancy_code", sa.String(30), nullable=True),
        sa.Column("price_type", sa.String(20), nullable=False, server_default="per_person_night"),
        sa.Column("base_price", sa.Numeric(12, 2), nullable=True),
        sa.Column("multiplier", sa.Numeric(6, 3), nullable=True),
        sa.Column("fixed_total", sa.Numeric(12, 2), nullable=True),
        sa.Column("min_payer", sa.Integer(), nullable=True),
        sa.Column("market_scope", sa.String(100), nullable=True),
        sa.Column("data_confidence", sa.String(30), nullable=False, server_default="verified"),
        sa.Column("notes", sa.String(300), nullable=True),
    )
    op.create_index("ix_contract_rates_contract", "contract_rates", ["contract_id"])
    op.create_index("ix_contract_rates_period", "contract_rates", ["period_id"])

    op.create_table(
        "contract_child_policies",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("contract_id", sa.Integer(),
                  sa.ForeignKey("agency_contracts.id", ondelete="CASCADE"), nullable=False),
        sa.Column("contract_room_type_id", sa.Integer(),
                  sa.ForeignKey("contract_room_types.id", ondelete="SET NULL"), nullable=True),
        sa.Column("child_order", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("age_min", sa.Numeric(4, 2), nullable=True),
        sa.Column("age_max", sa.Numeric(4, 2), nullable=True),
        sa.Column("discount_percent", sa.Numeric(6, 2), nullable=True),
        sa.Column("fixed_price", sa.Numeric(12, 2), nullable=True),
        sa.Column("period_scope", sa.String(100), nullable=True),
        sa.Column("data_confidence", sa.String(30), nullable=False, server_default="verified"),
        sa.Column("notes", sa.String(300), nullable=True),
    )
    op.create_index("ix_contract_child_policies_contract",
                    "contract_child_policies", ["contract_id"])


def downgrade() -> None:
    op.drop_table("contract_child_policies")
    op.drop_table("contract_rates")
