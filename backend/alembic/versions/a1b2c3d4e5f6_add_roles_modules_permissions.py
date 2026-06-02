"""add roles modules permissions

Revision ID: a1b2c3d4e5f6
Revises: 050fbdd677b6
Create Date: 2026-02-22 18:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "a1b2c3d4e5f6"
down_revision: Union[str, None] = "050fbdd677b6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Create roles table
    op.create_table(
        "roles",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(50), unique=True, nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    # 2. Create modules table
    op.create_table(
        "modules",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("code", sa.String(50), unique=True, nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("icon", sa.String(50), nullable=True),
        sa.Column("parent_id", sa.Integer(), sa.ForeignKey("modules.id"), nullable=True),
        sa.Column("sort_order", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_modules_code", "modules", ["code"])

    # 3. Create role_module_permissions table
    op.create_table(
        "role_module_permissions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("role_id", sa.Integer(), sa.ForeignKey("roles.id", ondelete="CASCADE"), nullable=False),
        sa.Column("module_id", sa.Integer(), sa.ForeignKey("modules.id", ondelete="CASCADE"), nullable=False),
        sa.Column("can_view", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("can_create", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("can_edit", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("can_delete", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("role_id", "module_id", name="uq_role_module"),
    )

    # 4. Seed roles
    op.execute("INSERT INTO roles (id, name, description) VALUES (1, 'Admin', 'Tam yetkili yönetici')")
    op.execute("INSERT INTO roles (id, name, description) VALUES (2, 'Personel', 'Standart personel')")

    # 5. Seed modules
    op.execute("INSERT INTO modules (id, name, code, icon, sort_order) VALUES (1, 'Panel', 'dashboard', 'home', 0)")
    op.execute("INSERT INTO modules (id, name, code, icon, sort_order) VALUES (2, 'Odalar', 'rooms', 'bed', 1)")
    op.execute("INSERT INTO modules (id, name, code, icon, sort_order) VALUES (3, 'Rezervasyonlar', 'reservations', 'calendar', 2)")
    op.execute("INSERT INTO modules (id, name, code, icon, sort_order) VALUES (4, 'Misafirler', 'guests', 'users', 3)")
    op.execute("INSERT INTO modules (id, name, code, icon, sort_order) VALUES (5, 'Sistem', 'system', 'settings', 4)")
    op.execute("INSERT INTO modules (id, name, code, icon, parent_id, sort_order) VALUES (6, 'Kullanicilar', 'system.users', 'user', 5, 0)")
    op.execute("INSERT INTO modules (id, name, code, icon, parent_id, sort_order) VALUES (7, 'Roller', 'system.roles', 'shield', 5, 1)")
    op.execute("INSERT INTO modules (id, name, code, icon, parent_id, sort_order) VALUES (8, 'Moduller', 'system.modules', 'box', 5, 2)")

    # Reset sequences
    op.execute("SELECT setval('roles_id_seq', 2)")
    op.execute("SELECT setval('modules_id_seq', 8)")

    # 6. Seed permissions - Admin gets full access to all modules
    for module_id in range(1, 9):
        op.execute(
            f"INSERT INTO role_module_permissions (role_id, module_id, can_view, can_create, can_edit, can_delete) "
            f"VALUES (1, {module_id}, true, true, true, true)"
        )

    # Personel gets view-only on dashboard, rooms, reservations, guests
    for module_id in [1, 2, 3, 4]:
        op.execute(
            f"INSERT INTO role_module_permissions (role_id, module_id, can_view, can_create, can_edit, can_delete) "
            f"VALUES (2, {module_id}, true, false, false, false)"
        )

    # 7. Add role_id column to users (nullable first)
    op.add_column("users", sa.Column("role_id", sa.Integer(), nullable=True))

    # 8. Data migration: map existing users
    op.execute("UPDATE users SET role_id = 1 WHERE role = 'admin'")
    op.execute("UPDATE users SET role_id = 2 WHERE role != 'admin' OR role IS NULL")
    # Catch any remaining nulls
    op.execute("UPDATE users SET role_id = 2 WHERE role_id IS NULL")

    # 9. Make role_id NOT NULL and add FK
    op.alter_column("users", "role_id", nullable=False)
    op.create_foreign_key("fk_users_role_id", "users", "roles", ["role_id"], ["id"])

    # 10. Drop old role string column
    op.drop_column("users", "role")


def downgrade() -> None:
    # Re-add role string column
    op.add_column("users", sa.Column("role", sa.String(20), server_default="staff"))
    op.execute("UPDATE users SET role = 'admin' WHERE role_id = 1")
    op.execute("UPDATE users SET role = 'staff' WHERE role_id != 1")

    # Drop FK and role_id column
    op.drop_constraint("fk_users_role_id", "users", type_="foreignkey")
    op.drop_column("users", "role_id")

    # Drop tables
    op.drop_table("role_module_permissions")
    op.drop_table("modules")
    op.drop_table("roles")
