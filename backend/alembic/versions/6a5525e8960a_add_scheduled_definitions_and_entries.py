"""add_scheduled_definitions_and_entries

Revision ID: 6a5525e8960a
Revises: a2b3c4d5e6f7
Create Date: 2026-04-11 08:28:20.041242

NOT: Bu migration başlangıçta autogenerate ile üretilmişti ve ilgisiz
tabloları (checks/check_uploads) yanlış sırada drop/recreate eden, ayrıca
çok sayıda alakasız indeks/sütun değişikliği içeren "autogenerate gürültüsü"
barındırıyordu. Bu gürültü sıfırdan `alembic upgrade head` çalıştırmayı
bozuyordu (checks.upload_id FK'si check_uploads'a bağlıyken önce check_uploads
düşürülmeye çalışılıyordu). Migration'ın gerçek amacı yalnızca
scheduled_definitions ve scheduled_entries tablolarını eklemektir; gürültü
temizlenmiştir.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = '6a5525e8960a'
down_revision: Union[str, None] = 'a2b3c4d5e6f7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('scheduled_definitions',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('source_type', sa.String(length=30), nullable=False),
    sa.Column('name', sa.String(length=200), nullable=False),
    sa.Column('category', sa.String(length=100), nullable=True),
    sa.Column('amount', sa.Numeric(precision=15, scale=2), nullable=False),
    sa.Column('currency', sa.String(length=3), nullable=False),
    sa.Column('frequency', sa.String(length=20), nullable=False),
    sa.Column('payment_day', sa.Integer(), nullable=False),
    sa.Column('start_month', sa.Integer(), nullable=False),
    sa.Column('year', sa.Integer(), nullable=False),
    sa.Column('notes', sa.Text(), nullable=True),
    sa.Column('is_active', sa.Boolean(), nullable=False),
    sa.Column('created_by', sa.Integer(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['created_by'], ['users.id'], ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_scheddef_active', 'scheduled_definitions', ['is_active'], unique=False)
    op.create_index('ix_scheddef_type', 'scheduled_definitions', ['source_type'], unique=False)
    op.create_table('scheduled_entries',
    sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
    sa.Column('definition_id', sa.Integer(), nullable=False),
    sa.Column('source_type', sa.String(length=30), nullable=False),
    sa.Column('entry_date', sa.Date(), nullable=False),
    sa.Column('amount', sa.Numeric(precision=15, scale=2), nullable=False),
    sa.Column('currency', sa.String(length=3), nullable=False),
    sa.Column('description', sa.Text(), nullable=True),
    sa.Column('is_paid', sa.Boolean(), nullable=False),
    sa.Column('paid_date', sa.Date(), nullable=True),
    sa.Column('notes', sa.Text(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['definition_id'], ['scheduled_definitions.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_schedentry_date', 'scheduled_entries', ['entry_date'], unique=False)
    op.create_index('ix_schedentry_paid', 'scheduled_entries', ['is_paid'], unique=False)
    op.create_index('ix_schedentry_source', 'scheduled_entries', ['source_type', 'definition_id'], unique=False)


def downgrade() -> None:
    op.drop_index('ix_schedentry_source', table_name='scheduled_entries')
    op.drop_index('ix_schedentry_paid', table_name='scheduled_entries')
    op.drop_index('ix_schedentry_date', table_name='scheduled_entries')
    op.drop_table('scheduled_entries')
    op.drop_index('ix_scheddef_type', table_name='scheduled_definitions')
    op.drop_index('ix_scheddef_active', table_name='scheduled_definitions')
    op.drop_table('scheduled_definitions')
