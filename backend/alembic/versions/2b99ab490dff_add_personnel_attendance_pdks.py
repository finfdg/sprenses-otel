"""add personnel attendance PDKS

Revision ID: 2b99ab490dff
Revises: d4e8f1a9c2b6
Create Date: 2026-06-04 18:13:30.056551

NOT: Autogenerate, model↔DB arasındaki mevcut (alakasız) drift'i de üretmişti
(checks tablosunu düşürmek vb.) — bunlar bilinçli olarak ÇIKARILDI. Bu migration
yalnızca PDKS tablolarını ekler.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '2b99ab490dff'
down_revision: Union[str, None] = 'd4e8f1a9c2b6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'personnel',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('full_name', sa.String(length=150), nullable=False),
        sa.Column('employee_code', sa.String(length=30), nullable=False),
        sa.Column('department', sa.String(length=80), nullable=True),
        sa.Column('phone', sa.String(length=30), nullable=True),
        sa.Column('access_token', sa.String(length=64), nullable=False),
        sa.Column('is_active', sa.Boolean(), server_default='true', nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_personnel_access_token'), 'personnel', ['access_token'], unique=True)
    op.create_index(op.f('ix_personnel_employee_code'), 'personnel', ['employee_code'], unique=True)

    op.create_table(
        'attendance_logs',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('personnel_id', sa.Integer(), nullable=False),
        sa.Column('type', sa.String(length=5), nullable=False),
        sa.Column('punched_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('source', sa.String(length=20), server_default='phone_qr', nullable=False),
        sa.Column('recorded_by', sa.Integer(), nullable=True),
        sa.Column('note', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['personnel_id'], ['personnel.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['recorded_by'], ['users.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_attendance_logs_personnel_id'), 'attendance_logs', ['personnel_id'], unique=False)
    op.create_index('ix_attendance_personnel_time', 'attendance_logs', ['personnel_id', 'punched_at'], unique=False)
    op.create_index('ix_attendance_punched_at', 'attendance_logs', ['punched_at'], unique=False)


def downgrade() -> None:
    op.drop_index('ix_attendance_punched_at', table_name='attendance_logs')
    op.drop_index('ix_attendance_personnel_time', table_name='attendance_logs')
    op.drop_index(op.f('ix_attendance_logs_personnel_id'), table_name='attendance_logs')
    op.drop_table('attendance_logs')
    op.drop_index(op.f('ix_personnel_employee_code'), table_name='personnel')
    op.drop_index(op.f('ix_personnel_access_token'), table_name='personnel')
    op.drop_table('personnel')
