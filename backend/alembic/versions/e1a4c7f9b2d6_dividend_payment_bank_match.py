"""dividend_payments.bank_transaction_id — temettü ödemesi ↔ banka eşleştirme

Bir temettü ödemesi (pay sahibi × taksit net'i) hangi banka hareketiyle ödendiyse buraya
bağlanır. Doluysa net finance_event'i is_matched=True olur → nakit akımda gizlenir (banka bacağı
gerçek çıkışı temsil eder; çift sayım engellenir; çek/kredi deseniyle aynı).

ELLE yazıldı (additive + nullable).

Revision ID: e1a4c7f9b2d6
Revises: 237c01701a06
Create Date: 2026-07-05
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "e1a4c7f9b2d6"
down_revision: Union[str, None] = "237c01701a06"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "dividend_payments",
        sa.Column("bank_transaction_id", sa.Integer(), nullable=True),
    )
    op.create_foreign_key(
        "fk_dividend_payments_bank_tx", "dividend_payments", "bank_transactions",
        ["bank_transaction_id"], ["id"], ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint("fk_dividend_payments_bank_tx", "dividend_payments", type_="foreignkey")
    op.drop_column("dividend_payments", "bank_transaction_id")
