"""add_payment_method_and_widen_tag_source

Revision ID: 12e465d5094c
Revises: 937f9dce1d17
Create Date: 2026-03-24 14:36:21.614804
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = '12e465d5094c'
down_revision: Union[str, None] = '937f9dce1d17'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('bank_transactions', sa.Column('payment_method', sa.String(length=20), nullable=True))
    op.alter_column('bank_transactions', 'tag_source',
               existing_type=sa.VARCHAR(length=10),
               type_=sa.String(length=20),
               existing_nullable=True)
    op.create_index('ix_bank_tx_payment_method', 'bank_transactions', ['payment_method'])


def downgrade() -> None:
    op.drop_index('ix_bank_tx_payment_method', table_name='bank_transactions')
    op.alter_column('bank_transactions', 'tag_source',
               existing_type=sa.String(length=20),
               type_=sa.VARCHAR(length=10),
               existing_nullable=True)
    op.drop_column('bank_transactions', 'payment_method')
