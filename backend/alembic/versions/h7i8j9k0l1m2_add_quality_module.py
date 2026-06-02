"""Kalite modülü tablolarını oluştur ve RBAC kaydı yap.

Revision ID: h7i8j9k0l1m2
Revises: 5c53043e295c
Create Date: 2026-03-04
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "h7i8j9k0l1m2"
down_revision: Union[str, None] = "5c53043e295c"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── quality_templates ──────────────────────────────────────────
    op.create_table(
        "quality_templates",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("frequency", sa.String(20), nullable=False, server_default="daily"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("created_by", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_quality_templates_is_active", "quality_templates", ["is_active"])
    op.create_index("ix_quality_templates_frequency", "quality_templates", ["frequency"])

    # ── quality_template_sections ──────────────────────────────────
    op.create_table(
        "quality_template_sections",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("template_id", sa.Integer(), sa.ForeignKey("quality_templates.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default=sa.text("0")),
    )
    op.create_index("ix_quality_template_sections_template_id", "quality_template_sections", ["template_id"])

    # ── quality_template_fields ────────────────────────────────────
    op.create_table(
        "quality_template_fields",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("section_id", sa.Integer(), sa.ForeignKey("quality_template_sections.id", ondelete="CASCADE"), nullable=False),
        sa.Column("label", sa.String(300), nullable=False),
        sa.Column("field_type", sa.String(20), nullable=False),
        sa.Column("unit", sa.String(30), nullable=True),
        sa.Column("is_required", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("is_resource", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("is_guest_count", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("options", sa.Text(), nullable=True),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default=sa.text("0")),
    )
    op.create_index("ix_quality_template_fields_section_id", "quality_template_fields", ["section_id"])

    # ── quality_template_assignees ─────────────────────────────────
    op.create_table(
        "quality_template_assignees",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("template_id", sa.Integer(), sa.ForeignKey("quality_templates.id", ondelete="CASCADE"), nullable=False),
        sa.Column("assignment_type", sa.String(20), nullable=False),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=True),
        sa.Column("role_id", sa.Integer(), sa.ForeignKey("roles.id", ondelete="CASCADE"), nullable=True),
        sa.CheckConstraint(
            "(user_id IS NOT NULL AND role_id IS NULL) OR (user_id IS NULL AND role_id IS NOT NULL)",
            name="ck_assignee_user_or_role",
        ),
    )
    op.create_index("ix_quality_template_assignees_template_type", "quality_template_assignees", ["template_id", "assignment_type"])

    # ── quality_forms ──────────────────────────────────────────────
    op.create_table(
        "quality_forms",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("template_id", sa.Integer(), sa.ForeignKey("quality_templates.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("period_date", sa.Date(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="draft"),
        sa.Column("filled_by", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("reviewed_by", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("review_comment", sa.Text(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("template_id", "period_date", name="uq_template_period"),
    )
    op.create_index("ix_quality_forms_template_id", "quality_forms", ["template_id"])
    op.create_index("ix_quality_forms_period_date", "quality_forms", ["period_date"])
    op.create_index("ix_quality_forms_status", "quality_forms", ["status"])

    # ── quality_form_values ────────────────────────────────────────
    op.create_table(
        "quality_form_values",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("form_id", sa.Integer(), sa.ForeignKey("quality_forms.id", ondelete="CASCADE"), nullable=False),
        sa.Column("field_id", sa.Integer(), sa.ForeignKey("quality_template_fields.id", ondelete="CASCADE"), nullable=False),
        sa.Column("value", sa.Text(), nullable=True),
        sa.Column("corrective_action", sa.Text(), nullable=True),
        sa.UniqueConstraint("form_id", "field_id", name="uq_form_field"),
    )
    op.create_index("ix_quality_form_values_form_id", "quality_form_values", ["form_id"])

    # ── RBAC: Kalite modüllerini kaydet ────────────────────────────
    op.execute(
        "INSERT INTO modules (name, code, icon, parent_id, sort_order, is_active) "
        "VALUES ('Kalite', 'quality', 'clipboard-check', NULL, 10, true)"
    )
    op.execute(
        "INSERT INTO modules (name, code, icon, parent_id, sort_order, is_active) "
        "VALUES ('Şablonlar', 'quality.templates', 'file-text', "
        "(SELECT id FROM modules WHERE code = 'quality'), 0, true)"
    )
    op.execute(
        "INSERT INTO modules (name, code, icon, parent_id, sort_order, is_active) "
        "VALUES ('Formlar', 'quality.forms', 'file-check', "
        "(SELECT id FROM modules WHERE code = 'quality'), 1, true)"
    )

    # ── RBAC: Admin rolüne tam yetki ver ───────────────────────────
    op.execute(
        "INSERT INTO role_module_permissions (role_id, module_id, can_view, can_use) "
        "SELECT r.id, m.id, true, true "
        "FROM roles r, modules m "
        "WHERE r.name = 'Admin' AND m.code IN ('quality', 'quality.templates', 'quality.forms')"
    )


def downgrade() -> None:
    # İzinleri sil
    op.execute(
        "DELETE FROM role_module_permissions WHERE module_id IN "
        "(SELECT id FROM modules WHERE code IN ('quality', 'quality.templates', 'quality.forms'))"
    )
    # Modülleri sil (önce çocuk, sonra ebeveyn)
    op.execute("DELETE FROM modules WHERE code IN ('quality.templates', 'quality.forms')")
    op.execute("DELETE FROM modules WHERE code = 'quality'")
    # Tabloları sil
    op.drop_table("quality_form_values")
    op.drop_table("quality_forms")
    op.drop_table("quality_template_assignees")
    op.drop_table("quality_template_fields")
    op.drop_table("quality_template_sections")
    op.drop_table("quality_templates")
