"""PMS acente adı → muhasebe 120 cari kodu köprüsü (agency_code_map).

Rezervasyon acente grupları (agency_groups.members) PMS adlarıyla tutulur; hak ediş firmaları
muhasebe 120 kodlarıdır. İsimler iki evrende FARKLI (ör. 'CORAL PL' ↔ 'CORAL SEYAHAT A.Ş.') →
güvenilir eşleme yalnız PMS `Agency.Name → AgencyAccCode.AccCode` köprüsüyle olur. Sales
import'u bu tabloyu Sedna PMS'ten doldurur; receivable_service offline okur.

Revision ID: a7d3e9f2c5b8
Revises: f4a8c2d6e9b1
Create Date: 2026-07-02
"""
import sqlalchemy as sa
from alembic import op

revision = "a7d3e9f2c5b8"
down_revision = "f4a8c2d6e9b1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "agency_code_map",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("pms_name", sa.String(200), nullable=False, unique=True),
        sa.Column("acc_code", sa.String(50), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_agency_code_map_acc", "agency_code_map", ["acc_code"])


def downgrade() -> None:
    op.drop_index("ix_agency_code_map_acc", table_name="agency_code_map")
    op.drop_table("agency_code_map")
