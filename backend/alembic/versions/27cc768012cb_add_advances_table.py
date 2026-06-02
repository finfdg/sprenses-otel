"""add_advances_table

Revision ID: 27cc768012cb
Revises: 2ee8870deabb
Create Date: 2026-03-26 01:00:47.119777
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = '27cc768012cb'
down_revision: Union[str, None] = '2ee8870deabb'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('advances',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('agency_name', sa.String(length=200), nullable=False),
    sa.Column('amount', sa.Numeric(precision=15, scale=2), nullable=False),
    sa.Column('currency', sa.String(length=5), nullable=False),
    sa.Column('advance_date', sa.Date(), nullable=False),
    sa.Column('status', sa.String(length=20), nullable=False),
    sa.Column('notes', sa.Text(), nullable=True),
    sa.Column('bank_transaction_id', sa.Integer(), nullable=True),
    sa.Column('received_date', sa.Date(), nullable=True),
    sa.Column('received_amount', sa.Numeric(precision=15, scale=2), nullable=True),
    sa.Column('created_by', sa.Integer(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['bank_transaction_id'], ['bank_transactions.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['created_by'], ['users.id'], ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_advances_date', 'advances', ['advance_date'], unique=False)
    op.create_index('ix_advances_status', 'advances', ['status'], unique=False)


def downgrade() -> None:
    op.drop_index('ix_advances_status', table_name='advances')
    op.drop_index('ix_advances_date', table_name='advances')
    op.drop_table('advances')
