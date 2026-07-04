"""payment_deferrals table — kalıcı öteleme (herhangi ödeme türünün ertelenmiş tarihi)

Bir ödeme kalemi (cari ödeme, çek, kredi taksiti, KK ekstresi, planlı gider/gelir)
ileri bir tarihe ötelenince tercih burada KALICI saklanır. finance_event_service._upsert
her FinanceEvent yazımında burayı sorgular → Sedna sync / FIFO yeniden yazımı ötelemeyi
korur. Tek tablo, tüm türler (source_type + source_id doğal anahtar). "bank" HARİÇ.

ELLE yazıldı (autogenerate yanlış DROP üretebilir) — yalnız bu tabloyu ekler.

Revision ID: a6fb877d2af1
Revises: a7d3e9f2c5b8
Create Date: 2026-07-04
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "a6fb877d2af1"
down_revision: Union[str, None] = "a7d3e9f2c5b8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "payment_deferrals",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("source_type", sa.String(30), nullable=False),
        sa.Column("source_id", sa.BigInteger(), nullable=False),
        sa.Column("deferred_to", sa.Date(), nullable=False),
        sa.Column(
            "created_by", sa.Integer(),
            sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True,
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True),
            server_default=sa.func.now(), nullable=False,
        ),
        sa.Column("note", sa.Text(), nullable=True),
        sa.UniqueConstraint("source_type", "source_id", name="uq_payment_deferrals_source"),
    )
    op.create_index(
        "idx_payment_deferrals_source", "payment_deferrals",
        ["source_type", "source_id"],
    )


def downgrade() -> None:
    op.drop_index("idx_payment_deferrals_source", table_name="payment_deferrals")
    op.drop_table("payment_deferrals")
