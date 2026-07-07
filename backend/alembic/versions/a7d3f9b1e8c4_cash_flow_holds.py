"""cash_flow_holds tablosu — bekleyen nakit akım kaleminin beklemeye alınma durumu

Revision ID: a7d3f9b1e8c4
Revises: f2b8d1a5c9e3
Create Date: 2026-07-07

Panel Nakit Akım kartında bir bekleyen hareket "beklemeye alınınca" burada saklanır (ortak).
Nakit akım hesapları future-pending held kalemleri dışlar; ayrı Bekleme Listesi'nde gösterir.
Öteleme (payment_deferrals) deseniyle aynı: doğal anahtar source_type+source_id.
"""
import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision = "a7d3f9b1e8c4"
down_revision = "f2b8d1a5c9e3"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "cash_flow_holds",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("source_type", sa.String(length=30), nullable=False),
        sa.Column("source_id", sa.BigInteger(), nullable=False),
        sa.Column("created_by", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("source_type", "source_id", name="uq_cash_flow_holds_source"),
    )
    op.create_index("idx_cash_flow_holds_source", "cash_flow_holds", ["source_type", "source_id"])


def downgrade() -> None:
    op.drop_index("idx_cash_flow_holds_source", table_name="cash_flow_holds")
    op.drop_table("cash_flow_holds")
