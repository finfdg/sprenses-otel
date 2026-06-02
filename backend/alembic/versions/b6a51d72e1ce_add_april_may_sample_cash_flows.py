"""add_april_may_sample_cash_flows

Revision ID: b6a51d72e1ce
Revises: fc72105614de
Create Date: 2026-03-07 11:42:05.504313
"""
from typing import Sequence, Union

from alembic import op

revision: str = 'b6a51d72e1ce'
down_revision: Union[str, None] = 'fc72105614de'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Nisan 2026 verileri
    op.execute(
        "INSERT INTO cash_flows (title, type, amount, description, date, created_by) VALUES "
        "('Oda Gelirleri', 'income', 52000.00, 'Nisan ayı oda satış geliri', '2026-04-01', "
        "(SELECT id FROM users WHERE username = 'admin' LIMIT 1)), "
        "('Restoran Geliri', 'income', 14800.00, 'Restoran ve bar geliri', '2026-04-03', "
        "(SELECT id FROM users WHERE username = 'admin' LIMIT 1)), "
        "('SPA Geliri', 'income', 9500.00, 'SPA ve wellness geliri', '2026-04-05', "
        "(SELECT id FROM users WHERE username = 'admin' LIMIT 1)), "
        "('Havuz Bar Geliri', 'income', 7200.00, 'Havuz bar ve içecek satışları', '2026-04-08', "
        "(SELECT id FROM users WHERE username = 'admin' LIMIT 1)), "
        "('Otopark Geliri', 'income', 3800.00, 'Otopark ve vale ücreti', '2026-04-10', "
        "(SELECT id FROM users WHERE username = 'admin' LIMIT 1)), "
        "('Etkinlik Geliri', 'income', 11000.00, 'Düğün ve organizasyon geliri', '2026-04-15', "
        "(SELECT id FROM users WHERE username = 'admin' LIMIT 1)), "
        "('Personel Maaşları', 'expense', 34000.00, 'Nisan ayı personel maaşları', '2026-04-01', "
        "(SELECT id FROM users WHERE username = 'admin' LIMIT 1)), "
        "('Doğalgaz Faturası', 'expense', 4200.00, 'Nisan ayı doğalgaz gideri', '2026-04-04', "
        "(SELECT id FROM users WHERE username = 'admin' LIMIT 1)), "
        "('Gıda Alımları', 'expense', 9800.00, 'Restoran gıda tedariği', '2026-04-06', "
        "(SELECT id FROM users WHERE username = 'admin' LIMIT 1)), "
        "('Bahçe Bakımı', 'expense', 3500.00, 'Bahçe ve peyzaj bakım gideri', '2026-04-09', "
        "(SELECT id FROM users WHERE username = 'admin' LIMIT 1)), "
        "('Sigorta Ödemesi', 'expense', 6200.00, 'Yıllık sigorta taksiti', '2026-04-12', "
        "(SELECT id FROM users WHERE username = 'admin' LIMIT 1)), "
        "('Su Faturası', 'expense', 2800.00, 'Nisan ayı su gideri', '2026-04-14', "
        "(SELECT id FROM users WHERE username = 'admin' LIMIT 1))"
    )

    # Mayıs 2026 verileri
    op.execute(
        "INSERT INTO cash_flows (title, type, amount, description, date, created_by) VALUES "
        "('Oda Gelirleri', 'income', 61000.00, 'Mayıs ayı oda satış geliri', '2026-05-01', "
        "(SELECT id FROM users WHERE username = 'admin' LIMIT 1)), "
        "('Restoran Geliri', 'income', 17200.00, 'Restoran ve bar geliri', '2026-05-03', "
        "(SELECT id FROM users WHERE username = 'admin' LIMIT 1)), "
        "('SPA Geliri', 'income', 11500.00, 'SPA ve wellness geliri', '2026-05-06', "
        "(SELECT id FROM users WHERE username = 'admin' LIMIT 1)), "
        "('Plaj Hizmetleri', 'income', 8900.00, 'Plaj şezlong ve şemsiye geliri', '2026-05-10', "
        "(SELECT id FROM users WHERE username = 'admin' LIMIT 1)), "
        "('Minibar Geliri', 'income', 5200.00, 'Minibar satışları', '2026-05-12', "
        "(SELECT id FROM users WHERE username = 'admin' LIMIT 1)), "
        "('Toplantı Salonu', 'income', 9400.00, 'Konferans ve toplantı salonu', '2026-05-18', "
        "(SELECT id FROM users WHERE username = 'admin' LIMIT 1)), "
        "('Transfer Geliri', 'income', 4600.00, 'Havalimanı transfer ücreti', '2026-05-22', "
        "(SELECT id FROM users WHERE username = 'admin' LIMIT 1)), "
        "('Personel Maaşları', 'expense', 36000.00, 'Mayıs ayı personel maaşları', '2026-05-01', "
        "(SELECT id FROM users WHERE username = 'admin' LIMIT 1)), "
        "('Elektrik Faturası', 'expense', 7800.00, 'Mayıs ayı elektrik gideri (klima)', '2026-05-04', "
        "(SELECT id FROM users WHERE username = 'admin' LIMIT 1)), "
        "('Gıda Alımları', 'expense', 12500.00, 'Restoran gıda tedariği', '2026-05-07', "
        "(SELECT id FROM users WHERE username = 'admin' LIMIT 1)), "
        "('Havuz Kimyasalları', 'expense', 2400.00, 'Havuz bakım ve kimyasal malzeme', '2026-05-11', "
        "(SELECT id FROM users WHERE username = 'admin' LIMIT 1)), "
        "('Pazarlama Gideri', 'expense', 5500.00, 'Online reklam ve tanıtım', '2026-05-15', "
        "(SELECT id FROM users WHERE username = 'admin' LIMIT 1)), "
        "('Çamaşırhane', 'expense', 3200.00, 'Dış kaynak çamaşırhane hizmeti', '2026-05-20', "
        "(SELECT id FROM users WHERE username = 'admin' LIMIT 1))"
    )


def downgrade() -> None:
    op.execute("DELETE FROM cash_flows WHERE date >= '2026-04-01'")
