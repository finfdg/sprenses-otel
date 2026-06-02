"""Add username, split name into first_name and last_name

Revision ID: c3d4e5f6g7h8
Revises: b2c3d4e5f6g7
Create Date: 2026-02-22
"""
from alembic import op
import sqlalchemy as sa

# revision identifiers
revision = "c3d4e5f6g7h8"
down_revision = "b2c3d4e5f6g7"
branch_labels = None
depends_on = None


def upgrade():
    # 1. Add new columns
    op.add_column("users", sa.Column("first_name", sa.String(100), nullable=True))
    op.add_column("users", sa.Column("last_name", sa.String(100), nullable=True))
    op.add_column("users", sa.Column("username", sa.String(50), nullable=True))

    # 2. Migrate data: split existing name into first_name/last_name, generate username from email
    op.execute("""
        UPDATE users SET
            first_name = CASE
                WHEN position(' ' in name) > 0 THEN substring(name from 1 for position(' ' in name) - 1)
                ELSE name
            END,
            last_name = CASE
                WHEN position(' ' in name) > 0 THEN substring(name from position(' ' in name) + 1)
                ELSE ''
            END,
            username = split_part(email, '@', 1)
    """)

    # 3. Make columns NOT NULL after data migration
    op.alter_column("users", "first_name", nullable=False)
    op.alter_column("users", "last_name", nullable=False)
    op.alter_column("users", "username", nullable=False)

    # 4. Add unique index on username
    op.create_index("ix_users_username", "users", ["username"], unique=True)

    # 5. Drop old name column
    op.drop_column("users", "name")


def downgrade():
    # 1. Add back name column
    op.add_column("users", sa.Column("name", sa.String(100), nullable=True))

    # 2. Migrate data back
    op.execute("""
        UPDATE users SET name = CASE
            WHEN last_name != '' THEN first_name || ' ' || last_name
            ELSE first_name
        END
    """)

    op.alter_column("users", "name", nullable=False)

    # 3. Drop new columns
    op.drop_index("ix_users_username", "users")
    op.drop_column("users", "username")
    op.drop_column("users", "last_name")
    op.drop_column("users", "first_name")
