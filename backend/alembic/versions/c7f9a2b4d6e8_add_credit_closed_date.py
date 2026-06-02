"""add credit_products.closed_date

Revision ID: c7f9a2b4d6e8
Revises: 7d052738619a
Create Date: 2026-05-26
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = 'c7f9a2b4d6e8'
down_revision: Union[str, None] = '7d052738619a'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Kredi kapatma tarihi — status='closed' olduğunda doldurulur
    op.add_column(
        'credit_products',
        sa.Column('closed_date', sa.Date(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column('credit_products', 'closed_date')
