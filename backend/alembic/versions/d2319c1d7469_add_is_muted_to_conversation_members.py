"""add is_muted to conversation_members

Revision ID: d2319c1d7469
Revises: c1218b0c6358
Create Date: 2026-02-24 12:00:00.000000

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "d2319c1d7469"
down_revision = "c1218b0c6358"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "conversation_members",
        sa.Column("is_muted", sa.Boolean(), server_default="false", nullable=False),
    )


def downgrade() -> None:
    op.drop_column("conversation_members", "is_muted")
