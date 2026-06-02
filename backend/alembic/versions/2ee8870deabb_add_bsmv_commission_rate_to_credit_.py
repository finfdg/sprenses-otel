"""add_bsmv_commission_rate_to_credit_products

Revision ID: 2ee8870deabb
Revises: bb8eb02e1937
Create Date: 2026-03-25 07:46:29.310955
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = '2ee8870deabb'
down_revision: Union[str, None] = 'bb8eb02e1937'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('credit_products', sa.Column('bsmv_rate', sa.Numeric(6, 4), nullable=True))
    op.add_column('credit_products', sa.Column('commission_rate', sa.Numeric(6, 4), nullable=True))


def downgrade() -> None:
    op.drop_column('credit_products', 'commission_rate')
    op.drop_column('credit_products', 'bsmv_rate')
