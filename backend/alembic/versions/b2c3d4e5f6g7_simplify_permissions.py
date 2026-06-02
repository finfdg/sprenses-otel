"""Simplify permissions: can_create/can_edit/can_delete -> can_use

Revision ID: b2c3d4e5f6g7
Revises: a1b2c3d4e5f6
Create Date: 2026-02-22
"""
from alembic import op
import sqlalchemy as sa

revision = 'b2c3d4e5f6g7'
down_revision = 'a1b2c3d4e5f6'
branch_labels = None
depends_on = None


def upgrade():
    # Add can_use column (default False)
    op.add_column('role_module_permissions', sa.Column('can_use', sa.Boolean(), nullable=False, server_default=sa.text('false')))

    # Migrate data: can_use = true if any of can_create/can_edit/can_delete was true
    op.execute("""
        UPDATE role_module_permissions
        SET can_use = (can_create OR can_edit OR can_delete)
    """)

    # Drop old columns
    op.drop_column('role_module_permissions', 'can_create')
    op.drop_column('role_module_permissions', 'can_edit')
    op.drop_column('role_module_permissions', 'can_delete')


def downgrade():
    # Add old columns back
    op.add_column('role_module_permissions', sa.Column('can_create', sa.Boolean(), nullable=False, server_default=sa.text('false')))
    op.add_column('role_module_permissions', sa.Column('can_edit', sa.Boolean(), nullable=False, server_default=sa.text('false')))
    op.add_column('role_module_permissions', sa.Column('can_delete', sa.Boolean(), nullable=False, server_default=sa.text('false')))

    # Migrate data back: all three = can_use
    op.execute("""
        UPDATE role_module_permissions
        SET can_create = can_use, can_edit = can_use, can_delete = can_use
    """)

    # Drop can_use
    op.drop_column('role_module_permissions', 'can_use')
