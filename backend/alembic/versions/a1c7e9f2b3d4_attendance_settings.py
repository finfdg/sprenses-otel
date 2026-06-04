"""attendance_settings tablosu — PDKS panelden ayarlanabilir QR TTL

Revision ID: a1c7e9f2b3d4
Revises: 2b99ab490dff
Create Date: 2026-06-04

Tek satırlı (id=1) ayar tablosu. token_ttl_sec = kiosk QR geçerlilik süresi (saniye).
Elle yazıldı (autogenerate kullanılmadı) — yalnızca bu tabloyu kurar, varsayılan satırı ekler.
"""
from alembic import op
import sqlalchemy as sa

revision = "a1c7e9f2b3d4"
down_revision = "2b99ab490dff"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "attendance_settings",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("token_ttl_sec", sa.Integer(), nullable=False, server_default="7"),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=True),
    )
    # Tekil varsayılan satır
    op.execute("INSERT INTO attendance_settings (id, token_ttl_sec) VALUES (1, 7)")


def downgrade():
    op.drop_table("attendance_settings")
