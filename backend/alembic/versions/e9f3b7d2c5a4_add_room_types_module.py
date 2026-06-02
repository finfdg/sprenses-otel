"""add_room_types_module

room_types tablosu + sales.room_types modülü + Admin yetkisi + 341 odanın
rezervasyon hacmine orantılı tahmini dağılım seed'i.

Revision ID: e9f3b7d2c5a4
Revises: d8e2f4a1b9c3
Create Date: 2026-05-21 09:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = 'e9f3b7d2c5a4'
down_revision: Union[str, None] = 'd8e2f4a1b9c3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── room_types ──────────────────────────────────────────
    op.create_table(
        'room_types',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('code', sa.String(length=40), nullable=False),
        sa.Column('name', sa.String(length=120), nullable=False),
        sa.Column('total_rooms', sa.Integer(), nullable=False, server_default=sa.text('0')),
        sa.Column('max_occupancy', sa.Integer(), nullable=False, server_default=sa.text('2')),
        sa.Column('sort_order', sa.Integer(), nullable=False, server_default=sa.text('0')),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default=sa.text('true')),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('code', name='uq_room_types_code'),
        sa.CheckConstraint('total_rooms >= 0', name='ck_room_types_total_rooms_positive'),
        sa.CheckConstraint('max_occupancy >= 1', name='ck_room_types_max_occupancy_positive'),
    )
    op.create_index('ix_room_types_sort_order', 'room_types', ['sort_order'], unique=False)
    op.create_index('ix_room_types_is_active', 'room_types', ['is_active'], unique=False)

    # ── Seed: 341 odanın rezervasyon hacmine orantılı tahmini dağılımı ─
    # Toplam: 126 + 96 + 52 + 21 + 16 + 14 + 14 + 1 + 1 = 341
    op.execute("""
        INSERT INTO room_types (code, name, total_rooms, max_occupancy, sort_order, is_active, description)
        VALUES
            ('STD KARA',   'Standart Kara Manzaralı',     126, 3, 10, true,
             'Rezervasyon hacmine göre tahmini değer — gerçek değeri Oda Tipleri sayfasından düzeltin.'),
            ('STD DNZ',    'Standart Deniz Manzaralı',     96, 3, 20, true,
             'Rezervasyon hacmine göre tahmini değer — gerçek değeri Oda Tipleri sayfasından düzeltin.'),
            ('SIDE SEA V', 'Side Deniz Manzaralı',         52, 3, 30, true,
             'Rezervasyon hacmine göre tahmini değer — gerçek değeri Oda Tipleri sayfasından düzeltin.'),
            ('FAM DNZ',    'Aile Odası Deniz Manzaralı',   21, 4, 40, true,
             'Rezervasyon hacmine göre tahmini değer — gerçek değeri Oda Tipleri sayfasından düzeltin.'),
            ('DBP',        'Dubleks',                      16, 4, 50, true,
             'Rezervasyon hacmine göre tahmini değer — kısaltma anlamı ve gerçek değer için düzeltin.'),
            ('J.SUITE',    'Junior Suite',                 14, 4, 60, true,
             'Rezervasyon hacmine göre tahmini değer — gerçek değeri Oda Tipleri sayfasından düzeltin.'),
            ('DBL POOL V', 'Çift Yataklı Havuz Manzaralı', 14, 3, 70, true,
             'Rezervasyon hacmine göre tahmini değer — gerçek değeri Oda Tipleri sayfasından düzeltin.'),
            ('SUIT DNZ',   'Suite Deniz Manzaralı',         1, 4, 80, true,
             'Rezervasyon hacmine göre tahmini değer — gerçek değeri Oda Tipleri sayfasından düzeltin.'),
            ('TERASLI S.', 'Teraslı Suite',                 1, 4, 90, true,
             'Rezervasyon hacmine göre tahmini değer — gerçek değeri Oda Tipleri sayfasından düzeltin.')
        ON CONFLICT (code) DO NOTHING;
    """)

    # ── Seed: Modül kaydı (sales altında) ──────────────────────
    op.execute("""
        INSERT INTO modules (name, code, description, parent_id, is_active, sort_order)
        SELECT 'Oda Tipleri', 'sales.room_types',
               'Otel oda tipi envanteri — doluluk hesaplamasında payda olarak kullanılır',
               (SELECT id FROM modules WHERE code = 'sales'), true, 30
        WHERE NOT EXISTS (SELECT 1 FROM modules WHERE code = 'sales.room_types');
    """)

    # ── Seed: Admin yetkisi ────────────────────────────────────
    op.execute("""
        INSERT INTO role_module_permissions (role_id, module_id, can_view, can_use)
        SELECT r.id, m.id, true, true
        FROM roles r, modules m
        WHERE r.name = 'Admin' AND m.code = 'sales.room_types'
        ON CONFLICT DO NOTHING;
    """)


def downgrade() -> None:
    op.execute("DELETE FROM role_module_permissions WHERE module_id IN (SELECT id FROM modules WHERE code = 'sales.room_types');")
    op.execute("DELETE FROM modules WHERE code = 'sales.room_types';")
    op.drop_index('ix_room_types_is_active', table_name='room_types')
    op.drop_index('ix_room_types_sort_order', table_name='room_types')
    op.drop_table('room_types')
