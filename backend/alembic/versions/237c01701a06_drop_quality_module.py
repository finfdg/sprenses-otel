"""drop_quality_module

Kalite modülü (Şablonlar + Formlar) sistemden tamamen kaldırıldı (kullanıcı kararı 2026-07-05).
Bu migration ilgili 6 tabloyu düşürür ve RBAC kayıtlarını (quality modülleri + "Kalite Müdürü"
rolü) temizler. role_module_permissions FK'leri CASCADE olduğundan modül/rol silinince ilgili
izin satırları otomatik gider.

NOT: Geri alınamaz (veri kaybı). Geri dönüş yalnızca drop öncesi alınan pg_dump yedeğinden yapılır.
Fresh/CI DB'de RBAC DELETE'leri no-op (satırlar seed'den sonra gelirdi ama seed'den de çıkarıldı).

Revision ID: 237c01701a06
Revises: e1a2c3d4f5b6
Create Date: 2026-07-05 13:10:38.351786
"""
from typing import Sequence, Union

from alembic import op

revision: str = '237c01701a06'
down_revision: Union[str, None] = 'e1a2c3d4f5b6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# Bağımlılık sırası önemsiz — CASCADE tablolar-arası FK'leri çözer.
_QUALITY_TABLES = [
    "quality_form_values",
    "quality_forms",
    "quality_template_fields",
    "quality_template_sections",
    "quality_template_assignees",
    "quality_templates",
]


def upgrade() -> None:
    # 1) Tabloları düşür
    for tbl in _QUALITY_TABLES:
        op.execute(f'DROP TABLE IF EXISTS "{tbl}" CASCADE')

    # 2) RBAC temizliği (prod'da mevcut; fresh/CI'de no-op).
    #    role_module_permissions FK'leri CASCADE → modül/rol silinince izinler otomatik gider.
    op.execute("DELETE FROM modules WHERE code LIKE 'quality%'")
    op.execute("DELETE FROM roles WHERE name = 'Kalite Müdürü'")


def downgrade() -> None:
    raise NotImplementedError(
        "Kalite modülü kaldırma geri alınamaz — geri dönüş için drop öncesi pg_dump yedeğini geri yükleyin."
    )
