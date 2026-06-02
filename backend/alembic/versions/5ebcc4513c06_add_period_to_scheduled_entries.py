"""add_period_month_and_year_to_scheduled_entries

Revision ID: 5ebcc4513c06
Revises: ac3e8808bca8
Create Date: 2026-04-21
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = '5ebcc4513c06'
down_revision: Union[str, None] = 'ac3e8808bca8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('scheduled_entries', sa.Column('period_month', sa.Integer(), nullable=True))
    op.add_column('scheduled_entries', sa.Column('period_year', sa.Integer(), nullable=True))

    op.execute("""
        UPDATE scheduled_entries
           SET period_month = EXTRACT(MONTH FROM entry_date)::int,
               period_year  = EXTRACT(YEAR  FROM entry_date)::int
         WHERE period_month IS NULL OR period_year IS NULL
    """)

    op.alter_column('scheduled_entries', 'period_month', nullable=False)
    op.alter_column('scheduled_entries', 'period_year', nullable=False)

    op.create_index(
        'ix_schedentry_period',
        'scheduled_entries',
        ['source_type', 'period_year', 'period_month'],
    )


def downgrade() -> None:
    op.drop_index('ix_schedentry_period', table_name='scheduled_entries')
    op.drop_column('scheduled_entries', 'period_year')
    op.drop_column('scheduled_entries', 'period_month')
