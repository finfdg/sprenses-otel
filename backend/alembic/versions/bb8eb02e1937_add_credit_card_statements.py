"""add_credit_card_statements

Revision ID: bb8eb02e1937
Revises: 20327ad823d2
Create Date: 2026-03-24 22:30:27.738912
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = 'bb8eb02e1937'
down_revision: Union[str, None] = '20327ad823d2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('credit_card_statements',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('credit_product_id', sa.Integer(), nullable=False),
    sa.Column('ekstre_no', sa.String(length=100), nullable=True),
    sa.Column('kesim_tarihi', sa.Date(), nullable=False),
    sa.Column('son_odeme_tarihi', sa.Date(), nullable=False),
    sa.Column('onceki_bakiye', sa.Numeric(precision=15, scale=2), nullable=False),
    sa.Column('donem_harcama', sa.Numeric(precision=15, scale=2), nullable=False),
    sa.Column('faiz_ucret', sa.Numeric(precision=15, scale=2), nullable=False),
    sa.Column('donem_odeme', sa.Numeric(precision=15, scale=2), nullable=False),
    sa.Column('toplam_borc', sa.Numeric(precision=15, scale=2), nullable=False),
    sa.Column('asgari_odeme', sa.Numeric(precision=15, scale=2), nullable=False),
    sa.Column('is_paid', sa.Boolean(), nullable=False),
    sa.Column('paid_amount', sa.Numeric(precision=15, scale=2), nullable=True),
    sa.Column('paid_date', sa.Date(), nullable=True),
    sa.Column('file_name', sa.String(length=255), nullable=True),
    sa.Column('file_url', sa.String(length=500), nullable=True),
    sa.Column('uploaded_by', sa.Integer(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['credit_product_id'], ['credit_products.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_cc_stmt_product', 'credit_card_statements', ['credit_product_id'], unique=False)
    op.create_table('credit_card_transactions',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('statement_id', sa.Integer(), nullable=False),
    sa.Column('islem_tarihi', sa.Date(), nullable=True),
    sa.Column('aciklama', sa.Text(), nullable=False),
    sa.Column('kategori', sa.String(length=100), nullable=True),
    sa.Column('taksit_bilgi', sa.String(length=100), nullable=True),
    sa.Column('tutar', sa.Numeric(precision=15, scale=2), nullable=False),
    sa.Column('is_credit', sa.Boolean(), nullable=False),
    sa.Column('bonus', sa.Numeric(precision=15, scale=2), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['statement_id'], ['credit_card_statements.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_cc_tx_stmt', 'credit_card_transactions', ['statement_id'], unique=False)


def downgrade() -> None:
    op.drop_index('ix_cc_tx_stmt', table_name='credit_card_transactions')
    op.drop_table('credit_card_transactions')
    op.drop_index('ix_cc_stmt_product', table_name='credit_card_statements')
    op.drop_table('credit_card_statements')
