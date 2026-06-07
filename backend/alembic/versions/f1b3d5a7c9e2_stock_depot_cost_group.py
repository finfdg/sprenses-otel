"""stock_depots.cost_group — depo maliyet grubu (fb/staff/rooms/waste...)

Kişi başı F&B maliyeti, CPOR, zayiat % hesabı için departman→grup sınıflaması.

Revision ID: f1b3d5a7c9e2
Revises: e9a1c3f7b2d4
Create Date: 2026-06-07
"""
from alembic import op
import sqlalchemy as sa

revision = "f1b3d5a7c9e2"
down_revision = "e9a1c3f7b2d4"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("stock_depots", sa.Column("cost_group", sa.String(20), nullable=True))


def downgrade():
    op.drop_column("stock_depots", "cost_group")
