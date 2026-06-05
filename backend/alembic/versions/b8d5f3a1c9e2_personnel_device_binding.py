"""personnel device binding — anti-buddy-punch (cihaz bağlama)

Revision ID: b8d5f3a1c9e2
Revises: a7c4e2f9b1d8
Create Date: 2026-06-05

Basış kimliğini kuran cihaza kilitler. access_token artık yalnızca enrollment;
basış kimliği cihaza özel device_token (hash'i burada). Tek aktif cihaz.
Elle yazıldı.
"""
from alembic import op
import sqlalchemy as sa

revision = "b8d5f3a1c9e2"
down_revision = "a7c4e2f9b1d8"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("personnel", sa.Column("device_token_hash", sa.String(64), nullable=True))
    op.add_column("personnel", sa.Column("device_bound_at", sa.DateTime(timezone=True), nullable=True))
    op.create_index("ix_personnel_device_token_hash", "personnel", ["device_token_hash"])


def downgrade():
    op.drop_index("ix_personnel_device_token_hash", table_name="personnel")
    op.drop_column("personnel", "device_bound_at")
    op.drop_column("personnel", "device_token_hash")
