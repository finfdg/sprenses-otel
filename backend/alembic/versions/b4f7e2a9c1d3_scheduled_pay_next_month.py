"""scheduled_definitions.pay_next_month kolonu

Tanım-bazlı "ödeme bir sonraki ay" bayrağı — True ise dönemin ödemesi bir sonraki ayın
payment_day'inde yapılır (ör. Ocak dönemi → 10 Şubat). salary/sgk/withholding zaten
source_type bazlı +1 ay kayar; bu, recurring vb. türlerde tanım-bazlı aynı davranışı sağlar.
Additive + nullable=False + server_default=false (mevcut satırlar davranış değiştirmez).

Revision ID: b4f7e2a9c1d3
Revises: c7e2a9f4b6d1
Create Date: 2026-07-04
"""
import sqlalchemy as sa
from alembic import op

revision = "b4f7e2a9c1d3"
down_revision = "c7e2a9f4b6d1"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "scheduled_definitions",
        sa.Column("pay_next_month", sa.Boolean(), nullable=False, server_default="false"),
    )


def downgrade():
    op.drop_column("scheduled_definitions", "pay_next_month")
