"""add payment instruction lists + items

Revision ID: d4e8f1a9c2b6
Revises: c7f9a2b4d6e8
Create Date: 2026-05-26
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = 'd4e8f1a9c2b6'
down_revision: Union[str, None] = 'c7f9a2b4d6e8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'payment_instruction_lists',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(length=200), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('status', sa.String(length=20), server_default='draft', nullable=False),
        sa.Column('created_by', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['created_by'], ['users.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_table(
        'payment_instruction_items',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('list_id', sa.Integer(), nullable=False),
        sa.Column('vendor_id', sa.Integer(), nullable=True),
        sa.Column('hesap_kodu', sa.String(length=50), nullable=True),
        sa.Column('hesap_adi', sa.String(length=300), nullable=False),
        sa.Column('amount', sa.Numeric(15, 2), server_default='0', nullable=False),
        sa.Column('balance_snapshot', sa.Numeric(15, 2), nullable=True),
        sa.Column('notes', sa.String(length=300), nullable=True),
        sa.Column('sort_order', sa.Integer(), server_default='0', nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['list_id'], ['payment_instruction_lists.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['vendor_id'], ['vendors.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_pi_items_list', 'payment_instruction_items', ['list_id'])


def downgrade() -> None:
    op.drop_index('ix_pi_items_list', table_name='payment_instruction_items')
    op.drop_table('payment_instruction_items')
    op.drop_table('payment_instruction_lists')
