"""add_hotel_reservation_module

Revision ID: d8e2f4a1b9c3
Revises: 5ebcc4513c06
Create Date: 2026-05-13 11:50:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = 'd8e2f4a1b9c3'
down_revision: Union[str, None] = '5ebcc4513c06'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── reservation_uploads ─────────────────────────────────
    op.create_table('reservation_uploads',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('file_name', sa.String(length=255), nullable=False),
        sa.Column('file_url', sa.String(length=500), nullable=True),
        sa.Column('file_type', sa.String(length=10), nullable=True),
        sa.Column('hotel_name', sa.String(length=100), nullable=True),
        sa.Column('period_checkin_start', sa.Date(), nullable=True),
        sa.Column('period_checkin_end', sa.Date(), nullable=True),
        sa.Column('period_record_start', sa.Date(), nullable=True),
        sa.Column('period_record_end', sa.Date(), nullable=True),
        sa.Column('total_rows', sa.Integer(), nullable=False, server_default=sa.text('0')),
        sa.Column('new_rows', sa.Integer(), nullable=False, server_default=sa.text('0')),
        sa.Column('updated_rows', sa.Integer(), nullable=False, server_default=sa.text('0')),
        sa.Column('uploaded_by', sa.Integer(), nullable=True),
        sa.Column('uploaded_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['uploaded_by'], ['users.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
    )

    # ── reservations ────────────────────────────────────────
    op.create_table('reservations',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('rec_id', sa.Integer(), nullable=False),
        sa.Column('upload_id', sa.Integer(), nullable=True),
        sa.Column('agency', sa.String(length=50), nullable=True),
        sa.Column('room_type', sa.String(length=40), nullable=True),
        sa.Column('voucher', sa.String(length=40), nullable=True),
        sa.Column('guests', sa.Text(), nullable=True),
        sa.Column('checkin_date', sa.Date(), nullable=False),
        sa.Column('checkout_date', sa.Date(), nullable=False),
        sa.Column('nights', sa.Integer(), nullable=False, server_default=sa.text('0')),
        sa.Column('record_date', sa.Date(), nullable=False),
        sa.Column('board', sa.String(length=10), nullable=True),
        sa.Column('vip_type', sa.String(length=20), nullable=True),
        sa.Column('rooms', sa.Integer(), nullable=False, server_default=sa.text('1')),
        sa.Column('adult', sa.Integer(), nullable=False, server_default=sa.text('0')),
        sa.Column('child_paid', sa.Integer(), nullable=False, server_default=sa.text('0')),
        sa.Column('child_free', sa.Integer(), nullable=False, server_default=sa.text('0')),
        sa.Column('baby', sa.Integer(), nullable=False, server_default=sa.text('0')),
        sa.Column('nation', sa.String(length=10), nullable=True),
        sa.Column('net_amount', sa.Numeric(precision=12, scale=2), nullable=True),
        sa.Column('currency', sa.String(length=5), nullable=True),
        sa.Column('eur_total', sa.Numeric(precision=12, scale=2), nullable=False, server_default=sa.text('0')),
        sa.Column('per_room', sa.Numeric(precision=10, scale=2), nullable=True),
        sa.Column('per_adult', sa.Numeric(precision=10, scale=2), nullable=True),
        sa.Column('rez_status', sa.String(length=20), nullable=True),
        sa.Column('status', sa.String(length=20), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['upload_id'], ['reservation_uploads.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_reservations_rec_id', 'reservations', ['rec_id'], unique=True)
    op.create_index('ix_reservations_checkin_date', 'reservations', ['checkin_date'], unique=False)
    op.create_index('ix_reservations_record_date', 'reservations', ['record_date'], unique=False)
    op.create_index('ix_reservations_agency', 'reservations', ['agency'], unique=False)
    op.create_index('ix_reservations_nation', 'reservations', ['nation'], unique=False)
    op.create_index('ix_reservations_room_type', 'reservations', ['room_type'], unique=False)
    op.create_index('ix_reservations_checkin_agency', 'reservations', ['checkin_date', 'agency'], unique=False)
    op.create_index('ix_reservations_checkin_nation', 'reservations', ['checkin_date', 'nation'], unique=False)

    # ── Seed: Modül kaydı ──────────────────────────────────
    op.execute("""
        INSERT INTO modules (name, code, description, parent_id, is_active, sort_order)
        SELECT 'Otel Rezervasyon', 'sales.hotel_reservation',
               'Otel rezervasyon verilerinin XLS ile yüklenmesi ve analiz raporları',
               (SELECT id FROM modules WHERE code = 'sales'), true, 20
        WHERE NOT EXISTS (SELECT 1 FROM modules WHERE code = 'sales.hotel_reservation');
    """)

    # ── Seed: Admin yetkisi ────────────────────────────────
    op.execute("""
        INSERT INTO role_module_permissions (role_id, module_id, can_view, can_use)
        SELECT r.id, m.id, true, true
        FROM roles r, modules m
        WHERE r.name = 'Admin' AND m.code = 'sales.hotel_reservation'
        ON CONFLICT DO NOTHING;
    """)


def downgrade() -> None:
    op.execute("DELETE FROM role_module_permissions WHERE module_id IN (SELECT id FROM modules WHERE code = 'sales.hotel_reservation');")
    op.execute("DELETE FROM modules WHERE code = 'sales.hotel_reservation';")
    op.drop_index('ix_reservations_checkin_nation', table_name='reservations')
    op.drop_index('ix_reservations_checkin_agency', table_name='reservations')
    op.drop_index('ix_reservations_room_type', table_name='reservations')
    op.drop_index('ix_reservations_nation', table_name='reservations')
    op.drop_index('ix_reservations_agency', table_name='reservations')
    op.drop_index('ix_reservations_record_date', table_name='reservations')
    op.drop_index('ix_reservations_checkin_date', table_name='reservations')
    op.drop_index('ix_reservations_rec_id', table_name='reservations')
    op.drop_table('reservations')
    op.drop_table('reservation_uploads')
