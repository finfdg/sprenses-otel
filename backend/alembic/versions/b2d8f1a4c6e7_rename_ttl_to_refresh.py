"""attendance_settings: token_ttl_sec → refresh_sec (knob = yenileme süresi)

Revision ID: b2d8f1a4c6e7
Revises: a1c7e9f2b3d4
Create Date: 2026-06-04

Panel knob'u artık "QR yenileme süresi" (ekranda QR ne sıklıkta değişir). Güvenlik
geçerliliği (TTL) kodda `refresh + GRACE` olarak türetilir. Kolon adı buna uyarlanır.
"""
from alembic import op

revision = "b2d8f1a4c6e7"
down_revision = "a1c7e9f2b3d4"
branch_labels = None
depends_on = None


def upgrade():
    op.alter_column("attendance_settings", "token_ttl_sec", new_column_name="refresh_sec")


def downgrade():
    op.alter_column("attendance_settings", "refresh_sec", new_column_name="token_ttl_sec")
