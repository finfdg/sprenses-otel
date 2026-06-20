"""checks + finance_events: bank_name_inferred (banka tahmini bayrağı)

Revision ID: d2a6c4f8e1b5
Revises: c1f5a8e3b9d2
Create Date: 2026-06-20

Çekin bankası Sedna'da boşsa, ardışık çek-numarası komşularından (aynı çek defteri =
aynı banka) interpolasyonla TAHMİN edilebilir. Tahmin gerçek veriyle karışmasın diye
ayrı bayrak: True → değer çıkarımdır ("~tahmin" rozeti). finance_events'e de denormalize
(nakit akım çek kartında aynı rozeti gösterebilsin). Additive + default False → geriye uyumlu.
"""
from alembic import op
import sqlalchemy as sa

revision = "d2a6c4f8e1b5"
down_revision = "c1f5a8e3b9d2"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("checks", sa.Column("bank_name_inferred", sa.Boolean(), nullable=False, server_default=sa.false()))
    op.add_column("finance_events", sa.Column("bank_name_inferred", sa.Boolean(), nullable=False, server_default=sa.false()))


def downgrade():
    op.drop_column("finance_events", "bank_name_inferred")
    op.drop_column("checks", "bank_name_inferred")
