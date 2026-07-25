"""Denetim otomasyonu: ardışık koşu sınırı (max_chain_runs)

Bir tetiklemede kuyruktaki birden çok bulgu art arda işlenebilsin diye eklendi —
aksi halde kuyrukta iş varken timer'ın bir sonraki tiki boş bekleniyordu.
Sınır, gözetimsiz koşu sayısını (maliyet + canlıya art arda deploy) sınırlar.

1 = zincirleme kapalı (tetiklemede tek bulgu).

ELLE yazıldı (proje kuralı: autogenerate yanlış DROP üretebilir).

Revision ID: d5e9f3a7b2c4
Revises: c4d8e2f6a1b9
Create Date: 2026-07-25
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "d5e9f3a7b2c4"
down_revision: Union[str, None] = "c4d8e2f6a1b9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "audit_automation_config",
        sa.Column("max_chain_runs", sa.Integer(), nullable=False, server_default="3"),
    )


def downgrade() -> None:
    op.drop_column("audit_automation_config", "max_chain_runs")
