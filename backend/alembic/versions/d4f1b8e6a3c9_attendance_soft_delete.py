"""attendance_logs.deleted_at — soft delete (silinen kayıt soluk gösterilir)

Revision ID: d4f1b8e6a3c9
Revises: c3e9a1f7d2b8
Create Date: 2026-06-05

Silinen giriş/çıkış kayıtları DB'den kaldırılmaz; deleted_at damgalanır. Geçmiş'te
soluk gösterilir ama aktif hesaplara (içeride/puantaj/kiosk/alternasyon) dahil edilmez.
Elle yazıldı (autogenerate kullanılmadı).
"""
from alembic import op
import sqlalchemy as sa

revision = "d4f1b8e6a3c9"
down_revision = "c3e9a1f7d2b8"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("attendance_logs", sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True))


def downgrade():
    op.drop_column("attendance_logs", "deleted_at")
