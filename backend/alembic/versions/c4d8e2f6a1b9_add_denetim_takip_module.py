"""Denetim Takip modülü — bulgu/boyut/koşu tabloları + system.denetim RBAC

Kurumsal denetim raporlarını (docs/denetim/*.md) yaşayan veriye çevirir:
  audit_reports          — rapor başlığı (v4, ileride v5)
  audit_dimensions       — 23 skor boyutu (score_current SAKLANMAZ, türetilir)
  audit_findings         — bulgular (tablonun satırı, otomasyonun iş kalemi)
  audit_finding_runs     — otomasyon koşu geçmişi (denetlenebilir iz)
  audit_automation_config — tek satır (id=1) otomasyon ayarı + acil durdurma anahtarı

ELLE yazıldı (proje kuralı: autogenerate yanlış DROP üretebilir).

Modül kaydı taze DB'de de çalışsın diye `WHERE EXISTS (parent)` ile koşulludur
(R4'te yakalanan migration-FK-sırası tuzağı: parent modül 02_seed.sql'de ve
migration'dan SONRA yükleniyor).

Revision ID: c4d8e2f6a1b9
Revises: e8f2b6d4a9c3
Create Date: 2026-07-25
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "c4d8e2f6a1b9"
down_revision: Union[str, None] = "e8f2b6d4a9c3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_MODULE_CODE = "system.denetim"


def upgrade() -> None:
    # ── audit_reports ──────────────────────────────────────────
    op.create_table(
        "audit_reports",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("key", sa.String(length=60), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("report_date", sa.Date(), nullable=False),
        sa.Column("doc_path", sa.String(length=300), nullable=True),
        sa.Column("baseline_score", sa.Numeric(5, 2), nullable=True),
        sa.Column("target_score", sa.Numeric(5, 2), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_audit_reports_key", "audit_reports", ["key"], unique=True)

    # ── audit_dimensions ───────────────────────────────────────
    op.create_table(
        "audit_dimensions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("report_id", sa.Integer(), nullable=False),
        sa.Column("no", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("score_prev", sa.Numeric(4, 2), nullable=True),
        sa.Column("score_baseline", sa.Numeric(4, 2), nullable=False),
        sa.Column("score_target", sa.Numeric(4, 2), nullable=False),
        sa.Column("layer", sa.String(length=20), nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(["report_id"], ["audit_reports.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("report_id", "no", name="uq_audit_dimension_report_no"),
    )
    op.create_index("ix_audit_dimensions_report_id", "audit_dimensions", ["report_id"])

    # ── audit_findings ─────────────────────────────────────────
    op.create_table(
        "audit_findings",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("report_id", sa.Integer(), nullable=False),
        sa.Column("code", sa.String(length=30), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("dimension_no", sa.Integer(), nullable=False),
        sa.Column("risk", sa.String(length=10), nullable=False),
        sa.Column("effort", sa.String(length=2), nullable=False),
        sa.Column("category", sa.String(length=20), nullable=False),
        sa.Column("status", sa.String(length=12), nullable=False, server_default="acik"),
        sa.Column("evidence", sa.Text(), nullable=True),
        sa.Column("solution", sa.Text(), nullable=True),
        sa.Column("closure_criteria", sa.Text(), nullable=True),
        sa.Column("source_section", sa.String(length=120), nullable=True),
        sa.Column("score_impact", sa.Numeric(4, 2), nullable=False, server_default="0.2"),
        sa.Column("automatable", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("auto_enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("prompt_override", sa.Text(), nullable=True),
        sa.Column("auto_attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_run_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_run_status", sa.String(length=20), nullable=True),
        sa.Column("branch_name", sa.String(length=120), nullable=True),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("closed_by", sa.Integer(), nullable=True),
        sa.Column("closure_note", sa.Text(), nullable=True),
        sa.Column("verification_output", sa.Text(), nullable=True),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["report_id"], ["audit_reports.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["closed_by"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("report_id", "code", name="uq_audit_finding_report_code"),
    )
    op.create_index("ix_audit_findings_report_id", "audit_findings", ["report_id"])
    op.create_index("ix_audit_findings_status", "audit_findings", ["status"])
    op.create_index("ix_audit_findings_risk", "audit_findings", ["risk"])
    op.create_index(
        "ix_audit_findings_dimension", "audit_findings", ["report_id", "dimension_no"],
    )

    # ── audit_finding_runs ─────────────────────────────────────
    op.create_table(
        "audit_finding_runs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("finding_id", sa.Integer(), nullable=False),
        sa.Column("trigger", sa.String(length=12), nullable=False, server_default="otomatik"),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="calisiyor"),
        sa.Column("started_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("duration_sec", sa.Integer(), nullable=True),
        sa.Column("branch", sa.String(length=120), nullable=True),
        sa.Column("commit_sha", sa.String(length=40), nullable=True),
        sa.Column("files_changed", sa.Integer(), nullable=True),
        sa.Column("tests_passed", sa.Integer(), nullable=True),
        sa.Column("tests_failed", sa.Integer(), nullable=True),
        sa.Column("deployed", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("rolled_back", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("model", sa.String(length=40), nullable=True),
        sa.Column("cost_usd", sa.Numeric(8, 4), nullable=True),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("log_excerpt", sa.Text(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(["finding_id"], ["audit_findings.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_audit_finding_runs_finding_id", "audit_finding_runs", ["finding_id"])
    op.create_index(
        "ix_audit_runs_finding_started", "audit_finding_runs", ["finding_id", "started_at"],
    )

    # ── audit_automation_config (tek satır) ────────────────────
    op.create_table(
        "audit_automation_config",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("interval_hours", sa.Integer(), nullable=False, server_default="5"),
        sa.Column("model", sa.String(length=40), nullable=False, server_default="opus"),
        sa.Column("max_attempts", sa.Integer(), nullable=False, server_default="2"),
        sa.Column("max_budget_usd", sa.Numeric(6, 2), nullable=False, server_default="8.00"),
        sa.Column("timeout_min", sa.Integer(), nullable=False, server_default="45"),
        sa.Column("auto_deploy", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("auto_rollback", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("min_free_mb", sa.Integer(), nullable=False, server_default="2500"),
        sa.Column("notify_inapp", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("notify_email", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("last_run_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_by", sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(["updated_by"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.execute(
        "INSERT INTO audit_automation_config (id) VALUES (1) ON CONFLICT (id) DO NOTHING",
    )

    # ── RBAC: system.denetim modülü ────────────────────────────
    # Koşullu: parent (system) yoksa atla — taze DB'de seed sonradan yükleniyor (R4 dersi)
    op.execute(f"""
        INSERT INTO modules (name, code, description, parent_id, is_active, sort_order)
        SELECT 'Denetim Takip', '{_MODULE_CODE}',
               'Kurumsal denetim bulgularının takibi, skor panosu ve otomatik düzeltme',
               m.id, true, 120
        FROM modules m
        WHERE m.code = 'system'
          AND NOT EXISTS (SELECT 1 FROM modules WHERE code = '{_MODULE_CODE}');
    """)

    # Admin rolüne tam izin
    op.execute(f"""
        INSERT INTO role_module_permissions (role_id, module_id, can_view, can_use)
        SELECT r.id, m.id, true, true
        FROM roles r
        CROSS JOIN modules m
        WHERE m.code = '{_MODULE_CODE}'
          AND r.name = 'Admin'
        ON CONFLICT ON CONSTRAINT uq_role_module DO UPDATE SET
            can_view = true, can_use = true;
    """)


def downgrade() -> None:
    op.execute(f"""
        DELETE FROM role_module_permissions
        WHERE module_id IN (SELECT id FROM modules WHERE code = '{_MODULE_CODE}');
    """)
    op.execute(f"DELETE FROM modules WHERE code = '{_MODULE_CODE}';")

    op.drop_table("audit_automation_config")
    op.drop_index("ix_audit_runs_finding_started", table_name="audit_finding_runs")
    op.drop_index("ix_audit_finding_runs_finding_id", table_name="audit_finding_runs")
    op.drop_table("audit_finding_runs")
    op.drop_index("ix_audit_findings_dimension", table_name="audit_findings")
    op.drop_index("ix_audit_findings_risk", table_name="audit_findings")
    op.drop_index("ix_audit_findings_status", table_name="audit_findings")
    op.drop_index("ix_audit_findings_report_id", table_name="audit_findings")
    op.drop_table("audit_findings")
    op.drop_index("ix_audit_dimensions_report_id", table_name="audit_dimensions")
    op.drop_table("audit_dimensions")
    op.drop_index("ix_audit_reports_key", table_name="audit_reports")
    op.drop_table("audit_reports")
