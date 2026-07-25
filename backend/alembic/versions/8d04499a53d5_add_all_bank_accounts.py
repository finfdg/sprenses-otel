"""add_all_bank_accounts

Revision ID: 8d04499a53d5
Revises: 2b4495d4c8f5
Create Date: 2026-03-09 14:13:58.822192

NOT — GERÇEK IBAN'LAR KALDIRILDI (2026-07-25, public depo):
Bu migration başlangıçta şirketin GERÇEK banka hesap numaralarını içeriyordu. Depo public
olduğundan yer tutucularla (TR0000...) değiştirildi. Etkiler:
  - ÜRETİM: migration çoktan uygulandı, gerçek hesaplar `bank_accounts` tablosunda DURUYOR.
    Bu dosya artık yalnız tarihsel kayıttır; yeniden çalıştırılmaz.
  - CI / test DB: sıfırdan kurulumda yer tutucu IBAN'lar yazılır — testlerin hiçbiri bu
    değerlere bağlı değil (doğrulandı).
  - FELAKET KURTARMA: sıfırdan kurulumda gerçek hesaplar migration'dan DEĞİL, DB yedeğinden
    (`scripts/db-restore.sh`) gelir. Yedeksiz kurulumda hesaplar elle girilmelidir.
  - downgrade(): artık yer tutucu IBAN'ları siler → üretimde fiilen no-op. Bu bilinçli ve
    daha güvenli: bu migration'ın üretimde geri alınması zaten banka hesabı + hareketlerini
    silmek demekti.
UYARI: git GEÇMİŞİ hâlâ eski değerleri içerir — bu değişiklik yalnız güncel hâli temizler.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = '8d04499a53d5'
down_revision: Union[str, None] = '2b4495d4c8f5'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Yapı Kredi — 3 hesap
    op.execute(
        "INSERT INTO bank_accounts (bank_name, iban, currency, created_by) VALUES "
        "('Yapı Kredi', 'TR000000000000000000000101', 'TRY', "
        "(SELECT id FROM users WHERE username = 'admin' LIMIT 1)), "
        "('Yapı Kredi', 'TR000000000000000000000102', 'EUR', "
        "(SELECT id FROM users WHERE username = 'admin' LIMIT 1)), "
        "('Yapı Kredi', 'TR000000000000000000000103', 'TRY', "
        "(SELECT id FROM users WHERE username = 'admin' LIMIT 1))"
    )

    # TEB — 3 hesap
    op.execute(
        "INSERT INTO bank_accounts (bank_name, iban, currency, created_by) VALUES "
        "('TEB', 'TR000000000000000000000201', 'EUR', "
        "(SELECT id FROM users WHERE username = 'admin' LIMIT 1)), "
        "('TEB', 'TR000000000000000000000202', 'TRY', "
        "(SELECT id FROM users WHERE username = 'admin' LIMIT 1)), "
        "('TEB', 'TR000000000000000000000203', 'TRY', "
        "(SELECT id FROM users WHERE username = 'admin' LIMIT 1))"
    )

    # VakıfBank — 2 hesap
    op.execute(
        "INSERT INTO bank_accounts (bank_name, iban, currency, created_by) VALUES "
        "('VakıfBank', 'TR000000000000000000000301', 'TRY', "
        "(SELECT id FROM users WHERE username = 'admin' LIMIT 1)), "
        "('VakıfBank', 'TR000000000000000000000302', 'EUR', "
        "(SELECT id FROM users WHERE username = 'admin' LIMIT 1))"
    )

    # Garanti BBVA — 3 hesap
    op.execute(
        "INSERT INTO bank_accounts (bank_name, iban, currency, created_by) VALUES "
        "('Garanti BBVA', 'TR000000000000000000000401', 'TRY', "
        "(SELECT id FROM users WHERE username = 'admin' LIMIT 1)), "
        "('Garanti BBVA', 'TR000000000000000000000402', 'USD', "
        "(SELECT id FROM users WHERE username = 'admin' LIMIT 1)), "
        "('Garanti BBVA', 'TR000000000000000000000403', 'EUR', "
        "(SELECT id FROM users WHERE username = 'admin' LIMIT 1))"
    )

    # Halkbank — 3 hesap
    op.execute(
        "INSERT INTO bank_accounts (bank_name, iban, currency, created_by) VALUES "
        "('Halkbank', 'TR000000000000000000000501', 'TRY', "
        "(SELECT id FROM users WHERE username = 'admin' LIMIT 1)), "
        "('Halkbank', 'TR000000000000000000000502', 'TRY', "
        "(SELECT id FROM users WHERE username = 'admin' LIMIT 1)), "
        "('Halkbank', 'TR000000000000000000000503', 'EUR', "
        "(SELECT id FROM users WHERE username = 'admin' LIMIT 1))"
    )


def downgrade() -> None:
    ibans = (
        "'TR000000000000000000000101','TR000000000000000000000102','TR000000000000000000000103',"
        "'TR000000000000000000000201','TR000000000000000000000202','TR000000000000000000000203',"
        "'TR000000000000000000000301','TR000000000000000000000302',"
        "'TR000000000000000000000401','TR000000000000000000000402','TR000000000000000000000403',"
        "'TR000000000000000000000501','TR000000000000000000000502','TR000000000000000000000503'"
    )
    op.execute(
        f"DELETE FROM bank_transactions WHERE account_id IN "
        f"(SELECT id FROM bank_accounts WHERE iban IN ({ibans}))"
    )
    op.execute(
        f"DELETE FROM bank_statements WHERE account_id IN "
        f"(SELECT id FROM bank_accounts WHERE iban IN ({ibans}))"
    )
    op.execute(f"DELETE FROM bank_accounts WHERE iban IN ({ibans})")
