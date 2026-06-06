"""sales_collections.customer_name ekle (avans bakiyesi görünümü için)

Revision ID: f4b8d1e6a2c7
Revises: e3a9c7d2b5f1
Create Date: 2026-06-06
"""
from alembic import op
import sqlalchemy as sa

revision = "f4b8d1e6a2c7"
down_revision = "e3a9c7d2b5f1"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("sales_collections", sa.Column("customer_name", sa.String(length=300), nullable=True))


def downgrade():
    op.drop_column("sales_collections", "customer_name")
