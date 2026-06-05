"""shift_definitions — vardiya tanımları (Sabah/Akşam/Gece/Split)

Revision ID: f6b3d8e1a4c2
Revises: e5a2c9d7f1b4
Create Date: 2026-06-05

Otel 7/24 çalıştığı için vardiya tanımları. Normal vardiya start/end; gece vardiyası
gece yarısını geçebilir (end <= start). Split vardiya için ikinci segment (start2/end2).
Elle yazıldı. Birkaç örnek vardiya seed edilir.
"""
from alembic import op
import sqlalchemy as sa

revision = "f6b3d8e1a4c2"
down_revision = "e5a2c9d7f1b4"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "shift_definitions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(80), nullable=False),
        sa.Column("color", sa.String(7), nullable=False, server_default="#0d9488"),
        sa.Column("start_time", sa.Time(), nullable=False),
        sa.Column("end_time", sa.Time(), nullable=False),
        sa.Column("start_time2", sa.Time(), nullable=True),
        sa.Column("end_time2", sa.Time(), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
    )
    # Örnek vardiyalar (otel standardı)
    op.execute("""
        INSERT INTO shift_definitions (name, color, start_time, end_time, description, sort_order) VALUES
        ('Sabah', '#3b82f6', '07:00', '15:00', 'Resepsiyon, Kat Hizmetleri, kahvaltı servisi', 1),
        ('Akşam', '#f59e0b', '15:00', '23:00', 'Akşam yemeği, yoğun check-in/out dönemi', 2),
        ('Gece', '#6366f1', '23:00', '07:00', 'Night Audit, Güvenlik, Temizlik', 3)
    """)


def downgrade():
    op.drop_table("shift_definitions")
