"""add_match_number_system

Revision ID: ee61e9f2a02e
Revises: 12e465d5094c
Create Date: 2026-03-24 15:08:44.878487
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = 'ee61e9f2a02e'
down_revision: Union[str, None] = '12e465d5094c'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('bank_transactions', sa.Column('match_number', sa.Integer(), nullable=True))
    op.add_column('vendor_transactions', sa.Column('match_number', sa.Integer(), nullable=True))
    op.add_column('vendor_transactions', sa.Column('payment_method', sa.String(length=20), nullable=True))
    op.create_index('ix_bank_tx_match', 'bank_transactions', ['match_number'])
    op.create_index('ix_vendor_tx_match', 'vendor_transactions', ['match_number'])
    # Eşleştirme numarası sekansı
    op.execute("CREATE SEQUENCE IF NOT EXISTS match_number_seq START 1")


def downgrade() -> None:
    op.execute("DROP SEQUENCE IF EXISTS match_number_seq")
    op.drop_index('ix_vendor_tx_match', table_name='vendor_transactions')
    op.drop_index('ix_bank_tx_match', table_name='bank_transactions')
    op.drop_column('vendor_transactions', 'payment_method')
    op.drop_column('vendor_transactions', 'match_number')
    op.drop_column('bank_transactions', 'match_number')
