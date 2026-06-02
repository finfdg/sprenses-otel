import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

from app.config import settings
from app.database import Base
from app.models import (
    User, Role, Module, RoleModulePermission,
    Conversation, ConversationMember, Message, PushSubscription,
    QualityTemplate, QualityTemplateSection, QualityTemplateField,
    QualityTemplateAssignee, QualityForm, QualityFormValue,
    CreditCardStatement, CreditCardTransaction,
)
# Models not in __init__ but needed for FK resolution
from app.models.credit_product import CreditProduct, CreditPayment  # noqa: F401
from app.models.cash_flow import CashFlow  # noqa: F401
from app.models.bank_account import BankAccount  # noqa: F401
from app.models.bank_statement import BankStatement  # noqa: F401
from app.models.bank_transaction import BankTransaction  # noqa: F401
from app.models.transaction_category import TransactionCategory  # noqa: F401
from app.models.exchange_rate import ExchangeRate  # noqa: F401
from app.models.vendor import Vendor  # noqa: F401
from app.models.vendor_upload import VendorUpload  # noqa: F401
from app.models.vendor_transaction import VendorTransaction  # noqa: F401
from app.models.notification import Notification  # noqa: F401

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# DB URL'yi .env'den al
config.set_main_option("sqlalchemy.url", settings.database_url)

target_metadata = Base.metadata


def run_migrations_offline():
    url = config.get_main_option("sqlalchemy.url")
    context.configure(url=url, target_metadata=target_metadata, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online():
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
