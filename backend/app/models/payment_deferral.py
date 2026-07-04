"""PaymentDeferral — bir ödeme kaleminin KALICI ertelenmiş (öteleme) tarihi.

Nakit Koruma / Nakit Akım'da bir kalem ileri bir tarihe "ötelenince" bu tercih
kalıcı olarak burada saklanır. Herhangi bir ödeme türü (cari ödeme, çek, kredi
taksiti, KK ekstresi, planlı gider/gelir) için TEK tablo — `source_type` +
`source_id` doğal anahtarıyla ayrışır.

finance_event_service._upsert her FinanceEvent yazımında bu tabloya bakar: ilgili
kaynağın ötelemesi varsa `event_date` ertelenmiş tarihe çekilir → Sedna sync / FIFO
yeniden yazımı ötelemeyi korur (kalıcılık). `bank` türü ertelenmez (banka hareketi
gerçekleşmiş nakittir, en kalabalık FE türüdür → lookup dışı).
"""

from sqlalchemy import (
    BigInteger,
    Column,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)

from app.database import Base


class PaymentDeferral(Base):
    """Bir ödeme kaleminin kalıcı ertelenmiş tarihi (doğal anahtar: source_type+source_id)."""

    __tablename__ = "payment_deferrals"

    id           = Column(BigInteger, primary_key=True, autoincrement=True)
    source_type  = Column(String(30), nullable=False)
    source_id    = Column(BigInteger, nullable=False)
    deferred_to  = Column(Date, nullable=False)

    created_by   = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at   = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    note         = Column(Text, nullable=True)

    __table_args__ = (
        UniqueConstraint("source_type", "source_id", name="uq_payment_deferrals_source"),
        Index("idx_payment_deferrals_source", "source_type", "source_id"),
    )

    def __repr__(self) -> str:
        return (
            f"<PaymentDeferral id={self.id} {self.source_type}/{self.source_id} "
            f"→ {self.deferred_to}>"
        )
