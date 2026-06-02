"""drop rooms guests reservations modules

Revision ID: e3a4b5c6d7e8
Revises: d2319c1d7469
Create Date: 2026-02-24 14:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "e3a4b5c6d7e8"
down_revision: Union[str, None] = "d2319c1d7469"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Modül izinlerini sil (role_module_permissions)
    op.execute(
        "DELETE FROM role_module_permissions "
        "WHERE module_id IN (SELECT id FROM modules WHERE code IN ('rooms', 'guests', 'reservations'))"
    )

    # 2. Modül kayıtlarını sil
    op.execute("DELETE FROM modules WHERE code IN ('rooms', 'guests', 'reservations')")

    # 3. Tabloları sil (FK sırası: reservations önce)
    op.drop_table("reservations")
    op.drop_index(op.f("ix_rooms_room_number"), table_name="rooms")
    op.drop_table("rooms")
    op.drop_table("guests")


def downgrade() -> None:
    # guests tablosunu yeniden oluştur
    op.create_table(
        "guests",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("first_name", sa.String(length=100), nullable=False),
        sa.Column("last_name", sa.String(length=100), nullable=False),
        sa.Column("email", sa.String(length=255), nullable=True),
        sa.Column("phone", sa.String(length=20), nullable=True),
        sa.Column("id_number", sa.String(length=50), nullable=True),
        sa.Column("nationality", sa.String(length=50), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )

    # rooms tablosunu yeniden oluştur
    op.create_table(
        "rooms",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("room_number", sa.String(length=10), nullable=False),
        sa.Column("room_type", sa.String(length=50), nullable=False),
        sa.Column("floor", sa.Integer(), nullable=False),
        sa.Column("capacity", sa.Integer(), nullable=False),
        sa.Column("price_per_night", sa.Numeric(precision=10, scale=2), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_rooms_room_number"), "rooms", ["room_number"], unique=True)

    # reservations tablosunu yeniden oluştur
    op.create_table(
        "reservations",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("guest_id", sa.Integer(), nullable=False),
        sa.Column("room_id", sa.Integer(), nullable=False),
        sa.Column("check_in", sa.Date(), nullable=False),
        sa.Column("check_out", sa.Date(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("total_price", sa.Numeric(precision=10, scale=2), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["guest_id"], ["guests.id"]),
        sa.ForeignKeyConstraint(["room_id"], ["rooms.id"]),
        sa.PrimaryKeyConstraint("id"),
    )

    # Modül kayıtlarını geri ekle
    op.execute("INSERT INTO modules (name, code, icon, sort_order) VALUES ('Odalar', 'rooms', 'bed', 1)")
    op.execute("INSERT INTO modules (name, code, icon, sort_order) VALUES ('Rezervasyonlar', 'reservations', 'calendar', 2)")
    op.execute("INSERT INTO modules (name, code, icon, sort_order) VALUES ('Misafirler', 'guests', 'users', 3)")
