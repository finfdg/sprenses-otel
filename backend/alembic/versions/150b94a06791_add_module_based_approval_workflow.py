"""add_module_based_approval_workflow

Revision ID: 150b94a06791
Revises: bfaaaa45cc57
Create Date: 2026-04-13 10:43:35.358965
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = '150b94a06791'
down_revision: Union[str, None] = 'bfaaaa45cc57'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Yeni tablo: talep eden roller
    op.create_table('approval_workflow_requestor_roles',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('workflow_id', sa.Integer(), nullable=False),
        sa.Column('role_id', sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(['role_id'], ['roles.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['workflow_id'], ['approval_workflows.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('workflow_id', 'role_id', name='uq_awrr_workflow_role')
    )
    op.create_index('ix_awrr_workflow', 'approval_workflow_requestor_roles', ['workflow_id'], unique=False)

    # Yeni tablo: onay veren roller
    op.create_table('approval_workflow_approver_roles',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('workflow_id', sa.Integer(), nullable=False),
        sa.Column('role_id', sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(['role_id'], ['roles.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['workflow_id'], ['approval_workflows.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('workflow_id', 'role_id', name='uq_awar_workflow_role')
    )
    op.create_index('ix_awar_workflow', 'approval_workflow_approver_roles', ['workflow_id'], unique=False)

    # approval_workflows: module_id ekle, entity_type nullable yap
    op.add_column('approval_workflows', sa.Column('module_id', sa.Integer(), nullable=True))
    op.alter_column('approval_workflows', 'entity_type',
                    existing_type=sa.VARCHAR(length=50),
                    nullable=True)
    op.create_index('ix_aw_module', 'approval_workflows', ['module_id'], unique=False)
    op.create_foreign_key('fk_aw_module', 'approval_workflows', 'modules', ['module_id'], ['id'], ondelete='SET NULL')

    # approval_requests: yeni kolonlar
    op.add_column('approval_requests', sa.Column('module_code', sa.String(length=50), nullable=True))
    op.add_column('approval_requests', sa.Column('action_type', sa.String(length=10), nullable=True))
    op.add_column('approval_requests', sa.Column('payload_json', sa.Text(), nullable=True))

    # Mevcut eski workflow'ları pasifleştir
    op.execute("UPDATE approval_workflows SET is_active = false WHERE module_id IS NULL")


def downgrade() -> None:
    # approval_requests: yeni kolonları kaldır
    op.drop_column('approval_requests', 'payload_json')
    op.drop_column('approval_requests', 'action_type')
    op.drop_column('approval_requests', 'module_code')

    # approval_workflows: module_id kaldır, entity_type NOT NULL yap
    op.drop_constraint('fk_aw_module', 'approval_workflows', type_='foreignkey')
    op.drop_index('ix_aw_module', table_name='approval_workflows')
    op.drop_column('approval_workflows', 'module_id')
    op.alter_column('approval_workflows', 'entity_type',
                    existing_type=sa.VARCHAR(length=50),
                    nullable=False)

    # Yeni tabloları kaldır
    op.drop_index('ix_awar_workflow', table_name='approval_workflow_approver_roles')
    op.drop_table('approval_workflow_approver_roles')
    op.drop_index('ix_awrr_workflow', table_name='approval_workflow_requestor_roles')
    op.drop_table('approval_workflow_requestor_roles')
