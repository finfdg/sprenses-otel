"""FinanceEvent — Tüm parasal hareketlerin merkezi olay tablosu.

Her banka işlemi, çek, kredi taksiti, kredi kartı ekstresi, avans ve cari ödeme
bu tabloya denormalize edilmiş bir kayıt olarak eklenir. Nakit akım listesi
6 farklı tablodan UNION yapmak yerine bu tek tabloyu sorgular.

Yazar: Sprenses Otel Yönetim Sistemi
"""

from sqlalchemy import (
    BigInteger,
    Boolean,
    Column,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import relationship

from app.database import Base

# Kaynak tipleri
SOURCE_BANK        = "bank"
SOURCE_CHECK       = "check"
SOURCE_CREDIT      = "credit"
SOURCE_CC_PAYMENT  = "cc_payment"
SOURCE_ADVANCE     = "advance"
SOURCE_VENDOR      = "vendor_payment"
SOURCE_TAX          = "tax"
SOURCE_RECURRING    = "recurring"
SOURCE_SALARY       = "salary"
SOURCE_WITHHOLDING  = "withholding"
SOURCE_RENT_INCOME  = "rent_income"
SOURCE_RENT_EXPENSE = "rent_expense"
SOURCE_SGK          = "sgk"
SOURCE_DIVIDEND     = "dividend"          # kâr payı NET ödemesi (ortaklara)
SOURCE_DIVIDEND_STOPAJ = "dividend_stopaj"  # kâr payı stopajı (vergi dairesine, ertesi ay muhtasar)

ALL_SOURCE_TYPES = (
    SOURCE_BANK, SOURCE_CHECK, SOURCE_CREDIT,
    SOURCE_CC_PAYMENT, SOURCE_ADVANCE, SOURCE_VENDOR,
    SOURCE_TAX, SOURCE_RECURRING, SOURCE_SALARY, SOURCE_WITHHOLDING,
    SOURCE_RENT_INCOME, SOURCE_RENT_EXPENSE, SOURCE_SGK,
    SOURCE_DIVIDEND, SOURCE_DIVIDEND_STOPAJ,
)

# Yön sabitleri
DIRECTION_INCOME  =  1
DIRECTION_EXPENSE = -1


class FinanceEvent(Base):
    """Denormalize edilmiş nakit akım olayı.

    Kayıt her zaman kaynak modülün write endpoint'i tarafından oluşturulur/güncellenir.
    Silme işlemlerinde de kaldırılır. Nakit akım listesi buradan okur.
    """
    __tablename__ = "finance_events"

    id             = Column(BigInteger, primary_key=True, autoincrement=True)
    event_date     = Column(Date, nullable=False, index=True)
    amount         = Column(Numeric(15, 2), nullable=False)   # daima pozitif
    direction      = Column(SmallInteger, nullable=False)     # +1 gelir, -1 gider
    currency       = Column(String(3), nullable=False, default="TRY")
    amount_try     = Column(Numeric(15, 2), nullable=True)    # önceden dönüştürülmüş TRY

    # Kaynak referansı — UniqueConstraint ile çift kayıt engellenir
    source_type    = Column(String(30), nullable=False)
    source_id      = Column(BigInteger, nullable=False)

    # Denormalize görüntü alanları (JOIN gerektirmez)
    description    = Column(Text, nullable=True)
    bank_name      = Column(String(100), nullable=True)
    bank_name_inferred = Column(Boolean, default=False, nullable=False, server_default="false")  # True → bank_name tahmin (çek komşu no'larından)
    account_id     = Column(Integer, nullable=True)
    iban           = Column(String(34), nullable=True)
    receipt_no     = Column(String(50), nullable=True)
    balance        = Column(Numeric(15, 2), nullable=True)
    payment_method = Column(String(50), nullable=True)
    match_number   = Column(Integer, nullable=True)
    check_no       = Column(String(50), nullable=True)
    event_status   = Column(String(20), nullable=True)        # pending/paid/cancelled/received
    vendor_code    = Column(String(50), nullable=True)
    tag_note       = Column(Text, nullable=True)
    tag_source     = Column(String(20), nullable=True)

    # FK referansları (filtreleme için)
    bank_account_id = Column(Integer, ForeignKey("bank_accounts.id", ondelete="SET NULL"), nullable=True)
    vendor_id       = Column(Integer, ForeignKey("vendors.id",        ondelete="SET NULL"), nullable=True)
    category_id     = Column(Integer, ForeignKey("transaction_categories.id", ondelete="SET NULL"), nullable=True)
    category_name   = Column(String(100), nullable=True)
    category_color  = Column(String(20),  nullable=True)

    # Çift sayım engeli
    is_realized    = Column(Boolean, default=False, nullable=False)  # banka doğruladı mı
    is_matched     = Column(Boolean, default=False, nullable=False)  # çift sayım engeli
    matched_event_id = Column(BigInteger, ForeignKey("finance_events.id", ondelete="SET NULL"), nullable=True)

    created_at     = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at     = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    # İlişkiler
    bank_account   = relationship("BankAccount",          foreign_keys=[bank_account_id], lazy="select")
    vendor         = relationship("Vendor",               foreign_keys=[vendor_id],       lazy="select")
    category       = relationship("TransactionCategory",  foreign_keys=[category_id],     lazy="select")
    matched_event  = relationship("FinanceEvent",         foreign_keys=[matched_event_id], remote_side=[id], lazy="select")

    __table_args__ = (
        UniqueConstraint("source_type", "source_id", name="uq_finance_events_source"),
        Index("idx_fe_date",         "event_date"),
        Index("idx_fe_date_dir",     "event_date", "direction"),
        Index("idx_fe_source",       "source_type", "source_id"),
        Index("idx_fe_bank_account", "bank_account_id"),
        Index("idx_fe_vendor",       "vendor_id"),
        Index("idx_fe_category",     "category_id"),
        Index("idx_fe_matched",      "is_matched"),
    )

    @property
    def type(self) -> str:
        """direction'dan tip döndür."""
        return "income" if self.direction == DIRECTION_INCOME else "expense"

    def __repr__(self) -> str:
        return (
            f"<FinanceEvent id={self.id} source={self.source_type}/{self.source_id} "
            f"date={self.event_date} amount={self.amount} dir={self.direction}>"
        )
