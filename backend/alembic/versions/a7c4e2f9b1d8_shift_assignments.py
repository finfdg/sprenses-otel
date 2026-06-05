"""shift_assignments — vardiya çizelgesi (rota): hangi gün kim hangi vardiyada

Revision ID: a7c4e2f9b1d8
Revises: f6b3d8e1a4c2
Create Date: 2026-06-05

Tarih bazlı vardiya ataması. (personnel_id, work_date) benzersiz — bir personel
bir günde tek vardiyada. Personel veya vardiya tanımı silinince CASCADE ile gider.
Elle yazıldı.
"""
from alembic import op
import sqlalchemy as sa

revision = "a7c4e2f9b1d8"
down_revision = "f6b3d8e1a4c2"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "shift_assignments",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "personnel_id",
            sa.Integer(),
            sa.ForeignKey("personnel.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "shift_id",
            sa.Integer(),
            sa.ForeignKey("shift_definitions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("work_date", sa.Date(), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column(
            "created_by",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_unique_constraint(
        "uq_shift_assignment_personnel_date",
        "shift_assignments",
        ["personnel_id", "work_date"],
    )
    op.create_index("ix_shift_assignment_date", "shift_assignments", ["work_date"])
    op.create_index("ix_shift_assignment_shift", "shift_assignments", ["shift_id"])


def downgrade():
    op.drop_index("ix_shift_assignment_shift", table_name="shift_assignments")
    op.drop_index("ix_shift_assignment_date", table_name="shift_assignments")
    op.drop_constraint("uq_shift_assignment_personnel_date", "shift_assignments", type_="unique")
    op.drop_table("shift_assignments")
