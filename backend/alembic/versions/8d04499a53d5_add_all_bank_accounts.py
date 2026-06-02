"""add_all_bank_accounts

Revision ID: 8d04499a53d5
Revises: 2b4495d4c8f5
Create Date: 2026-03-09 14:13:58.822192
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
        "('Yapı Kredi', 'TR260006701000000072821701', 'TRY', "
        "(SELECT id FROM users WHERE username = 'admin' LIMIT 1)), "
        "('Yapı Kredi', 'TR210006701000000065488591', 'EUR', "
        "(SELECT id FROM users WHERE username = 'admin' LIMIT 1)), "
        "('Yapı Kredi', 'TR950006701000000065408689', 'TRY', "
        "(SELECT id FROM users WHERE username = 'admin' LIMIT 1))"
    )

    # TEB — 3 hesap
    op.execute(
        "INSERT INTO bank_accounts (bank_name, iban, currency, created_by) VALUES "
        "('TEB', 'TR520003200000000048909295', 'EUR', "
        "(SELECT id FROM users WHERE username = 'admin' LIMIT 1)), "
        "('TEB', 'TR410003200010700000015817', 'TRY', "
        "(SELECT id FROM users WHERE username = 'admin' LIMIT 1)), "
        "('TEB', 'TR540003200000000031666442', 'TRY', "
        "(SELECT id FROM users WHERE username = 'admin' LIMIT 1))"
    )

    # VakıfBank — 2 hesap
    op.execute(
        "INSERT INTO bank_accounts (bank_name, iban, currency, created_by) VALUES "
        "('VakıfBank', 'TR140001500158007301152442', 'TRY', "
        "(SELECT id FROM users WHERE username = 'admin' LIMIT 1)), "
        "('VakıfBank', 'TR540001500158048017640765', 'EUR', "
        "(SELECT id FROM users WHERE username = 'admin' LIMIT 1))"
    )

    # Garanti BBVA — 3 hesap
    op.execute(
        "INSERT INTO bank_accounts (bank_name, iban, currency, created_by) VALUES "
        "('Garanti BBVA', 'TR870006200011500006297372', 'TRY', "
        "(SELECT id FROM users WHERE username = 'admin' LIMIT 1)), "
        "('Garanti BBVA', 'TR030006200011500009075800', 'USD', "
        "(SELECT id FROM users WHERE username = 'admin' LIMIT 1)), "
        "('Garanti BBVA', 'TR660006200011500009075539', 'EUR', "
        "(SELECT id FROM users WHERE username = 'admin' LIMIT 1))"
    )

    # Halkbank — 3 hesap
    op.execute(
        "INSERT INTO bank_accounts (bank_name, iban, currency, created_by) VALUES "
        "('Halkbank', 'TR230001200137600010100011', 'TRY', "
        "(SELECT id FROM users WHERE username = 'admin' LIMIT 1)), "
        "('Halkbank', 'TR670001200137600010102420', 'TRY', "
        "(SELECT id FROM users WHERE username = 'admin' LIMIT 1)), "
        "('Halkbank', 'TR210001200137600058100012', 'EUR', "
        "(SELECT id FROM users WHERE username = 'admin' LIMIT 1))"
    )


def downgrade() -> None:
    ibans = (
        "'TR260006701000000072821701','TR210006701000000065488591','TR950006701000000065408689',"
        "'TR520003200000000048909295','TR410003200010700000015817','TR540003200000000031666442',"
        "'TR140001500158007301152442','TR540001500158048017640765',"
        "'TR870006200011500006297372','TR030006200011500009075800','TR660006200011500009075539',"
        "'TR230001200137600010100011','TR670001200137600010102420','TR210001200137600058100012'"
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
