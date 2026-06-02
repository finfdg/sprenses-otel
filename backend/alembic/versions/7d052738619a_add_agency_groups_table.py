"""add_agency_groups_table

Revision ID: 7d052738619a
Revises: e9f3b7d2c5a4
Create Date: 2026-05-23

NOT: Bu dosya başlangıçta autogenerate gürültüsü (checks/check_uploads tablolarını
yanlış sırada drop/recreate eden bir `_old_upgrade_do_not_run` ve gerçek upgrade ile
uyumsuz ikinci bir `downgrade` tanımı) içeriyordu. Gürültü temizlendi; migration'ın
gerçek amacı yalnızca agency_groups tablosunu eklemek ve mevcut grupları seed etmektir.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = '7d052738619a'
down_revision: Union[str, None] = 'e9f3b7d2c5a4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'agency_groups',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(length=100), nullable=False),
        sa.Column('members', sa.JSON(), nullable=False, server_default='[]'),
        sa.Column('created_at', sa.DateTime(timezone=True),
                  server_default=sa.text("now()"), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True),
                  server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('name', name='uq_agency_groups_name'),
    )
    op.create_index('ix_agency_groups_id', 'agency_groups', ['id'])

    # Mevcut grupları seed et
    op.execute("""
        INSERT INTO agency_groups (name, members) VALUES
        ('ALLTOURS',  '["ALLTOURS D", "ALLTOURS NV"]'),
        ('ANEX',      '["ANEX EU", "ANEX BDT", "ANEXPOL", "ANEXTORO"]'),
        ('BYEBYE',    '["BYEBYE D", "BYEBYE NV"]'),
        ('CORAL',     '["CORAL RU", "CORAL PL", "CORAL CZ", "CORALTR", "CORAL DEU"]'),
        ('WEBRES',    '["WEBRES", "WEBRES EU"]'),
        ('MUNFERIT',  '["MUNFERIT TL", "MUNFERIT EUR", "MUNFERIT USD"]'),
        ('LIBERO',    '["LIBERO TOUR", "LIBERO DEU"]')
    """)


def downgrade() -> None:
    op.drop_index('ix_agency_groups_id', table_name='agency_groups')
    op.drop_table('agency_groups')
