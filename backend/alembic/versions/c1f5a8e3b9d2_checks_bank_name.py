"""checks: bank_name kolonu (verilen çekin ödeneceği banka)

Revision ID: c1f5a8e3b9d2
Revises: a7c4e2b9d1f3
Create Date: 2026-06-20

Verilen çekin hangi bankadan (çek defterinin bankasından) ödeneceği bilgisi. Sedna
`AccCheck.Bank` alanından gelir. Eskiden ayrı kolon olmadığından `description`'a yazılıyor,
ama description Excel notlarıyla karışıyordu → güvenilir değildi. Ayrı kolon = temiz gösterim.
Additive + nullable → geriye uyumlu (eski kod kolonu görmezden gelir).
"""
from alembic import op
import sqlalchemy as sa

revision = "c1f5a8e3b9d2"
down_revision = "a7c4e2b9d1f3"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("checks", sa.Column("bank_name", sa.String(length=100), nullable=True))


def downgrade():
    op.drop_column("checks", "bank_name")
