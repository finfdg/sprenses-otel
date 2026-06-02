"""add_approval_workflow_tables

Revision ID: bfaaaa45cc57
Revises: b7c8d9e0f1a2
Create Date: 2026-04-13 10:06:12.538117
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = 'bfaaaa45cc57'
down_revision: Union[str, None] = 'b7c8d9e0f1a2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('approval_workflows',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(length=200), nullable=False),
        sa.Column('entity_type', sa.String(length=50), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default=sa.text('true')),
        sa.Column('conditions_json', sa.Text(), nullable=True),
        sa.Column('created_by', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True),
        sa.ForeignKeyConstraint(['created_by'], ['users.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('name')
    )
    op.create_index('ix_aw_entity_type', 'approval_workflows', ['entity_type'], unique=False)
    op.create_index('ix_aw_active', 'approval_workflows', ['is_active'], unique=False)

    op.create_table('approval_workflow_steps',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('workflow_id', sa.Integer(), nullable=False),
        sa.Column('step_number', sa.SmallInteger(), nullable=False),
        sa.Column('approver_type', sa.String(length=20), nullable=False),
        sa.Column('approver_user_id', sa.Integer(), nullable=True),
        sa.Column('approver_role_id', sa.Integer(), nullable=True),
        sa.Column('approver_dept_id', sa.Integer(), nullable=True),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default=sa.text('true')),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True),
        sa.ForeignKeyConstraint(['approver_dept_id'], ['departments.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['approver_role_id'], ['roles.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['approver_user_id'], ['users.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['workflow_id'], ['approval_workflows.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('workflow_id', 'step_number', name='uq_aws_workflow_step')
    )
    op.create_index('ix_aws_workflow', 'approval_workflow_steps', ['workflow_id'], unique=False)

    op.create_table('approval_requests',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('workflow_id', sa.Integer(), nullable=True),
        sa.Column('entity_type', sa.String(length=50), nullable=False),
        sa.Column('entity_id', sa.Integer(), nullable=False),
        sa.Column('status', sa.String(length=20), nullable=False, server_default=sa.text("'pending'")),
        sa.Column('current_step', sa.SmallInteger(), nullable=False, server_default=sa.text('1')),
        sa.Column('total_steps', sa.SmallInteger(), nullable=False, server_default=sa.text('1')),
        sa.Column('requested_by', sa.Integer(), nullable=True),
        sa.Column('requested_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True),
        sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('completed_by', sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(['completed_by'], ['users.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['requested_by'], ['users.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['workflow_id'], ['approval_workflows.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_ar_entity', 'approval_requests', ['entity_type', 'entity_id'], unique=False)
    op.create_index('ix_ar_status', 'approval_requests', ['status'], unique=False)
    op.create_index('ix_ar_requested_by', 'approval_requests', ['requested_by'], unique=False)
    op.create_index('ix_ar_workflow', 'approval_requests', ['workflow_id'], unique=False)

    op.create_table('approval_request_logs',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('request_id', sa.Integer(), nullable=False),
        sa.Column('step_number', sa.SmallInteger(), nullable=False),
        sa.Column('action', sa.String(length=20), nullable=False),
        sa.Column('actor_id', sa.Integer(), nullable=True),
        sa.Column('note', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True),
        sa.ForeignKeyConstraint(['actor_id'], ['users.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['request_id'], ['approval_requests.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_arl_request', 'approval_request_logs', ['request_id'], unique=False)
    op.create_index('ix_arl_actor', 'approval_request_logs', ['actor_id'], unique=False)


def downgrade() -> None:
    op.drop_index('ix_arl_actor', table_name='approval_request_logs')
    op.drop_index('ix_arl_request', table_name='approval_request_logs')
    op.drop_table('approval_request_logs')

    op.drop_index('ix_ar_workflow', table_name='approval_requests')
    op.drop_index('ix_ar_requested_by', table_name='approval_requests')
    op.drop_index('ix_ar_status', table_name='approval_requests')
    op.drop_index('ix_ar_entity', table_name='approval_requests')
    op.drop_table('approval_requests')

    op.drop_index('ix_aws_workflow', table_name='approval_workflow_steps')
    op.drop_table('approval_workflow_steps')

    op.drop_index('ix_aw_active', table_name='approval_workflows')
    op.drop_index('ix_aw_entity_type', table_name='approval_workflows')
    op.drop_table('approval_workflows')
