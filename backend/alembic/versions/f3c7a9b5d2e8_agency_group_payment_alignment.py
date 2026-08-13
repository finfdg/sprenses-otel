"""agency_groups.payment_alignment — ciro projeksiyonu ödeme günü hizalaması.

friday (varsayılan): vade sonrası ilk Cuma · month_end: vadenin düştüğü ayın son
günü (ör. Nordic ay sonlarında öder). Detay: docs/modules/nakit-akim.md.

Revision ID: f3c7a9b5d2e8
Revises: e6a1c4f8b2d7
Create Date: 2026-08-13
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "f3c7a9b5d2e8"
down_revision: Union[str, None] = "e6a1c4f8b2d7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "agency_groups",
        sa.Column("payment_alignment", sa.String(length=10),
                  server_default="friday", nullable=False),
    )


def downgrade() -> None:
    op.drop_column("agency_groups", "payment_alignment")
