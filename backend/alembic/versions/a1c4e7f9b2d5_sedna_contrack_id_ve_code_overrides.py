"""reservations.sedna_contrack_id + agency_code_overrides tablosu

Kontrat modülü Faz 0 (2026-07-17): rezervasyon↔Sedna kontrat bağı için ContrackId
kolonu (Sedna SQL join'i zaten vardı) + Sedna senkronunun silip yeniden yüklediği
agency_code_map için kalıcı yerel düzeltme katmanı.

Revision ID: a1c4e7f9b2d5
Revises: f7a8b9c0d1e2
Create Date: 2026-07-17
"""
from alembic import op
import sqlalchemy as sa

revision = "a1c4e7f9b2d5"
down_revision = "f7a8b9c0d1e2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("reservations", sa.Column("sedna_contrack_id", sa.Integer(), nullable=True))
    op.create_index("ix_reservations_sedna_contrack", "reservations", ["sedna_contrack_id"])

    op.create_table(
        "agency_code_overrides",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("pms_name", sa.String(length=200), nullable=False),
        sa.Column("acc_code", sa.String(length=50), nullable=False),
        sa.Column("notes", sa.String(length=300), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True),
                  server_default=sa.text("now()"), nullable=False),
        sa.UniqueConstraint("pms_name", name="uq_agency_code_overrides_pms_name"),
    )


def downgrade() -> None:
    op.drop_table("agency_code_overrides")
    op.drop_index("ix_reservations_sedna_contrack", table_name="reservations")
    op.drop_column("reservations", "sedna_contrack_id")
