"""users.email_verified + email_verified_at — e-posta teyidi

Kullanıcının tanımlı e-posta adresinin doğrulanıp doğrulanmadığını tutar. Teyit
e-postasındaki bağlantıya tıklanınca True olur. E-posta değişince False'a döner
(apply_user_update). ELLE yazıldı (additive + nullable/default).

Revision ID: f2b8d1a5c9e3
Revises: e1a4c7f9b2d6
Create Date: 2026-07-06
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "f2b8d1a5c9e3"
down_revision: Union[str, None] = "e1a4c7f9b2d6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column(
            "email_verified",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )
    op.add_column(
        "users",
        sa.Column("email_verified_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("users", "email_verified_at")
    op.drop_column("users", "email_verified")
