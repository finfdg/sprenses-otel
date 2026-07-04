"""vendor_notes table + vendors iletişim kolonları (contact_person/phone/email)

Cariler yeniden tasarımı (2026-07-04, "Sprenses Tasarımlar"): cari detayında "Notlar"
sekmesi (görüşme/takip notları — ekle/düzenle/sil/yapıldı) + "Firma Bilgileri" sekmesinde
iletişim alanları. Notlar/iletişim finansal etkisi olmayan metadatadır; onaydan muaftır.

ELLE yazıldı (autogenerate yanlış DROP üretebilir) — yalnız additive: 3 nullable kolon +
1 yeni tablo. Mevcut veri etkilenmez.

Revision ID: d8c3f1a2b4e6
Revises: b4f7e2a9c1d3
Create Date: 2026-07-04
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "d8c3f1a2b4e6"
down_revision: Union[str, None] = "b4f7e2a9c1d3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── vendors: iletişim kolonları (nullable, additive) ──
    op.add_column("vendors", sa.Column("contact_person", sa.String(200), nullable=True))
    op.add_column("vendors", sa.Column("phone", sa.String(50), nullable=True))
    op.add_column("vendors", sa.Column("email", sa.String(200), nullable=True))

    # ── vendor_notes: cari görüşme/takip notları ──
    op.create_table(
        "vendor_notes",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "vendor_id", sa.Integer(),
            sa.ForeignKey("vendors.id", ondelete="CASCADE"), nullable=False,
        ),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column(
            "author_id", sa.Integer(),
            sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True,
        ),
        sa.Column("author_name", sa.String(150), nullable=True),
        sa.Column("done", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True),
            server_default=sa.func.now(), nullable=False,
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True),
            server_default=sa.func.now(), nullable=False,
        ),
    )
    op.create_index("ix_vendor_notes_vendor_id", "vendor_notes", ["vendor_id"])


def downgrade() -> None:
    op.drop_index("ix_vendor_notes_vendor_id", table_name="vendor_notes")
    op.drop_table("vendor_notes")
    op.drop_column("vendors", "email")
    op.drop_column("vendors", "phone")
    op.drop_column("vendors", "contact_person")
