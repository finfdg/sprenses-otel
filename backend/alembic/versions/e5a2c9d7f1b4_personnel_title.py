"""personnel.title — görev (ünvan) alanı

Revision ID: e5a2c9d7f1b4
Revises: d4f1b8e6a3c9
Create Date: 2026-06-05

Personelin görevi/ünvanı (ör. ELEKTRİKÇİ, TEKNİK MÜDÜR). Excel sicil listesindeki
"Gorev" kolonundan içe aktarılır. Elle yazıldı.
"""
from alembic import op
import sqlalchemy as sa

revision = "e5a2c9d7f1b4"
down_revision = "d4f1b8e6a3c9"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("personnel", sa.Column("title", sa.String(120), nullable=True))


def downgrade():
    op.drop_column("personnel", "title")
