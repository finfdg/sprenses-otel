"""attendance_logs.edited_at — elle düzenlenen kaydı işaretle

Revision ID: c3e9a1f7d2b8
Revises: b2d8f1a4c6e7
Create Date: 2026-06-05

Düzenlenen giriş/çıkış kayıtları panoda farklı renkte gösterilir. edited_at NULL ise
kayıt düzenlenmemiştir. Elle yazıldı (autogenerate kullanılmadı).
"""
from alembic import op
import sqlalchemy as sa

revision = "c3e9a1f7d2b8"
down_revision = "b2d8f1a4c6e7"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("attendance_logs", sa.Column("edited_at", sa.DateTime(timezone=True), nullable=True))


def downgrade():
    op.drop_column("attendance_logs", "edited_at")
